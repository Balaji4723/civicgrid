from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import resolution
from ..auth import require_capability, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..hashchain import list_events
from .. import settings
from ..models import CorroborationOutcome, Condition, DiscrepancyEvent, DiscrepancyStatus, Role, User
from ..serializers import ser_discrepancy, ser_event

router = APIRouter(prefix="/discrepancy", tags=["discrepancy"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)
auditor = require_capability("INDEPENDENT_VERIFIER")


def _actor(u: User) -> str:
    return f"{u.role.value.lower()}:{u.id}"


class EvidenceIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)
    evidence_ref: Optional[str] = Field(default=None, max_length=255)  # e.g. photo file name


class CorroborateIn(BaseModel):
    """Evidence-backed path: {"audit_id": n} - a COMPLETED audit by an independent auditor (server checks independence).
    Legacy path (only when REQUIRE_FILE_EVIDENCE=false): manual audit numbers, NOT evidence-backed, no independence check."""
    audit_id: Optional[int] = Field(default=None, ge=1)
    audit_quantity: Optional[int] = Field(default=None, gt=0)
    audit_condition: Optional[Condition] = None
    auditor: str = Field(default="AUD-07", max_length=60)


class InvestigateIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class ResolveIn(BaseModel):
    finding: str = Field(min_length=3, max_length=1000)
    attributed_to: Literal["NONE", "WORKER", "FACILITY", "PROCESS"] = "NONE"


class CloseIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


@router.get("")
def list_discrepancies(status: Optional[DiscrepancyStatus] = None, user: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(DiscrepancyEvent).order_by(DiscrepancyEvent.id)
    if status:
        stmt = stmt.where(DiscrepancyEvent.status == status)
    return [ser_discrepancy(d) for d in db.scalars(stmt)]


@router.get("/{discrepancy_id}")
def get_discrepancy(discrepancy_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    from .evidence import case_view
    d = db.get(DiscrepancyEvent, discrepancy_id)
    if not d:
        raise ServiceError(404, "DISCREPANCY_NOT_FOUND", f"No discrepancy #{discrepancy_id}.")
    events = [ser_event(e, i) for i, e in enumerate(list_events(db, d.load_id))]
    view = case_view(db, d, user)
    if user.role == Role.FACILITY:
        from ..evidence import can_view, evidence_for_discrepancy
        ok = {e.public_id for e in evidence_for_discrepancy(db, d) if can_view(db, user, e)}
        view["evidence"] = [e for e in view["evidence"] if e["id"] in ok]
    return {**ser_discrepancy(d), "trail": [e for e in events if e["payload"].get("discrepancy_id") == d.id], **view}


@router.post("/{discrepancy_id}/add-evidence")
def add_evidence(discrepancy_id: int, body: EvidenceIn, user: User = Depends(staff), db: Session = Depends(get_db)):
    d = resolution.add_evidence(db, discrepancy_id, _actor(user), body.note, body.evidence_ref,
                                require_files=settings.require_file_evidence(), user=user)
    db.commit()
    return ser_discrepancy(d)


@router.post("/{discrepancy_id}/corroborate")
def corroborate(discrepancy_id: int, body: CorroborateIn, user: User = Depends(auditor), db: Session = Depends(get_db)):
    legacy = body.audit_quantity is not None or body.audit_condition is not None
    if body.audit_id is not None and legacy:
        raise ServiceError(422, "AMBIGUOUS_CORROBORATION", "Send either audit_id or the legacy manual audit fields, not both.")
    if body.audit_id is not None:
        d, outcome, code, message = resolution.corroborate_with_audit(db, discrepancy_id, user, body.audit_id)
        db.commit()  # commit either way: a rejected audit is still recorded in the audit trail
        if outcome != CorroborationOutcome.ACCEPTED:
            raise ServiceError(409, "NOT_CORROBORATED", message, current_status=d.status.value, outcome=outcome.value, reason_code=code)
        return {**ser_discrepancy(d), "message": message, "outcome": outcome.value, "reason_code": code}
    if settings.require_file_evidence():
        raise ServiceError(422, "AUDIT_REQUIRED", "Corroboration needs a completed independent audit (pass audit_id). "
                           "Manually typed audit numbers are only accepted when REQUIRE_FILE_EVIDENCE=false and are never evidence-backed.")
    d, ok, message = resolution.corroborate(
        db, discrepancy_id, _actor(user), body.audit_quantity,
        body.audit_condition.value if body.audit_condition else None, body.auditor)
    db.commit()  # commit either way: a rejected audit signal is still recorded in the audit trail
    if not ok:
        raise ServiceError(409, "NOT_CORROBORATED", message, current_status=d.status.value)
    return {**ser_discrepancy(d), "message": message}


@router.post("/{discrepancy_id}/investigate")
def investigate(discrepancy_id: int, body: InvestigateIn, user: User = Depends(auditor), db: Session = Depends(get_db)):
    d = resolution.investigate(db, discrepancy_id, _actor(user), body.note)
    db.commit()
    return ser_discrepancy(d)


@router.post("/{discrepancy_id}/resolve")
def resolve(discrepancy_id: int, body: ResolveIn, user: User = Depends(auditor), db: Session = Depends(get_db)):
    d = resolution.resolve(db, discrepancy_id, _actor(user), body.finding, body.attributed_to)
    db.commit()
    return ser_discrepancy(d)


@router.post("/{discrepancy_id}/close")
def close(discrepancy_id: int, body: CloseIn, user: User = Depends(auditor), db: Session = Depends(get_db)):
    d = resolution.close(db, discrepancy_id, _actor(user), body.note)
    db.commit()
    return ser_discrepancy(d)
