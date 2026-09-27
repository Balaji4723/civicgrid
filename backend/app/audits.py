"""Audit lifecycle. An audit is an INDEPENDENT physical check of a received load.

    selected (RANDOM | RISK_BASED | MANUAL, with a stored reason)  ->  PENDING
    an independent auditor starts it                               ->  IN_PROGRESS
    auditor attaches file evidence + submits quantity/condition    ->  COMPLETED
    (PENDING | IN_PROGRESS may be CANCELLED by a municipal admin, with a reason)

Every step appends to the load's SHA-256 chain (append_event). A completed audit does nothing by itself: it becomes
a corroborating signal only when it is submitted to a discrepancy (resolution.corroborate_with_audit), where the
Cross-Check Engine decides. Nothing in this module attributes responsibility to anyone.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit_selection as sel
from . import settings
from .crosscheck import quantity_mismatch, signals_agree
from .errors import ServiceError
from .evidence import actor_of
from .hashchain import append_event
from .independence import Parties, auditor_violations, get_parties
from .models import (Audit, AuditCorroboration, AuditMethod, AuditSelectionRun, AuditStatus, DigitalLoad, DiscrepancyEvent, Evidence,
                     EvidenceCategory, EvidenceKind, EvidenceSide, Facility, LoadStatus, ReceivingRecord, Route, User, Worker, utcnow)
from .services import build_declaration, get_load_or_404
from .settings import AuditConfig

MIN_REASON = 10


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------- creation
def _create_audit(db: Session, load: DigitalLoad, *, method: AuditMethod, reason: str, risk: Optional[dict], run: Optional[AuditSelectionRun],
                  user: Optional[User], now: datetime) -> Audit:
    if len(reason.strip()) < MIN_REASON:
        raise ServiceError(422, "REASON_REQUIRED", f"An audit cannot be selected without a recorded reason (min {MIN_REASON} characters).")
    if load.status not in (LoadStatus.VERIFIED, LoadStatus.DISPUTED):
        raise ServiceError(409, "LOAD_NOT_AUDITABLE", f"{load.id} is {load.status.value}. Only loads that have been received and cross-checked can be audited.")
    parties = get_parties(db, load)
    if db.scalars(select(Audit.id).where(Audit.load_id == load.id, Audit.status.in_([AuditStatus.PENDING, AuditStatus.IN_PROGRESS]))).first():
        raise ServiceError(409, "AUDIT_ALREADY_OPEN", f"{load.id} already has an open audit.")
    from .models import AuditTargetType
    a = Audit(target_type=AuditTargetType.DIGITAL_LOAD, load_id=load.id, worker_id=parties.worker_id, facility_id=parties.receiving_facility_id, method=method,
              risk_score=risk["score"] if risk else None, risk_factors={"factors": risk["factors"]} if risk else {},
              selection_reason=reason.strip(), run_id=run.id if run else None, selected_at=now,
              selected_by_user_id=user.id if user else None, status=AuditStatus.PENDING)
    db.add(a)
    try:
        db.flush()
    except IntegrityError as e:   # the partial unique index caught a concurrent selection
        raise ServiceError(409, "AUDIT_ALREADY_OPEN", f"{load.id} already has an open audit.") from e
    payload: dict[str, Any] = {"audit_id": a.id, "method": method.value, "risk_score": a.risk_score, "run_id": a.run_id,
                               "selection_reason_sha256": _sha(a.selection_reason)}
    if method != AuditMethod.MANUAL:
        payload["selection_reason"] = a.selection_reason          # engine-generated, no free text: safe to keep in the chain
    append_event(db, load.id, "AUDIT_SELECTED", payload, actor=actor_of(user) if user else "system:audit-engine", now=now)
    return a


def create_manual_audit(db: Session, user: User, load_id: str, reason: str, now: Optional[datetime] = None) -> Audit:
    load = get_load_or_404(db, load_id, lock=True)
    now = now or utcnow()
    risk = sel.compute_risk(db, load, settings.load_audit_config(), now)     # informational only for MANUAL
    return _create_audit(db, load, method=AuditMethod.MANUAL, reason=reason, risk=risk, run=None, user=user, now=now)


def run_selection(db: Session, *, method: AuditMethod, user: Optional[User], overrides: Optional[dict] = None, seed: Optional[int] = None,
                  dry_run: bool = False, now: Optional[datetime] = None) -> dict[str, Any]:
    if method == AuditMethod.MANUAL:
        raise ServiceError(422, "BAD_METHOD", "MANUAL audits are created one at a time with a reason.")
    overrides = overrides or {}
    sel.check_method_params(overrides.get("random_sample_pct"), overrides.get("risk_threshold"))
    try:
        cfg: AuditConfig = settings.load_audit_config(overrides)
    except ValueError as e:
        raise ServiceError(422, "BAD_CONFIG", str(e)) from e
    now = now or utcnow()
    eligible = sel.eligible_loads(db, cfg, now)
    by_id = {l.id: l for l in eligible}
    candidates: list[dict] = []
    chosen: list[tuple[str, str, Optional[dict]]] = []       # (load_id, reason, risk)

    if method == AuditMethod.RANDOM:
        seed = seed if seed is not None else sel.new_seed()
        picked, k = sel.draw_random(list(by_id), cfg.random_sample_pct, seed)
        reason = sel.random_reason(k, len(by_id), cfg.random_sample_pct, seed)
        for lid in sorted(by_id):
            candidates.append({"load_id": lid, "selected": lid in picked, "risk_score": None})
        chosen = [(lid, reason, None) for lid in picked]
    else:
        seed = None
        scored = sorted((sel.compute_risk(db, l, cfg, now) for l in eligible), key=lambda r: (-r["score"], r["load_id"]))
        picked_ids = [r["load_id"] for r in scored if r["score"] >= cfg.risk_threshold][: cfg.risk_max_selected]
        for r in scored:
            candidates.append({"load_id": r["load_id"], "selected": r["load_id"] in picked_ids, "risk_score": r["score"], "top_factors": r["top"],
                               "factors": r["factors"]})
        chosen = [(r["load_id"], sel.risk_reason(r, cfg.risk_threshold), r) for r in scored if r["load_id"] in picked_ids]

    result: dict[str, Any] = {"method": method.value, "dry_run": dry_run, "seed": seed, "config": cfg.to_dict(), "eligible_count": len(eligible),
                              "selected_count": len(chosen), "candidates": candidates, "audits": [], "run_id": None}
    if dry_run:
        return result

    run = AuditSelectionRun(method=method, seed=seed, config_json=cfg.to_dict(), eligible_count=len(eligible), selected_count=len(chosen),
                            details_json={"candidates": candidates}, executed_at=now, executed_by_user_id=user.id if user else None)
    db.add(run)
    db.flush()
    result["run_id"] = run.id
    for lid, reason, risk in chosen:
        a = _create_audit(db, by_id[lid], method=method, reason=reason, risk=risk, run=run, user=user, now=now)
        result["audits"].append(a)
    return result


# ---------------------------------------------------------------- lifecycle
def _lock(db: Session, audit_id: int) -> Audit:
    a = db.execute(select(Audit).where(Audit.id == audit_id).with_for_update()).scalar_one_or_none()
    if a is None:
        raise ServiceError(404, "AUDIT_NOT_FOUND", f"No audit #{audit_id}.")
    return a


def _require_independent(db: Session, user: User, audit: Audit) -> Parties:
    parties = get_parties(db, db.get(DigitalLoad, audit.load_id))
    viol = auditor_violations(user, parties)
    if viol:
        raise ServiceError(403, "NOT_INDEPENDENT", "You cannot audit this load: " + " ".join(v["message"] for v in viol), violations=viol)
    return parties


def start_audit(db: Session, audit_id: int, user: User, now: Optional[datetime] = None) -> Audit:
    a = _lock(db, audit_id)
    _require_independent(db, user, a)
    if a.status != AuditStatus.PENDING:
        raise ServiceError(409, "INVALID_AUDIT_STATE", f"Audit #{a.id} is {a.status.value}; only a PENDING audit can be started.")
    now = now or utcnow()
    a.status, a.auditor_id, a.started_at = AuditStatus.IN_PROGRESS, user.id, now
    append_event(db, a.load_id, "AUDIT_STARTED", {"audit_id": a.id, "auditor": actor_of(user), "auditor_role": user.role.value}, actor=actor_of(user), now=now)
    return a


def assert_can_add_evidence(db: Session, audit_id: int, user: User) -> Audit:
    a = _lock(db, audit_id)
    if a.status != AuditStatus.IN_PROGRESS or a.auditor_id != user.id:
        raise ServiceError(409, "NOT_YOUR_ACTIVE_AUDIT", "Evidence can only be added by the auditor of an IN_PROGRESS audit.")
    _require_independent(db, user, a)
    return a


def verdicts(decl: dict, rec: ReceivingRecord, audit_qty: int, audit_condition: str) -> dict[str, str]:
    """Which recorded signal does the audit agree with, per dimension? Deterministic rules, no attribution."""
    from .config import QUANTITY_TOLERANCE as TOL
    out: dict[str, str] = {}
    a_w = not quantity_mismatch(decl["quantity"], audit_qty, TOL)
    a_f = signals_agree("QUANTITY", {"quantity": rec.quantity}, {"quantity": audit_qty}, TOL)
    out["QUANTITY"] = "BOTH_AGREE" if a_w and a_f else "SUPPORTS_WORKER" if a_w else "SUPPORTS_FACILITY" if a_f else "INCONCLUSIVE"
    a_w = not (decl["stream"] == "SEGREGATED" and audit_condition == "UNACCEPTABLE")
    a_f = audit_condition == rec.condition.value
    out["STREAM"] = "BOTH_AGREE" if a_w and a_f else "SUPPORTS_WORKER" if a_w else "SUPPORTS_FACILITY" if a_f else "INCONCLUSIVE"
    return out


def overall_verdict(v: dict[str, str]) -> str:
    vals = set(v.values())
    if "SUPPORTS_FACILITY" in vals:
        return "SUPPORTS_FACILITY"
    if "INCONCLUSIVE" in vals:
        return "INCONCLUSIVE"
    if "SUPPORTS_WORKER" in vals:
        return "SUPPORTS_WORKER"
    return "BOTH_AGREE"


def complete_audit(db: Session, audit_id: int, user: User, *, quantity: int, condition: str, observations: str,
                   now: Optional[datetime] = None) -> Audit:
    a = _lock(db, audit_id)
    if a.status != AuditStatus.IN_PROGRESS or a.auditor_id != user.id:
        raise ServiceError(409, "NOT_YOUR_ACTIVE_AUDIT", "Only the auditor of an IN_PROGRESS audit can submit its result.")
    _require_independent(db, user, a)
    files = db.scalars(select(Evidence).where(Evidence.audit_id == a.id, Evidence.kind == EvidenceKind.FILE_EVIDENCE).order_by(Evidence.id)).all()
    if settings.require_file_evidence() and not files:
        raise ServiceError(422, "AUDIT_EVIDENCE_REQUIRED", "Attach at least one photo or video to the audit before submitting its result.")
    load = db.get(DigitalLoad, a.load_id)
    rec = db.scalars(select(ReceivingRecord).where(ReceivingRecord.load_id == load.id).order_by(ReceivingRecord.id)).first()
    decl = build_declaration(db, load)
    now = now or utcnow()
    v = verdicts(decl, rec, quantity, condition)
    overall = overall_verdict(v)
    followup = overall == "INCONCLUSIVE"
    a.result_json = {"quantity": quantity, "condition": condition, "observations": observations.strip(), "verdicts": v, "overall": overall,
                     "requires_followup": followup, "evidence_ids": [e.public_id for e in files]}
    a.status, a.completed_at = AuditStatus.COMPLETED, now
    ev = append_event(db, a.load_id, "AUDIT_COMPLETED",
                      {"audit_id": a.id, "auditor": actor_of(user), "quantity": quantity, "condition": condition, "verdicts": v, "overall": overall,
                       "requires_followup": followup, "observations_sha256": _sha(observations.strip()),
                       "evidence": [{"id": e.public_id, "sha256": e.sha256} for e in files]}, actor=actor_of(user), now=now)
    from .evidence import new_public_id
    side = {"SUPPORTS_WORKER": EvidenceSide.WORKER, "SUPPORTS_FACILITY": EvidenceSide.FACILITY}.get(overall, EvidenceSide.NEUTRAL)
    db.add(Evidence(public_id=new_public_id(), kind=EvidenceKind.AUDIT_RESULT, side=side, category=EvidenceCategory.AUDIT_OBSERVATION,
                    load_id=a.load_id, audit_id=a.id, uploader_id=user.id, uploader_actor=actor_of(user), uploader_role=user.role.value,
                    description=observations.strip(), event_id=ev.id, created_at=now))
    return a


def cancel_audit(db: Session, audit_id: int, user: User, reason: str, now: Optional[datetime] = None) -> Audit:
    a = _lock(db, audit_id)
    if a.status not in (AuditStatus.PENDING, AuditStatus.IN_PROGRESS):
        raise ServiceError(409, "INVALID_AUDIT_STATE", f"Audit #{a.id} is {a.status.value} and cannot be cancelled.")
    if len(reason.strip()) < MIN_REASON:
        raise ServiceError(422, "REASON_REQUIRED", f"A cancellation needs a recorded reason (min {MIN_REASON} characters).")
    now = now or utcnow()
    a.status, a.cancelled_at, a.cancel_reason = AuditStatus.CANCELLED, now, reason.strip()
    append_event(db, a.load_id, "AUDIT_CANCELLED", {"audit_id": a.id, "reason_sha256": _sha(reason.strip())}, actor=actor_of(user), now=now)
    return a


# ---------------------------------------------------------------- read models
def audit_evidence_summary(db: Session, a: Audit, parties: Parties) -> dict:
    from .independence import evidence_independence
    rows = db.scalars(select(Evidence).where(Evidence.audit_id == a.id).order_by(Evidence.id)).all()
    files = [e for e in rows if e.kind == EvidenceKind.FILE_EVIDENCE]
    indep = 0
    for e in files:
        if evidence_independence(e, db.get(User, e.uploader_id) if e.uploader_id else None, parties)["independent"]:
            indep += 1
    return {"files": len(files), "independent_files": indep, "has_result": any(e.kind == EvidenceKind.AUDIT_RESULT for e in rows)}


def ser_audit(db: Session, a: Audit, viewer: Optional[User] = None, detail: bool = False) -> dict:
    load = db.get(DigitalLoad, a.load_id)
    parties = get_parties(db, load)
    route = db.get(Route, load.route_id)
    worker = db.get(Worker, a.worker_id) if a.worker_id else None
    facility = db.get(Facility, a.facility_id) if a.facility_id else None
    auditor = db.get(User, a.auditor_id) if a.auditor_id else None
    actor_user = db.get(User, a.actor_user_id) if getattr(a, "actor_user_id", None) else None
    discs = db.scalars(select(DiscrepancyEvent).where(DiscrepancyEvent.load_id == a.load_id).order_by(DiscrepancyEvent.id)).all()
    viol = auditor_violations(viewer, parties) if viewer else None
    
    target_type_str = a.target_type.value if getattr(a, "target_type", None) else "DIGITAL_LOAD"
    
    actor_info = None
    if actor_user:
        actor_info = {"id": actor_user.id, "name": actor_user.name, "role": actor_user.role.value}
    elif worker:
        actor_info = {"name": worker.name, "role": "WORKER"}

    # Auditor is strictly the independent verifier (for digital load verification) or system gate.
    # Worker is NEVER displayed as the auditor.
    auditor_info = None
    if target_type_str == "DIGITAL_LOAD":
        if auditor:
            auditor_info = {"id": auditor.id, "name": auditor.name, "role": auditor.role.value}
    else:
        # Collection event audit: system-triggered random gate
        auditor_info = None

    out: dict[str, Any] = {
        "id": a.id, "target_type": target_type_str, "load_id": a.load_id,
        "household_id": getattr(a, "household_id", None),
        "collection_event_id": getattr(a, "collection_event_id", None),
        "ward": route.ward if route else None, "worker": worker.name if worker else None,
        "actor": actor_info,
        "facility": facility.name if facility else None, "method": a.method.value, "risk_score": a.risk_score,
        "selection_reason": a.selection_reason, "run_id": a.run_id, "selected_at": a.selected_at.isoformat(),
        "selected_by": "system (audit engine)" if a.selected_by_user_id is None else (db.get(User, a.selected_by_user_id).name),
        "status": a.status.value, "auditor": auditor_info,
        "started_at": a.started_at.isoformat() if a.started_at else None, "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        "discrepancies": [{"id": d.id, "type": d.type.value, "status": d.status.value} for d in discs],
        "evidence_status": audit_evidence_summary(db, a, parties),
        "result_overall": (a.result_json or {}).get("overall"),
        "can_conduct": None if viol is None else not viol, "independence_violations": viol,
    }
    if detail:
        load_d = build_declaration(db, load)
        rec = db.scalars(select(ReceivingRecord).where(ReceivingRecord.load_id == a.load_id).order_by(ReceivingRecord.id)).first()
        out.update({
            "risk_factors": (a.risk_factors or {}).get("factors", []), "result": a.result_json, "cancel_reason": a.cancel_reason,
            "declaration": load_d,
            "receiving": {"quantity": rec.quantity, "condition": rec.condition.value, "facility": facility.name if facility else None} if rec else None,
            "run": None if a.run_id is None else _run_summary(db, a.run_id),
            "corroborations": [{"discrepancy_id": c.discrepancy_id, "outcome": c.outcome.value, "reason_code": c.reason_code, "evaluated_at": c.evaluated_at.isoformat(),
                                "detail": c.detail_json}
                               for c in db.scalars(select(AuditCorroboration).where(AuditCorroboration.audit_id == a.id).order_by(AuditCorroboration.id))],
        })
    return out


def _run_summary(db: Session, run_id: int) -> dict:
    r = db.get(AuditSelectionRun, run_id)
    return {"id": r.id, "method": r.method.value, "seed": r.seed, "eligible_count": r.eligible_count, "selected_count": r.selected_count,
            "config": r.config_json, "executed_at": r.executed_at.isoformat()}
