"""Phase 3, Step 2 - Processing lifecycle. A facility processes a received load's material
(composting, recycling, MRF sorting, ...).

    start_processing   (FACILITY | MUNICIPAL_ADMIN, load VERIFIED or SETTLED)  -> creates the ProcessingRecord,
                       already IN_PROGRESS (there is no separate PENDING-then-start step here, unlike Audit -
                       "start processing" IS the creation action per the Phase 3 Step 2 brief)
    complete_processing  IN_PROGRESS -> COMPLETED
    cancel_processing    PENDING | IN_PROGRESS -> CANCELLED (with a recorded reason)

Every transition appends to the load's EXISTING SHA-256 hash chain via hashchain.append_event - no new
hashing/audit mechanism is created - and stores the resulting event's id on the row's `event_id`, exactly
like Evidence/Audit/AuditCorroboration in Phase 2.

Out of scope for this step (separate steps per the Phase 3 plan): handoffs, final dispositions, disposal
exceptions, API routes, frontend. This module is called directly (from tests, and later from a router).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import ServiceError
from .evidence import actor_of
from .hashchain import append_event
from .models import Facility, LoadStatus, ProcessingMethod, ProcessingRecord, ProcessingStatus, Role, User, WasteStream, utcnow
from .services import get_load_or_404

MIN_CANCEL_REASON = 10

# Only these roles may perform processing actions. No new role is introduced: this mirrors the existing
# `staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)` pattern used for receiving (loads.py) and the
# Audit Center (routers/audits.py). CITIZEN and WORKER are never authorized here.
PROCESSING_ROLES = (Role.FACILITY,)


def _require_processing_role(user: User) -> None:
    """Router-independent authorization check. This step adds no new routes, so the check lives here (the
    same place independence is checked in audits.py) rather than only at a FastAPI dependency."""
    if user.role not in PROCESSING_ROLES:
        raise ServiceError(403, "FORBIDDEN", f"Requires role: {', '.join(r.value for r in PROCESSING_ROLES)}.")


def _validate_quantities(processed_quantity_kg: int, recovered_quantity_kg: int, residual_quantity_kg: int) -> None:
    """Mirrors the DB CHECK constraints exactly, so a bad request fails with a clear 422 before it ever reaches
    the database - and values are never clamped or adjusted, only accepted as-is or rejected."""
    if processed_quantity_kg <= 0:
        raise ServiceError(422, "INVALID_QUANTITY", "processed_quantity_kg must be greater than 0.")
    if recovered_quantity_kg < 0 or residual_quantity_kg < 0:
        raise ServiceError(422, "INVALID_QUANTITY", "recovered_quantity_kg and residual_quantity_kg cannot be negative.")
    if recovered_quantity_kg + residual_quantity_kg > processed_quantity_kg:
        raise ServiceError(
            422, "INVALID_QUANTITY",
            f"recovered_quantity_kg + residual_quantity_kg ({recovered_quantity_kg + residual_quantity_kg}) "
            f"cannot exceed processed_quantity_kg ({processed_quantity_kg}).",
        )


def _lock(db: Session, processing_record_id: int) -> ProcessingRecord:
    p = db.execute(select(ProcessingRecord).where(ProcessingRecord.id == processing_record_id).with_for_update()).scalar_one_or_none()
    if p is None:
        raise ServiceError(404, "PROCESSING_RECORD_NOT_FOUND", f"No processing record #{processing_record_id}.")
    return p


# ---------------------------------------------------------------- creation / start
def start_processing(
    db: Session,
    user: User,
    load_id: str,
    *,
    facility_id: int,
    waste_stream: WasteStream,
    processing_method: ProcessingMethod,
    processed_quantity_kg: int,
    recovered_quantity_kg: int = 0,
    residual_quantity_kg: int = 0,
    notes: str = "",
    now: Optional[datetime] = None,
) -> ProcessingRecord:
    """Create a ProcessingRecord for `load_id` and start it (status IN_PROGRESS).

    Preconditions (all enforced server-side, in this order):
      1. Authorization: `user` must be FACILITY or MUNICIPAL_ADMIN.
      2. The load must exist and be VERIFIED or SETTLED - i.e. it has completed receiving/cross-check and has
         no unresolved discrepancy. A DISPUTED load (an open discrepancy) is explicitly rejected, as is a load
         that hasn't reached receiving yet (COLLECTING/DECLARED). This uses digital_loads.status exactly as it
         already works; nothing about that enum or its transitions is touched.
      3. `facility_id` must reference a real facility.
      4. Quantities must be valid (processed > 0; recovered, residual >= 0; recovered + residual <= processed).
      5. No other OPEN (PENDING/IN_PROGRESS) processing record may already exist for this load - checked here
         AND guarded by the partial unique index in the schema (uq_processing_records_one_open_per_load), so a
         concurrent duplicate is still caught even if two requests race past the check above.
    """
    _require_processing_role(user)
    load = get_load_or_404(db, load_id, lock=True)
    if load.status not in (LoadStatus.VERIFIED, LoadStatus.SETTLED):
        raise ServiceError(
            409, "LOAD_NOT_PROCESSABLE",
            f"{load.id} is {load.status.value}. Only a load that has completed receiving with no unresolved "
            f"discrepancy (VERIFIED or SETTLED) can start processing.",
        )
    if db.get(Facility, facility_id) is None:
        raise ServiceError(404, "FACILITY_NOT_FOUND", f"No facility #{facility_id}.")
    # STEP 5 ADDITION (facility scoping, the limitation flagged and deferred since Step 2/3): a FACILITY-role
    # user may only start processing at their OWN facility - they cannot record work as if it happened at a
    # facility they don't belong to. MUNICIPAL_ADMIN is unrestricted (facility-agnostic oversight, no
    # facility_id of their own). This is scoped to processing.start_processing ONLY: handoff/disposal_exception
    # source_facility_id represents where material physically IS, not who the acting user is, and forcing the
    # same restriction there would break the (already-approved, tested) disposal-exception reroute scenario,
    # where the acting user's own facility is not where the rejected material currently sits - see the Step 5
    # report for the full reasoning.
    if user.role == Role.FACILITY and user.facility_id != facility_id:
        raise ServiceError(403, "FACILITY_SCOPE_VIOLATION", f"You may only start processing at your own facility (#{user.facility_id}), not facility #{facility_id}.")
    _validate_quantities(processed_quantity_kg, recovered_quantity_kg, residual_quantity_kg)

    if db.scalars(select(ProcessingRecord.id).where(
        ProcessingRecord.digital_load_id == load.id,
        ProcessingRecord.status.in_([ProcessingStatus.PENDING, ProcessingStatus.IN_PROGRESS]),
    )).first():
        raise ServiceError(409, "PROCESSING_ALREADY_OPEN", f"{load.id} already has an open processing record.")

    now = now or utcnow()
    p = ProcessingRecord(
        digital_load_id=load.id, facility_id=facility_id, waste_stream=waste_stream, processing_method=processing_method,
        processed_quantity_kg=processed_quantity_kg, recovered_quantity_kg=recovered_quantity_kg,
        residual_quantity_kg=residual_quantity_kg, status=ProcessingStatus.IN_PROGRESS, started_at=now,
        recorded_by_user_id=user.id, notes=notes.strip() if notes else "", created_at=now,
    )
    db.add(p)
    try:
        db.flush()
    except IntegrityError as e:   # the partial unique index caught a concurrent start
        raise ServiceError(409, "PROCESSING_ALREADY_OPEN", f"{load.id} already has an open processing record.") from e

    ev = append_event(
        db, load.id, "PROCESSING_STARTED",
        {"processing_record_id": p.id, "facility_id": facility_id, "waste_stream": waste_stream.value,
         "processing_method": processing_method.value, "processed_quantity_kg": processed_quantity_kg,
         "recovered_quantity_kg": recovered_quantity_kg, "residual_quantity_kg": residual_quantity_kg},
        actor=actor_of(user), now=now,
    )
    p.event_id = ev.id
    db.flush()
    return p


# ---------------------------------------------------------------- lifecycle
def complete_processing(db: Session, user: User, processing_record_id: int, now: Optional[datetime] = None) -> ProcessingRecord:
    """IN_PROGRESS -> COMPLETED. Any other current status is an invalid transition (rejected, 409)."""
    _require_processing_role(user)
    p = _lock(db, processing_record_id)
    if p.status != ProcessingStatus.IN_PROGRESS:
        raise ServiceError(
            409, "INVALID_PROCESSING_STATE",
            f"Processing record #{p.id} is {p.status.value}; only an IN_PROGRESS record can be completed.",
        )
    now = now or utcnow()
    p.status, p.completed_at = ProcessingStatus.COMPLETED, now
    ev = append_event(
        db, p.digital_load_id, "PROCESSING_COMPLETED",
        {"processing_record_id": p.id, "recovered_quantity_kg": p.recovered_quantity_kg, "residual_quantity_kg": p.residual_quantity_kg},
        actor=actor_of(user), now=now,
    )
    p.event_id = ev.id
    db.flush()
    return p


def cancel_processing(db: Session, user: User, processing_record_id: int, reason: str, now: Optional[datetime] = None) -> ProcessingRecord:
    """PENDING | IN_PROGRESS -> CANCELLED. COMPLETED/CANCELLED cannot be cancelled again (invalid transition, 409).

    There is no dedicated cancel_reason column (migration 0004 is not being modified for this step): the reason
    is appended to the existing `notes` field, which already exists for exactly this kind of free-text record.
    """
    _require_processing_role(user)
    p = _lock(db, processing_record_id)
    if p.status not in (ProcessingStatus.PENDING, ProcessingStatus.IN_PROGRESS):
        raise ServiceError(409, "INVALID_PROCESSING_STATE", f"Processing record #{p.id} is {p.status.value} and cannot be cancelled.")
    if len(reason.strip()) < MIN_CANCEL_REASON:
        raise ServiceError(422, "REASON_REQUIRED", f"A cancellation needs a recorded reason (min {MIN_CANCEL_REASON} characters).")
    now = now or utcnow()
    reason = reason.strip()
    p.status = ProcessingStatus.CANCELLED
    p.notes = f"{p.notes}\nCancelled: {reason}" if p.notes else f"Cancelled: {reason}"
    ev = append_event(db, p.digital_load_id, "PROCESSING_CANCELLED", {"processing_record_id": p.id, "reason": reason}, actor=actor_of(user), now=now)
    p.event_id = ev.id
    db.flush()
    return p


# ---------------------------------------------------------------- serialization
def ser_processing(db: Session, p: ProcessingRecord) -> dict:
    facility = db.get(Facility, p.facility_id)
    recorded_by = db.get(User, p.recorded_by_user_id) if p.recorded_by_user_id else None
    return {
        "id": p.id, "digital_load_id": p.digital_load_id, "facility_id": p.facility_id, "facility": facility.name if facility else None,
        "waste_stream": p.waste_stream.value, "processing_method": p.processing_method.value,
        "processed_quantity_kg": p.processed_quantity_kg, "recovered_quantity_kg": p.recovered_quantity_kg, "residual_quantity_kg": p.residual_quantity_kg,
        "status": p.status.value, "started_at": p.started_at.isoformat() if p.started_at else None,
        "completed_at": p.completed_at.isoformat() if p.completed_at else None, "recorded_by": recorded_by.name if recorded_by else None,
        "notes": p.notes, "created_at": p.created_at.isoformat(), "event_id": p.event_id,
    }
