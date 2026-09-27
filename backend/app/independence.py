"""Who is independent of whom. Enforced on the server, never only in the UI.

The signals in a discrepancy come from PARTIES:
    worker    - declared the load (user accounts linked to workers.id == route.worker_id)
    recorder  - the user who recorded the facility receiving record (receiving_records.recorded_by_user_id)
    facility  - the facility organisation that received it (receiving_records.facility_id)

An AUDITOR / evidence uploader is independent only if they are none of those. What this model can NOT see:
conflicts of interest outside the database (relatives, shared management, a municipal admin who supervises
both sides). "Independent" here means "a different account, not the worker, not the recording user, and not
another user of the receiving facility". README documents this limitation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DigitalLoad, Evidence, EvidenceKind, ReceivingRecord, Role, Route, User


@dataclass
class Parties:
    load_id: str
    worker_id: Optional[int]
    worker_user_ids: set[int] = field(default_factory=set)
    recorder_user_id: Optional[int] = None
    receiving_facility_id: Optional[int] = None


def get_parties(db: Session, load: DigitalLoad) -> Parties:
    route = db.get(Route, load.route_id)
    worker_id = route.worker_id if route else None
    worker_users = set(db.scalars(select(User.id).where(User.worker_id == worker_id))) if worker_id else set()
    rec = db.scalars(select(ReceivingRecord).where(ReceivingRecord.load_id == load.id).order_by(ReceivingRecord.id)).first()
    return Parties(load.id, worker_id, worker_users, rec.recorded_by_user_id if rec else None, rec.facility_id if rec else None)


def auditor_violations(user: User, parties: Parties) -> list[dict]:
    """Empty list = independent. Each violation: {code, message}."""
    v: list[dict] = []
    if user.role == Role.WORKER:
        v.append({"code": "ROLE_WORKER", "message": "Workers cannot conduct audits."})
    if user.id in parties.worker_user_ids or (user.worker_id is not None and user.worker_id == parties.worker_id):
        v.append({"code": "RESPONSIBLE_WORKER", "message": "This account belongs to the worker responsible for the collection (self-audit)."})
    if parties.recorder_user_id is not None and user.id == parties.recorder_user_id:
        v.append({"code": "RECORDED_FACILITY_SIGNAL", "message": "This user recorded the facility receiving record that is being checked."})
    if user.role == Role.FACILITY and parties.receiving_facility_id is not None and user.facility_id == parties.receiving_facility_id:
        v.append({"code": "SAME_FACILITY_ORGANISATION", "message": "This user works for the facility that received the load."})
    return v


_EVIDENCE_REASON = {
    "RESPONSIBLE_WORKER": "Provided by the worker responsible for this load, so it cannot independently corroborate their own declaration.",
    "ROLE_WORKER": "Provided by a worker, so it cannot independently corroborate a worker's declaration.",
    "RECORDED_FACILITY_SIGNAL": "Provided by the person who recorded the facility receiving record, so it cannot independently corroborate their own record.",
    "SAME_FACILITY_ORGANISATION": "Provided by the facility that received the load, so it is not independent of the facility's own record.",
}


def evidence_independence(ev: Evidence, uploader: Optional[User], parties: Parties) -> dict:
    """Can this evidence item count as an INDEPENDENT signal for this load's discrepancy? (reasons are about the EVIDENCE)"""
    reasons: list[str] = []
    if ev.kind == EvidenceKind.NOTE:
        reasons.append("A note is not evidence: nothing was uploaded and nothing can be verified.")
    if ev.duplicate_of_id is not None:
        reasons.append("Identical file content was already submitted before, so this adds no independent information.")
    if uploader is None:
        reasons.append("Uploader account is unknown (legacy/seed entry).")
    else:
        codes = [v["code"] for v in auditor_violations(uploader, parties)]
        if "RESPONSIBLE_WORKER" in codes:
            codes = [c for c in codes if c != "ROLE_WORKER"]     # one clear reason, not two
        reasons.extend(_EVIDENCE_REASON[c] for c in codes)
    return {"independent": not reasons, "reasons": reasons}
