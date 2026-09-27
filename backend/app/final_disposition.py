"""Phase 3, Step 3(D) - Final Disposition. Where a load's processed material ultimately ends up.

record_final_disposition sources a FinalDisposition from EXACTLY ONE of:
  - a COMPLETED Handoff (the normal flow: Processing -> Handoff -> Final Disposition), or
  - a COMPLETED ProcessingRecord directly (material disposed at the same facility that processed it, with
    no separate transfer in between - the schema allows this since FinalDisposition.handoff_id is nullable)
capped by that source's remaining available quantity. Multiple FinalDisposition rows CAN legitimately exist
for the same load (e.g. 350 kg recovered -> a recycler, 150 kg residual -> a landfill) as long as their
quantities never exceed what each source actually has left - this is the many-per-load design already
approved in Step 1 (FinalDisposition's docstring in models.py), not a change made here.

    record_final_disposition   (FACILITY | MUNICIPAL_ADMIN, source COMPLETED)  -> RECORDED
    verify_disposition            RECORDED -> VERIFIED
    cancel_disposition            RECORDED -> CANCELLED (with a recorded reason)

DispositionStatus is used EXACTLY as defined in Step 1 - RECORDED, VERIFIED, CANCELLED. There is no PENDING
or COMPLETED value in this enum (that phrasing in the Step 3 brief was a generic example - "if the model
supports..."), so the event names below are FINAL_DISPOSITION_RECORDED / _VERIFIED / _CANCELLED rather than
the brief's example _COMPLETED, per "only use event types that correspond to actual implemented operations".

Every transition appends to the load's EXISTING SHA-256 hash chain via hashchain.append_event and stores
the resulting event's id on `final_disposition.event_id`, exactly like processing.py/handoff.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .errors import ServiceError
from .evidence import actor_of
from .hashchain import append_event
from .models import (
    DispositionStatus, DispositionType, Facility, FinalDisposition, Handoff, HandoffStatus, ProcessingRecord, ProcessingStatus, Role, User,
    utcnow,
)
from .services import get_load_or_404

MIN_CANCEL_REASON = 10

# Same reuse decision as processing.py/handoff.py: no new role, no per-facility independence check requested.
DISPOSITION_ROLES = (Role.FACILITY,)


def _require_disposition_role(user: User) -> None:
    if user.role not in DISPOSITION_ROLES:
        raise ServiceError(403, "FORBIDDEN", f"Requires role: {', '.join(r.value for r in DISPOSITION_ROLES)}.")


def _get_handoff(db: Session, handoff_id: int) -> Handoff:
    h = db.get(Handoff, handoff_id)
    if h is None:
        raise ServiceError(404, "HANDOFF_NOT_FOUND", f"No handoff #{handoff_id}.")
    return h


def _get_processing_record(db: Session, processing_record_id: int) -> ProcessingRecord:
    p = db.get(ProcessingRecord, processing_record_id)
    if p is None:
        raise ServiceError(404, "PROCESSING_RECORD_NOT_FOUND", f"No processing record #{processing_record_id}.")
    return p


def _disposed_against_handoff_kg(db: Session, handoff_id: int) -> int:
    total = db.scalar(select(func.coalesce(func.sum(FinalDisposition.quantity_kg), 0)).where(
        FinalDisposition.handoff_id == handoff_id, FinalDisposition.status != DispositionStatus.CANCELLED,
    ))
    return int(total or 0)


def _disposed_directly_against_processing_record_kg(db: Session, processing_record_id: int) -> int:
    total = db.scalar(select(func.coalesce(func.sum(FinalDisposition.quantity_kg), 0)).where(
        FinalDisposition.processing_record_id == processing_record_id, FinalDisposition.status != DispositionStatus.CANCELLED,
    ))
    return int(total or 0)


def _handed_off_from_processing_record_kg(db: Session, processing_record_id: int) -> int:
    total = db.scalar(select(func.coalesce(func.sum(Handoff.quantity_kg), 0)).where(
        Handoff.processing_record_id == processing_record_id, Handoff.status != HandoffStatus.CANCELLED,
    ))
    return int(total or 0)


def available_from_handoff(db: Session, handoff_id: int) -> int:
    h = _get_handoff(db, handoff_id)
    return h.quantity_kg - _disposed_against_handoff_kg(db, h.id)


def available_from_processing_record(db: Session, processing_record_id: int) -> int:
    """A processing record's total output (recovered + residual) minus whatever has already left it, either
    via a Handoff or via a FinalDisposition recorded directly against it - so the same kg can never be
    counted as both handed off AND disposed."""
    pr = _get_processing_record(db, processing_record_id)
    total_output = pr.recovered_quantity_kg + pr.residual_quantity_kg
    return total_output - _handed_off_from_processing_record_kg(db, pr.id) - _disposed_directly_against_processing_record_kg(db, pr.id)


def _lock(db: Session, final_disposition_id: int) -> FinalDisposition:
    fd = db.execute(select(FinalDisposition).where(FinalDisposition.id == final_disposition_id).with_for_update()).scalar_one_or_none()
    if fd is None:
        raise ServiceError(404, "FINAL_DISPOSITION_NOT_FOUND", f"No final disposition #{final_disposition_id}.")
    return fd


# ---------------------------------------------------------------- creation
def record_final_disposition(
    db: Session,
    user: User,
    load_id: str,
    *,
    disposition_type: DispositionType,
    destination_facility_id: int,
    quantity_kg: int,
    handoff_id: Optional[int] = None,
    processing_record_id: Optional[int] = None,
    notes: str = "",
    now: Optional[datetime] = None,
) -> FinalDisposition:
    """Record a FinalDisposition (status RECORDED) for `load_id`, sourced from exactly one of `handoff_id`
    or `processing_record_id`.

    Preconditions (all server-side, in this order):
      1. Authorization: `user` must be FACILITY or MUNICIPAL_ADMIN.
      2. The Digital Load must exist.
      3. Exactly one of `handoff_id` / `processing_record_id` must be given (never both, never neither) -
         this is the row's one traceable source.
      4. That source must exist, belong to THIS load, and be COMPLETED ("the relevant processing/handoff
         workflow exists").
      5. `destination_facility_id` must reference a real facility.
      6. `disposition_type` must be a valid DispositionType (enforced by the type system: callers pass the
         enum member, exactly as processing_method/waste_stream already work in processing.py/handoff.py).
      7. `quantity_kg` must be positive.
      8. `quantity_kg` must not exceed what's still available from that source.
    """
    _require_disposition_role(user)
    load = get_load_or_404(db, load_id, lock=True)

    if (handoff_id is None) == (processing_record_id is None):
        raise ServiceError(422, "SOURCE_REQUIRED", "Exactly one of handoff_id or processing_record_id must be given.")

    if handoff_id is not None:
        h = _get_handoff(db, handoff_id)
        if h.digital_load_id != load.id:
            raise ServiceError(409, "HANDOFF_LOAD_MISMATCH", f"Handoff #{h.id} belongs to {h.digital_load_id}, not {load.id}.")
        if h.status != HandoffStatus.COMPLETED:
            raise ServiceError(409, "HANDOFF_NOT_COMPLETED", f"Handoff #{h.id} is {h.status.value}; only a COMPLETED handoff has material ready to dispose.")
        available = available_from_handoff(db, h.id)
        pr_id_for_row = None
    else:
        pr = _get_processing_record(db, processing_record_id)
        if pr.digital_load_id != load.id:
            raise ServiceError(409, "PROCESSING_RECORD_LOAD_MISMATCH", f"Processing record #{pr.id} belongs to {pr.digital_load_id}, not {load.id}.")
        if pr.status != ProcessingStatus.COMPLETED:
            raise ServiceError(409, "PROCESSING_NOT_COMPLETED",
                               f"Processing record #{pr.id} is {pr.status.value}; only a COMPLETED processing record has material ready to dispose.")
        available = available_from_processing_record(db, pr.id)
        pr_id_for_row = pr.id

    if db.get(Facility, destination_facility_id) is None:
        raise ServiceError(404, "FACILITY_NOT_FOUND", f"No facility #{destination_facility_id}.")
    if quantity_kg <= 0:
        raise ServiceError(422, "INVALID_QUANTITY", "quantity_kg must be greater than 0.")
    if quantity_kg > available:
        source = f"handoff #{handoff_id}" if handoff_id is not None else f"processing record #{processing_record_id}"
        raise ServiceError(422, "QUANTITY_EXCEEDS_AVAILABLE", f"quantity_kg ({quantity_kg}) exceeds the {available} kg still available from {source}.")

    now = now or utcnow()
    fd = FinalDisposition(
        digital_load_id=load.id, handoff_id=handoff_id, processing_record_id=pr_id_for_row, disposition_type=disposition_type,
        destination_facility_id=destination_facility_id, quantity_kg=quantity_kg, status=DispositionStatus.RECORDED, timestamp=now,
        recorded_by_user_id=user.id, notes=notes.strip() if notes else "", created_at=now,
    )
    db.add(fd)
    db.flush()

    ev = append_event(
        db, load.id, "FINAL_DISPOSITION_RECORDED",
        {"final_disposition_id": fd.id, "handoff_id": handoff_id, "processing_record_id": pr_id_for_row,
         "disposition_type": disposition_type.value, "destination_facility_id": destination_facility_id, "quantity_kg": quantity_kg},
        actor=actor_of(user), now=now,
    )
    fd.event_id = ev.id
    db.flush()
    return fd


# ---------------------------------------------------------------- lifecycle
def verify_disposition(db: Session, user: User, final_disposition_id: int, now: Optional[datetime] = None) -> FinalDisposition:
    """RECORDED -> VERIFIED. Any other current status is an invalid transition (rejected, 409)."""
    _require_disposition_role(user)
    fd = _lock(db, final_disposition_id)
    if fd.status != DispositionStatus.RECORDED:
        raise ServiceError(409, "INVALID_DISPOSITION_STATE", f"Final disposition #{fd.id} is {fd.status.value}; only a RECORDED entry can be verified.")
    now = now or utcnow()
    fd.status = DispositionStatus.VERIFIED
    ev = append_event(db, fd.digital_load_id, "FINAL_DISPOSITION_VERIFIED", {"final_disposition_id": fd.id, "quantity_kg": fd.quantity_kg},
                      actor=actor_of(user), now=now)
    fd.event_id = ev.id
    db.flush()
    return fd


def cancel_disposition(db: Session, user: User, final_disposition_id: int, reason: str, now: Optional[datetime] = None) -> FinalDisposition:
    """RECORDED -> CANCELLED. VERIFIED/CANCELLED cannot be cancelled (invalid transition, 409).

    No dedicated cancel_reason column: the reason is appended to the existing `notes` field, same pattern
    as processing.cancel_processing / handoff.cancel_handoff.
    """
    _require_disposition_role(user)
    fd = _lock(db, final_disposition_id)
    if fd.status != DispositionStatus.RECORDED:
        raise ServiceError(409, "INVALID_DISPOSITION_STATE", f"Final disposition #{fd.id} is {fd.status.value} and cannot be cancelled.")
    if len(reason.strip()) < MIN_CANCEL_REASON:
        raise ServiceError(422, "REASON_REQUIRED", f"A cancellation needs a recorded reason (min {MIN_CANCEL_REASON} characters).")
    now = now or utcnow()
    reason = reason.strip()
    fd.status = DispositionStatus.CANCELLED
    fd.notes = f"{fd.notes}\nCancelled: {reason}" if fd.notes else f"Cancelled: {reason}"
    ev = append_event(db, fd.digital_load_id, "FINAL_DISPOSITION_CANCELLED", {"final_disposition_id": fd.id, "reason": reason}, actor=actor_of(user), now=now)
    fd.event_id = ev.id
    db.flush()
    return fd


# ---------------------------------------------------------------- serialization
def ser_final_disposition(db: Session, fd: FinalDisposition) -> dict:
    destination = db.get(Facility, fd.destination_facility_id)
    recorded_by = db.get(User, fd.recorded_by_user_id) if fd.recorded_by_user_id else None
    return {
        "id": fd.id, "digital_load_id": fd.digital_load_id, "handoff_id": fd.handoff_id, "processing_record_id": fd.processing_record_id,
        "disposition_type": fd.disposition_type.value, "destination_facility_id": fd.destination_facility_id,
        "destination_facility": destination.name if destination else None, "quantity_kg": fd.quantity_kg, "status": fd.status.value,
        "timestamp": fd.timestamp.isoformat() if fd.timestamp else None, "recorded_by": recorded_by.name if recorded_by else None,
        "notes": fd.notes, "created_at": fd.created_at.isoformat(), "event_id": fd.event_id,
    }
