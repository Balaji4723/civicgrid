"""CORE COMPONENT 2 - Discrepancy Resolution state machine.

    FLAGGED -> EVIDENCE_PENDING -> CORROBORATED -> INVESTIGATING -> RESOLVED -> CLOSED

Only these forward transitions are valid; anything else raises a 409 with the current
status and the one action that IS allowed. Every transition appends a hash-chained
event_log row. CORROBORATED can only be reached through the Cross-Check Engine.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from . import crosscheck
from .errors import ServiceError
from .hashchain import append_event
from .models import (Audit, AuditCorroboration, AuditStatus, AuditTargetType, CorroborationOutcome, DiscrepancyEvent, DiscrepancyStatus as S,
                     DiscrepancyType, Evidence, EvidenceKind, EvidenceSide, Role, User, utcnow)
from .independence import auditor_violations, evidence_independence, get_parties
from .services import build_declaration, get_load_or_404, sync_load_status_after_close

# action -> (required current status, next status)
TRANSITIONS: dict[str, tuple[S, S]] = {
    "add-evidence": (S.FLAGGED, S.EVIDENCE_PENDING),
    "corroborate": (S.EVIDENCE_PENDING, S.CORROBORATED),
    "investigate": (S.CORROBORATED, S.INVESTIGATING),
    "resolve": (S.INVESTIGATING, S.RESOLVED),
    "close": (S.RESOLVED, S.CLOSED),
}
NEXT_ACTION: dict[S, Optional[str]] = {frm: act for act, (frm, _) in TRANSITIONS.items()}
NEXT_ACTION[S.CLOSED] = None


def next_action(status: S) -> Optional[str]:
    return NEXT_ACTION.get(status)


def _load(db: Session, discrepancy_id: int) -> DiscrepancyEvent:
    d = db.execute(select(DiscrepancyEvent).where(DiscrepancyEvent.id == discrepancy_id).with_for_update()).scalar_one_or_none()
    if not d:
        raise ServiceError(404, "DISCREPANCY_NOT_FOUND", f"No discrepancy #{discrepancy_id}.")
    return d


def _require(d: DiscrepancyEvent, action: str) -> None:
    required, _ = TRANSITIONS[action]
    if d.status != required:
        allowed = next_action(d.status)
        raise ServiceError(
            409, "INVALID_TRANSITION",
            f"Cannot '{action}' a discrepancy in status {d.status.value}. "
            + (f"The only valid next step is '{allowed}'." if allowed else "It is CLOSED and cannot change."),
            current_status=d.status.value, requested_action=action, allowed_action=allowed,
        )


def _details(d: DiscrepancyEvent) -> dict:
    return copy.deepcopy(d.details_json or {})


def _save(d: DiscrepancyEvent, details: dict) -> None:
    d.details_json = details
    flag_modified(d, "details_json")


def add_evidence(db, discrepancy_id: int, actor: str, note: str, evidence_ref: Optional[str] = None, now: Optional[datetime] = None,
                 *, require_files: bool = False, user: Optional[User] = None):
    """FLAGGED -> EVIDENCE_PENDING.

    require_files=True  (REQUIRE_FILE_EVIDENCE): at least one uploaded FILE_EVIDENCE item must already be attached to this
                        discrepancy. A note alone is refused.
    require_files=False (legacy): a note is accepted, but it is stored as kind NOTE and the event says evidence_backed=false.
                        A note is never presented as file evidence.
    """
    from .evidence import store_note_evidence, evidence_for_discrepancy
    d = _load(db, discrepancy_id)
    _require(d, "add-evidence")
    now = now or utcnow()
    files = [e for e in evidence_for_discrepancy(db, d) if e.kind == EvidenceKind.FILE_EVIDENCE]
    if require_files and not files:
        raise ServiceError(422, "FILE_EVIDENCE_REQUIRED",
                           "Upload at least one photo or video to this discrepancy first. A note on its own is not evidence.")
    details = _details(d)
    item = {"note": note, "evidence_ref": evidence_ref, "by": actor, "at": now.isoformat(), "evidence_backed": bool(files)}
    details.setdefault("evidence", []).append(item)
    _save(d, details)
    if not files:   # legacy path: keep the note as an explicit NOTE row so it can never be mistaken for a file
        store_note_evidence(db, user=user, actor=actor, load=get_load_or_404(db, d.load_id), discrepancy=d,
                            note=note, side=EvidenceSide.NEUTRAL, now=now)
    d.status = S.EVIDENCE_PENDING
    payload = {"discrepancy_id": d.id, "note": note, "evidence_ref": evidence_ref, "status": d.status.value,
               "evidence_backed": bool(files), "evidence_kind": "FILE_EVIDENCE" if files else "NOTE",
               "evidence": [{"id": e.public_id, "sha256": e.sha256} for e in files]}
    append_event(db, d.load_id, "DISCREPANCY_EVIDENCE_ADDED", payload, actor=actor, now=now)
    return d


def corroborate(db, discrepancy_id: int, actor: str, audit_quantity: Optional[int], audit_condition: Optional[str],
                auditor: str, now: Optional[datetime] = None):
    """Second, independent signal (simulated audit). Returns (discrepancy, corroborated?, message)."""
    d = _load(db, discrepancy_id)
    _require(d, "corroborate")
    now = now or utcnow()
    details = _details(d)
    load = get_load_or_404(db, d.load_id)
    declaration = build_declaration(db, load)
    first_signal = details["receiving"]

    if d.type == DiscrepancyType.QUANTITY and audit_quantity is None:
        raise ServiceError(422, "AUDIT_QUANTITY_REQUIRED", "A QUANTITY discrepancy needs the audited quantity (kg).")
    if d.type == DiscrepancyType.STREAM and audit_condition is None:
        raise ServiceError(422, "AUDIT_CONDITION_REQUIRED", "A STREAM discrepancy needs the audited condition.")

    audit = {"source": "AUDIT", "auditor": auditor, "quantity": audit_quantity, "condition": audit_condition}
    verdict = crosscheck.compare_records(declaration, audit, flagged_against=first_signal, dimension=d.type.value)

    if verdict == crosscheck.CORROBORATED:
        details["audit"] = {**audit, "verdict": verdict, "at": now.isoformat(), "evidence_backed": False, "path": "LEGACY_MANUAL_ENTRY"}
        _save(d, details)
        d.status = S.CORROBORATED
        append_event(db, d.load_id, "DISCREPANCY_CORROBORATED",
                     {"discrepancy_id": d.id, "type": d.type.value, "audit": audit, "verdict": verdict, "status": d.status.value,
                      "evidence_backed": False, "path": "LEGACY_MANUAL_ENTRY"},
                     actor=actor, now=now)
        return d, True, "Independent audit agrees with the facility record. Discrepancy is now corroborated."

    if verdict == crosscheck.MATCH:
        msg = ("Audit agrees with the worker's declaration, so the facility's mismatch is NOT corroborated. "
               "Status stays EVIDENCE_PENDING and nothing is attributed to anyone.")
    else:
        msg = ("Audit also differs from the declaration, but does not agree with the facility record. "
               "Not corroborated; status stays EVIDENCE_PENDING and nothing is attributed to anyone.")
    append_event(db, d.load_id, "CORROBORATION_REJECTED",
                 {"discrepancy_id": d.id, "audit": audit, "verdict": verdict, "status": d.status.value}, actor=actor, now=now)
    return d, False, msg


def investigate(db, discrepancy_id: int, actor: str, note: Optional[str] = None, now: Optional[datetime] = None):
    d = _load(db, discrepancy_id)
    _require(d, "investigate")
    details = _details(d)
    details["investigation_note"] = note
    _save(d, details)
    d.status = S.INVESTIGATING
    append_event(db, d.load_id, "DISCREPANCY_INVESTIGATING", {"discrepancy_id": d.id, "note": note, "status": d.status.value}, actor=actor, now=now)
    return d


def resolve(db, discrepancy_id: int, actor: str, finding: str, attributed_to: str, now: Optional[datetime] = None):
    """Attribution can only be recorded here - and this state is only reachable via CORROBORATED."""
    d = _load(db, discrepancy_id)
    _require(d, "resolve")
    now = now or utcnow()
    details = _details(d)
    details["resolution"] = {"finding": finding, "attributed_to": attributed_to, "by": actor, "at": now.isoformat()}
    _save(d, details)
    d.status = S.RESOLVED
    d.resolved_at = now
    append_event(db, d.load_id, "DISCREPANCY_RESOLVED",
                 {"discrepancy_id": d.id, "finding": finding, "attributed_to": attributed_to, "status": d.status.value}, actor=actor, now=now)
    return d


def close(db, discrepancy_id: int, actor: str, note: Optional[str] = None, now: Optional[datetime] = None):
    d = _load(db, discrepancy_id)
    _require(d, "close")
    details = _details(d)
    details["closing_note"] = note
    _save(d, details)
    d.status = S.CLOSED
    append_event(db, d.load_id, "DISCREPANCY_CLOSED", {"discrepancy_id": d.id, "note": note, "status": d.status.value}, actor=actor, now=now)
    db.flush()
    sync_load_status_after_close(db, d.load_id)
    return d


# ------------------------------------------------------------------ Phase 2: audit-backed corroboration
def corroborate_with_audit(db, discrepancy_id: int, actor_user: User, audit_id: int, now: Optional[datetime] = None):
    """Second signal = a COMPLETED audit by an INDEPENDENT auditor. Independence is decided here, on the server.

    Returns (discrepancy, outcome, reason_code, message). The state machine is unchanged: CORROBORATED is reached only
    on ACCEPTED; every rejection leaves the discrepancy in EVIDENCE_PENDING, is recorded (row + hash-chained
    CORROBORATION_REJECTED event) and attributes nothing to anyone. The Cross-Check Engine still makes the comparison.
    """
    from . import settings
    d = _load(db, discrepancy_id)
    _require(d, "corroborate")
    audit = db.get(Audit, audit_id)
    if audit is None or audit.load_id != d.load_id:
        raise ServiceError(404, "AUDIT_NOT_FOUND", f"Audit #{audit_id} does not exist for {d.load_id}.")
    if getattr(audit, "target_type", None) == AuditTargetType.COLLECTION_EVENT:
        raise ServiceError(409, "INVALID_AUDIT_TARGET", f"Audit #{audit.id} is a point-of-collection audit; digital load discrepancies require a Digital Load Verification audit.")
    if audit.status != AuditStatus.COMPLETED:
        raise ServiceError(409, "AUDIT_NOT_COMPLETED", f"Audit #{audit.id} is {audit.status.value}; only a COMPLETED audit can be submitted.")
    if db.scalars(select(AuditCorroboration.id).where(AuditCorroboration.audit_id == audit.id, AuditCorroboration.discrepancy_id == d.id)).first():
        raise ServiceError(409, "AUDIT_ALREADY_EVALUATED", f"Audit #{audit.id} was already evaluated for discrepancy #{d.id}. Use a different audit.")

    now = now or utcnow()
    load = get_load_or_404(db, d.load_id)
    parties = get_parties(db, load)
    auditor = db.get(User, audit.auditor_id)
    result = audit.result_json or {}
    details = _details(d)

    def reject(outcome: CorroborationOutcome, code: str, msg: str, extra: Optional[dict] = None):
        detail = {"audit_id": audit.id, "auditor": f"{auditor.role.value.lower()}:{auditor.id}" if auditor else None, **(extra or {})}
        ev = append_event(db, d.load_id, "CORROBORATION_REJECTED",
                          {"discrepancy_id": d.id, "audit_id": audit.id, "outcome": outcome.value, "reason_code": code, "status": d.status.value,
                           "attribution": "NONE - rejection is not a finding about any person", **detail}, actor=f"{actor_user.role.value.lower()}:{actor_user.id}", now=now)
        db.add(AuditCorroboration(audit_id=audit.id, discrepancy_id=d.id, outcome=outcome, reason_code=code, detail_json=detail,
                                  evaluated_by_user_id=actor_user.id, evaluated_at=now, event_id=ev.id))
        return d, outcome, code, msg

    # 1. independence of the auditor (server-side, from the data - not from the role name alone)
    viol = auditor_violations(auditor, parties) if auditor else [{"code": "NO_AUDITOR", "message": "Audit has no auditor."}]
    if viol:
        return reject(CorroborationOutcome.REJECTED_NOT_INDEPENDENT, "AUDITOR_NOT_INDEPENDENT",
                      "Rejected: the auditor is not independent of the parties. " + " ".join(v["message"] for v in viol), {"violations": viol})

    # 2. the audit must carry independent FILE evidence (when file evidence is required)
    files = db.scalars(select(Evidence).where(Evidence.audit_id == audit.id, Evidence.kind == EvidenceKind.FILE_EVIDENCE)).all()
    good = [e for e in files if evidence_independence(e, db.get(User, e.uploader_id) if e.uploader_id else None, parties)["independent"]]
    if settings.require_file_evidence() and not good:
        return reject(CorroborationOutcome.REJECTED_NO_EVIDENCE, "NO_INDEPENDENT_FILE_EVIDENCE",
                      "Rejected: the audit has no independent file evidence (missing, or only duplicated/non-independent files).")

    # 3. the Cross-Check Engine compares the audit with the declaration and with the first signal (unchanged engine)
    audit_record = {"source": "AUDIT", "quantity": result.get("quantity"), "condition": result.get("condition")}
    verdict = crosscheck.compare_records(build_declaration(db, load), audit_record, flagged_against=details["receiving"], dimension=d.type.value)
    extra = {"engine_verdict": verdict, "audit_overall": result.get("overall")}
    if verdict == crosscheck.MATCH:
        return reject(CorroborationOutcome.REJECTED_SUPPORTS_WORKER, "AUDIT_SUPPORTS_WORKER",
                      "Rejected: the independent audit agrees with the worker's declaration, so the facility's mismatch is not corroborated. "
                      "The discrepancy stays EVIDENCE_PENDING and nothing is attributed to anyone.", extra)
    if verdict != crosscheck.CORROBORATED:
        return reject(CorroborationOutcome.REJECTED_INCONCLUSIVE, "AUDIT_INCONCLUSIVE",
                      "Rejected as inconclusive: the audit differs from the declaration but does not agree with the facility record either. "
                      "The discrepancy stays EVIDENCE_PENDING and nothing is attributed to anyone.", extra)

    # ACCEPTED
    audit_dict = {"source": "AUDIT", "auditor": f"{auditor.role.value.lower()}:{auditor.id}", "quantity": result.get("quantity"),
                  "condition": result.get("condition"), "verdict": verdict, "at": now.isoformat(), "audit_id": audit.id,
                  "evidence_backed": bool(good), "path": "INDEPENDENT_AUDIT", "evidence": [{"id": e.public_id, "sha256": e.sha256} for e in good]}
    details["audit"] = audit_dict
    _save(d, details)
    d.status = S.CORROBORATED
    ev = append_event(db, d.load_id, "DISCREPANCY_CORROBORATED",
                      {"discrepancy_id": d.id, "type": d.type.value, "audit_id": audit.id, "audit": {k: audit_dict[k] for k in ("auditor", "quantity", "condition")},
                       "verdict": verdict, "status": d.status.value, "evidence_backed": bool(good), "path": "INDEPENDENT_AUDIT",
                       "evidence": audit_dict["evidence"], "attribution": "NONE - corroboration confirms the mismatch, it does not assign responsibility"},
                      actor=f"{actor_user.role.value.lower()}:{actor_user.id}", now=now)
    db.add(AuditCorroboration(audit_id=audit.id, discrepancy_id=d.id, outcome=CorroborationOutcome.ACCEPTED, reason_code="AUDIT_SUPPORTS_FACILITY",
                              detail_json={"audit_id": audit.id, **extra}, evaluated_by_user_id=actor_user.id, evaluated_at=now, event_id=ev.id))
    return d, CorroborationOutcome.ACCEPTED, "AUDIT_SUPPORTS_FACILITY", "Independent audit agrees with the facility record. Discrepancy is now corroborated."
