"""Audit Center API. Workers have no access. MUNICIPAL_ADMIN may select/cancel; FACILITY and MUNICIPAL_ADMIN may conduct audits
they are independent for (enforced from the data in audits.py, not from the role name)."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audits as svc
from .. import evidence as ev_svc
from .. import settings
from ..auth import require_capability, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..independence import auditor_violations, get_parties
from ..models import (Audit, AuditMethod, AuditSelectionRun, AuditStatus, DigitalLoad, EvidenceCategory, EvidenceSide, Evidence, Role, User)
from .evidence import limit_body

router = APIRouter(prefix="/audit-center", tags=["audit center"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)
operator = require_capability("INDEPENDENT_VERIFIER")
verifier = require_capability("INDEPENDENT_VERIFIER")
admin = require_roles(Role.MUNICIPAL_ADMIN)


class SelectionRunIn(BaseModel):
    method: Literal["RANDOM", "RISK_BASED"]
    dry_run: bool = False
    seed: Optional[int] = Field(default=None, ge=0, le=2**62)
    random_sample_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    risk_threshold: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    risk_max_selected: Optional[int] = Field(default=None, ge=1, le=50)


class ManualIn(BaseModel):
    load_id: str = Field(min_length=3, max_length=20)
    reason: str = Field(min_length=10, max_length=1000)


class CompleteIn(BaseModel):
    quantity: int = Field(gt=0, le=100000)
    condition: Literal["ACCEPTABLE", "UNACCEPTABLE"]
    observations: str = Field(min_length=5, max_length=2000)


class CancelIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


def _visible(db: Session, user: User, a: Audit) -> bool:
    """Admins see every audit. Collection event audits are visible to staff for oversight.
    For digital load audits, a facility user is recused from audits of loads their own facility received."""
    if user.role == Role.MUNICIPAL_ADMIN or a.auditor_id == user.id:
        return True
    from ..models import AuditTargetType
    if getattr(a, "target_type", None) == AuditTargetType.COLLECTION_EVENT:
        return True
    return not auditor_violations(user, get_parties(db, db.get(DigitalLoad, a.load_id)))


def _get_visible(db: Session, user: User, audit_id: int) -> Audit:
    a = db.get(Audit, audit_id)
    if a is None or not _visible(db, user, a):
        raise ServiceError(404, "AUDIT_NOT_FOUND", f"No audit #{audit_id}.")
    return a


@router.get("/config")
def config(user: User = Depends(staff)):
    return settings.load_audit_config().to_dict()


@router.get("/summary")
def summary(user: User = Depends(staff), db: Session = Depends(get_db)):
    rows = [a for a in db.scalars(select(Audit)) if _visible(db, user, a)]
    by = lambda f: {k: sum(1 for a in rows if f(a) == k) for k in sorted({f(a) for a in rows})}
    return {"total": len(rows), "by_status": by(lambda a: a.status.value), "by_method": by(lambda a: a.method.value)}


@router.post("/selection-runs")
def selection_run(body: SelectionRunIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    out = svc.run_selection(db, method=AuditMethod(body.method), user=user, seed=body.seed, dry_run=body.dry_run,
                            overrides={"random_sample_pct": body.random_sample_pct, "risk_threshold": body.risk_threshold,
                                       "risk_max_selected": body.risk_max_selected})
    if not body.dry_run:
        db.commit()
    out["audits"] = [svc.ser_audit(db, a, user) for a in out["audits"]]
    return out


@router.get("/selection-runs")
def list_runs(user: User = Depends(staff), db: Session = Depends(get_db)):
    return [{"id": r.id, "method": r.method.value, "seed": r.seed, "eligible_count": r.eligible_count, "selected_count": r.selected_count,
             "executed_at": r.executed_at.isoformat(), "config": r.config_json} for r in db.scalars(select(AuditSelectionRun).order_by(AuditSelectionRun.id.desc()).limit(50))]


@router.post("/audits")
def manual_audit(body: ManualIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    a = svc.create_manual_audit(db, user, body.load_id.strip().upper(), body.reason)
    db.commit()
    return svc.ser_audit(db, a, user, detail=True)


@router.get("/audits")
def list_audits(status: Optional[AuditStatus] = None, method: Optional[AuditMethod] = None,
                target_type: Optional[str] = None,
                user: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(Audit).order_by(Audit.id.desc())
    if status:
        stmt = stmt.where(Audit.status == status)
    if method:
        stmt = stmt.where(Audit.method == method)
    if target_type:
        from ..models import AuditTargetType
        try:
            tt = AuditTargetType(target_type)
            stmt = stmt.where(Audit.target_type == tt)
        except ValueError:
            pass
    return [svc.ser_audit(db, a, user) for a in db.scalars(stmt) if _visible(db, user, a)]


@router.get("/audits/{audit_id}")
def audit_detail(audit_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    return svc.ser_audit(db, _get_visible(db, user, audit_id), user, detail=True)


@router.post("/audits/{audit_id}/start")
def start(audit_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    _get_visible(db, user, audit_id)
    a = svc.start_audit(db, audit_id, user)
    db.commit()
    return svc.ser_audit(db, a, user, detail=True)


@router.post("/audits/{audit_id}/evidence")
def add_evidence(
    audit_id: int, _: None = Depends(limit_body), file: UploadFile = File(...), side: Optional[EvidenceSide] = Form(None),
    category: EvidenceCategory = Form(EvidenceCategory.AUDIT_OBSERVATION), description: str = Form(..., min_length=3, max_length=1000),
    latitude: Optional[float] = Form(None, ge=-90, le=90, allow_inf_nan=False), longitude: Optional[float] = Form(None, ge=-180, le=180, allow_inf_nan=False),
    accuracy_m: Optional[float] = Form(None, ge=0, le=100000, allow_inf_nan=False),
    user: User = Depends(staff), db: Session = Depends(get_db),
):
    _get_visible(db, user, audit_id)
    a = svc.assert_can_add_evidence(db, audit_id, user)
    load = db.get(DigitalLoad, a.load_id)
    parties = get_parties(db, load)
    ev = ev_svc.store_file_evidence(db, user=user, load=load, fileobj=file.file, filename=file.filename, declared_content_type=file.content_type,
                                    side=side or EvidenceSide.NEUTRAL, category=category, description=description, lat=latitude, lng=longitude,
                                    accuracy_m=accuracy_m, audit=a)
    db.commit()
    return ev_svc.ser_evidence(db, ev, parties)


@router.post("/audits/{audit_id}/complete")
def complete(audit_id: int, body: CompleteIn, user: User = Depends(staff), db: Session = Depends(get_db)):
    _get_visible(db, user, audit_id)
    a = svc.complete_audit(db, audit_id, user, quantity=body.quantity, condition=body.condition, observations=body.observations)
    db.commit()
    return svc.ser_audit(db, a, user, detail=True)


@router.post("/audits/{audit_id}/cancel")
def cancel(audit_id: int, body: CancelIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    a = svc.cancel_audit(db, audit_id, user, body.reason)
    db.commit()
    return svc.ser_audit(db, a, user, detail=True)


@router.get("/audits/{audit_id}/evidence")
def audit_case_evidence(audit_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    """Everything on the audited load, for the auditor to inspect: worker, facility, neutral and audit evidence."""
    a = _get_visible(db, user, audit_id)
    load = db.get(DigitalLoad, a.load_id)
    parties = get_parties(db, load)
    rows = db.scalars(select(Evidence).where(Evidence.load_id == a.load_id).order_by(Evidence.id)).all()
    return [ev_svc.ser_evidence(db, e, parties) for e in rows if ev_svc.can_view(db, user, e)
            or (user.role == Role.FACILITY and a.auditor_id == user.id)]
