"""Phase 3, Step 3(A) - Handoff lifecycle. A Handoff is one physical transfer of (part of) a load's
processed material from a source facility to a destination facility, always tied to the COMPLETED
ProcessingRecord it draws its quantity from. (The Disposal Exception reroute path - a Handoff created
without a preceding ProcessingRecord - is explicitly out of scope for this step; processing_record_id is
therefore REQUIRED here, not optional as the column itself allows.)

    create_handoff     (FACILITY | MUNICIPAL_ADMIN, processing record COMPLETED)  -> PENDING
    complete_handoff     PENDING | IN_TRANSIT -> COMPLETED
    cancel_handoff        PENDING | IN_TRANSIT -> CANCELLED (with a recorded reason)

Every transition appends to the load's EXISTING SHA-256 hash chain via hashchain.append_event - no new
hashing mechanism - and stores the resulting event's id on the row's `event_id`, exactly like processing.py
and Phase 2's Audit/Evidence.

DESIGN DECISION (flagged): unlike processing.py (Step 2 - "start" IS creation, status goes straight to
IN_PROGRESS), here creation produces a PENDING handoff. This follows Step 3's brief, which gives
"PENDING -> COMPLETED" as the example transition for this entity. IN_TRANSIT exists in the schema but no
function in this step moves a handoff into it; `complete_handoff` accepts IN_TRANSIT as a starting state
too (an already-defined enum transition, not an invented one), so a later step can add a `mark_in_transit`
function with no change needed here.

DESIGN DECISION (flagged): a Handoff's `waste_stream` must be RECOVERED or RESIDUAL - the two output
quantities a ProcessingRecord actually tracks (there is no other way, with the Step 1 schema as approved,
to know how much of a given stream a processing record still has to give). Its available balance is that
processing record's matching quantity field minus whatever has already been handed off (non-cancelled)
against that same stream from that same processing record.

STEP 4 ADDITION (minimal, explained in full at the call site below and in disposal_exception.py): the
balance calculation in `_already_handed_off_kg` excludes a handoff once it has been superseded by an
authorized/resolved DisposalException. This is the one integration change Step 4 required in this file -
no transitions, contracts, or signatures changed; only which rows count toward the existing ledger.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import ServiceError
from .evidence import actor_of
from .hashchain import append_event
from .models import Facility, Handoff, HandoffStatus, ProcessingRecord, ProcessingStatus, Role, User, WasteStream, utcnow
from .services import get_load_or_404

MIN_CANCEL_REASON = 10

# Same reuse decision as processing.py: no new role, no per-facility independence check requested for this step.
HANDOFF_ROLES = (Role.FACILITY,)

# The only two WasteStream values a ProcessingRecord actually tracks output quantities for.
SOURCEABLE_STREAMS = (WasteStream.RECOVERED, WasteStream.RESIDUAL)


def _require_handoff_role(user: User) -> None:
    if user.role not in HANDOFF_ROLES:
        raise ServiceError(403, "FORBIDDEN", f"Requires role: {', '.join(r.value for r in HANDOFF_ROLES)}.")


def _get_processing_record(db: Session, processing_record_id: int) -> ProcessingRecord:
    p = db.get(ProcessingRecord, processing_record_id)
    if p is None:
        raise ServiceError(404, "PROCESSING_RECORD_NOT_FOUND", f"No processing record #{processing_record_id}.")
    return p


def _stream_output_kg(pr: ProcessingRecord, waste_stream: WasteStream) -> int:
    return pr.recovered_quantity_kg if waste_stream == WasteStream.RECOVERED else pr.residual_quantity_kg


def _already_handed_off_kg(db: Session, processing_record_id: int, waste_stream: WasteStream) -> int:
    # STEP 4 INTEGRATION FIX (explained in disposal_exception.py's module docstring): a handoff that has
    # been SUPERSEDED by an authorized/resolved DisposalException reroute (i.e. it IS that exception's
    # source_handoff_id) no longer counts against this ledger. Its quantity didn't disappear - it was
    # reassigned to the resulting handoff, which counts on its own. Without this exclusion, the original
    # (still COMPLETED, non-cancelled) handoff would keep "spending" the processing record's balance
    # forever, making it mathematically impossible to authorize a reroute for material that already left
    # via a handoff - the resulting handoff would always be rejected as exceeding the (already zero)
    # available balance, even though no new waste quantity is actually being requested.
    # Local import avoids a circular import (disposal_exception.py imports this module, not the reverse).
    from .models import DisposalException, DisposalExceptionStatus
    superseded = select(DisposalException.source_handoff_id).where(
        DisposalException.source_handoff_id.isnot(None),
        DisposalException.status.in_([DisposalExceptionStatus.AUTHORIZED, DisposalExceptionStatus.RESOLVED]),
    )
    total = db.scalar(select(func.coalesce(func.sum(Handoff.quantity_kg), 0)).where(
        Handoff.processing_record_id == processing_record_id, Handoff.waste_stream == waste_stream,
        Handoff.status != HandoffStatus.CANCELLED,
        Handoff.id.notin_(superseded),
    ))
    return int(total or 0)


def available_to_hand_off(db: Session, processing_record_id: int, waste_stream: WasteStream) -> int:
    """How much of `waste_stream` is still un-handed-off from this processing record. Public: reused by tests
    and, later, by a router/serializer."""
    pr = _get_processing_record(db, processing_record_id)
    return _stream_output_kg(pr, waste_stream) - _already_handed_off_kg(db, pr.id, waste_stream)


def _lock(db: Session, handoff_id: int) -> Handoff:
    h = db.execute(select(Handoff).where(Handoff.id == handoff_id).with_for_update()).scalar_one_or_none()
    if h is None:
        raise ServiceError(404, "HANDOFF_NOT_FOUND", f"No handoff #{handoff_id}.")
    return h


# ---------------------------------------------------------------- creation
def create_handoff(
    db: Session,
    user: User,
    load_id: str,
    *,
    processing_record_id: int,
    source_facility_id: int,
    destination_facility_id: int,
    waste_stream: WasteStream,
    quantity_kg: int,
    notes: str = "",
    now: Optional[datetime] = None,
) -> Handoff:
    """Create a Handoff (status PENDING) transferring `quantity_kg` of `waste_stream` (RECOVERED or RESIDUAL)
    out of a COMPLETED ProcessingRecord belonging to `load_id`.

    Preconditions (all server-side, in this order):
      1. Authorization: `user` must be FACILITY or MUNICIPAL_ADMIN.
      2. The Digital Load must exist.
      3. The processing record must exist, belong to THIS load ("the handoff must be associated with the
         correct Digital Load"), and be COMPLETED - an in-progress or cancelled processing record has no
         material ready to hand off ("the related processing workflow is valid").
      4. `waste_stream` must be RECOVERED or RESIDUAL.
      5. Source and destination facilities must both exist.
      6. Source and destination cannot be the same facility.
      7. `quantity_kg` must be positive.
      8. `quantity_kg` must not exceed what's still available for that stream from that processing record.
      9. No other OPEN (PENDING/IN_TRANSIT) handoff may already exist for this load - an already-open or
         already-closed handoff is never silently duplicated (schema-enforced partial unique index for the
         open case, checked here too for a clean error message).
    """
    _require_handoff_role(user)
    load = get_load_or_404(db, load_id, lock=True)
    pr = _get_processing_record(db, processing_record_id)
    if pr.digital_load_id != load.id:
        raise ServiceError(409, "PROCESSING_RECORD_LOAD_MISMATCH", f"Processing record #{pr.id} belongs to {pr.digital_load_id}, not {load.id}.")
    if pr.status != ProcessingStatus.COMPLETED:
        raise ServiceError(409, "PROCESSING_NOT_COMPLETED",
                           f"Processing record #{pr.id} is {pr.status.value}; only a COMPLETED processing record has material ready to hand off.")
    if waste_stream not in SOURCEABLE_STREAMS:
        raise ServiceError(422, "INVALID_WASTE_STREAM", "A handoff must move the RECOVERED or RESIDUAL output of a processing record.")
    if db.get(Facility, source_facility_id) is None:
        raise ServiceError(404, "FACILITY_NOT_FOUND", f"No facility #{source_facility_id}.")
    if db.get(Facility, destination_facility_id) is None:
        raise ServiceError(404, "FACILITY_NOT_FOUND", f"No facility #{destination_facility_id}.")
    if source_facility_id == destination_facility_id:
        raise ServiceError(422, "SAME_FACILITY", "Source and destination facilities cannot be the same.")
    if quantity_kg <= 0:
        raise ServiceError(422, "INVALID_QUANTITY", "quantity_kg must be greater than 0.")
    available = _stream_output_kg(pr, waste_stream) - _already_handed_off_kg(db, pr.id, waste_stream)
    if quantity_kg > available:
        raise ServiceError(
            422, "QUANTITY_EXCEEDS_AVAILABLE",
            f"quantity_kg ({quantity_kg}) exceeds the {available} kg of {waste_stream.value} still available from processing record #{pr.id}.",
        )

    if db.scalars(select(Handoff.id).where(
        Handoff.digital_load_id == load.id, Handoff.status.in_([HandoffStatus.PENDING, HandoffStatus.IN_TRANSIT]),
    )).first():
        raise ServiceError(409, "HANDOFF_ALREADY_OPEN", f"{load.id} already has an open handoff.")

    now = now or utcnow()
    h = Handoff(
        digital_load_id=load.id, processing_record_id=pr.id, source_facility_id=source_facility_id,
        destination_facility_id=destination_facility_id, quantity_kg=quantity_kg, waste_stream=waste_stream,
        status=HandoffStatus.PENDING, timestamp=now, recorded_by_user_id=user.id, notes=notes.strip() if notes else "", created_at=now,
    )
    db.add(h)
    try:
        db.flush()
    except IntegrityError as e:   # the partial unique index caught a concurrent creation
        raise ServiceError(409, "HANDOFF_ALREADY_OPEN", f"{load.id} already has an open handoff.") from e

    ev = append_event(
        db, load.id, "HANDOFF_CREATED",
        {"handoff_id": h.id, "processing_record_id": pr.id, "source_facility_id": source_facility_id,
         "destination_facility_id": destination_facility_id, "waste_stream": waste_stream.value, "quantity_kg": quantity_kg},
        actor=actor_of(user), now=now,
    )
    h.event_id = ev.id
    db.flush()
    return h


# ---------------------------------------------------------------- lifecycle
def complete_handoff(db: Session, user: User, handoff_id: int, now: Optional[datetime] = None) -> Handoff:
    """PENDING | IN_TRANSIT -> COMPLETED. Any other current status is an invalid transition (rejected, 409)."""
    _require_handoff_role(user)
    h = _lock(db, handoff_id)
    if h.status not in (HandoffStatus.PENDING, HandoffStatus.IN_TRANSIT):
        raise ServiceError(409, "INVALID_HANDOFF_STATE", f"Handoff #{h.id} is {h.status.value}; only a PENDING or IN_TRANSIT handoff can be completed.")
    now = now or utcnow()
    h.status = HandoffStatus.COMPLETED
    ev = append_event(db, h.digital_load_id, "HANDOFF_COMPLETED", {"handoff_id": h.id, "quantity_kg": h.quantity_kg}, actor=actor_of(user), now=now)
    h.event_id = ev.id
    db.flush()
    return h


def cancel_handoff(db: Session, user: User, handoff_id: int, reason: str, now: Optional[datetime] = None) -> Handoff:
    """PENDING | IN_TRANSIT -> CANCELLED. COMPLETED/CANCELLED cannot be cancelled again (invalid transition, 409).

    No dedicated cancel_reason column (migration 0004 is not being modified this step): the reason is
    appended to the existing `notes` field, same pattern as processing.cancel_processing.
    """
    _require_handoff_role(user)
    h = _lock(db, handoff_id)
    if h.status not in (HandoffStatus.PENDING, HandoffStatus.IN_TRANSIT):
        raise ServiceError(409, "INVALID_HANDOFF_STATE", f"Handoff #{h.id} is {h.status.value} and cannot be cancelled.")
    if len(reason.strip()) < MIN_CANCEL_REASON:
        raise ServiceError(422, "REASON_REQUIRED", f"A cancellation needs a recorded reason (min {MIN_CANCEL_REASON} characters).")
    now = now or utcnow()
    reason = reason.strip()
    h.status = HandoffStatus.CANCELLED
    h.notes = f"{h.notes}\nCancelled: {reason}" if h.notes else f"Cancelled: {reason}"
    ev = append_event(db, h.digital_load_id, "HANDOFF_CANCELLED", {"handoff_id": h.id, "reason": reason}, actor=actor_of(user), now=now)
    h.event_id = ev.id
    db.flush()
    return h


# ---------------------------------------------------------------- serialization
def ser_handoff(db: Session, h: Handoff) -> dict:
    source = db.get(Facility, h.source_facility_id)
    destination = db.get(Facility, h.destination_facility_id)
    recorded_by = db.get(User, h.recorded_by_user_id) if h.recorded_by_user_id else None
    return {
        "id": h.id, "digital_load_id": h.digital_load_id, "processing_record_id": h.processing_record_id,
        "source_facility_id": h.source_facility_id, "source_facility": source.name if source else None,
        "destination_facility_id": h.destination_facility_id, "destination_facility": destination.name if destination else None,
        "quantity_kg": h.quantity_kg, "waste_stream": h.waste_stream.value, "status": h.status.value,
        "timestamp": h.timestamp.isoformat() if h.timestamp else None, "recorded_by": recorded_by.name if recorded_by else None,
        "notes": h.notes, "created_at": h.created_at.isoformat(), "event_id": h.event_id,
    }
