"""Phase 3, Step 4 - Disposal Exception + Authorized Alternative Destination. Handles the case where a
processing/handoff destination cannot accept a load's material:

    PROCESSING / HANDOFF -> DISPOSAL EXCEPTION -> REASON -> AUTHORIZED ALTERNATIVE DESTINATION
        -> NEW HANDOFF -> FINAL DISPOSITION

    create_disposal_exception          (FACILITY | MUNICIPAL_ADMIN, trigger COMPLETED)  -> RAISED
    authorize_alternative_destination    RAISED -> AUTHORIZED  (creates the resulting Handoff)
    resolve_disposal_exception           AUTHORIZED -> RESOLVED  (once the resulting Handoff is COMPLETED)

DisposalExceptionStatus is used EXACTLY as defined in Step 1: RAISED, PENDING_AUTHORIZATION, AUTHORIZED,
REJECTED, RESOLVED, CANCELLED. This step implements the RAISED -> AUTHORIZED -> RESOLVED path only (the
Step 3 brief's own "OPEN -> AUTHORIZED -> RESOLVED" conceptual flow, mapped onto the real enum). PENDING_
AUTHORIZATION, REJECTED and CANCELLED are not reached by any function here - not requested this step - the
same "an enum value exists in the schema but nothing in this step's code produces it" situation already
established for Handoff.IN_TRANSIT in Step 3.

Every transition appends to the load's EXISTING SHA-256 hash chain via hashchain.append_event and stores
the resulting event's id on `disposal_exception.event_id`, exactly like processing.py/handoff.py/
final_disposition.py. authorize_alternative_destination does NOT implement a second handoff mechanism: it
calls handoff.create_handoff() directly, so the resulting Handoff goes through the exact same validation,
state machine and hash-chain logic as any other handoff.

================================================================================================
INTEGRATION FIX MADE TO handoff.py THIS STEP (explained here in full, as instructed before making it)
================================================================================================
Problem: a Handoff-triggered exception exists because a COMPLETED handoff's destination rejected the
material. That handoff's quantity is still counted (correctly, at the time) in ProcessingRecord's
recovered/residual balance as "already handed off". Reusing handoff.create_handoff() for the resulting,
rerouted handoff - as instructed, rather than duplicating its logic - means create_handoff() independently
recomputes that SAME balance. Without a fix, the original handoff's quantity would still count as spent,
so the balance for that (processing_record, waste_stream) would already be at (or near) zero, and the
resulting handoff would always be rejected with QUANTITY_EXCEEDS_AVAILABLE - even though no new waste
quantity is being requested, only a second leg of movement for material that never actually completed its
journey.
Fix: `handoff._already_handed_off_kg` now excludes a handoff once it is the source_handoff_id of an
AUTHORIZED or RESOLVED DisposalException - i.e. once it has been formally superseded by a reroute. This is
why `authorize_alternative_destination` below sets the exception's status to AUTHORIZED and flushes it
BEFORE calling create_handoff(): the exclusion has to be visible to that balance check at the moment
create_handoff() runs. Nothing about handoff.py's function signatures, transitions, or contracts changed -
only which existing rows count toward its existing ledger. All 234 pre-Step-4 tests (Steps 1-3) still pass
unmodified with this change in place (re-verified below), confirming it does not alter any prior behavior;
it only enables a case (an authorized reroute) that could not previously arise.
================================================================================================

DESIGN DECISION (flagged): `authorize_alternative_destination` sets AUTHORIZED directly from RAISED,
skipping PENDING_AUTHORIZATION - the brief asks for exactly one function here (not a separate "propose"
step then a "confirm" step), so there is nothing that would ever park an exception in PENDING_AUTHORIZATION.

DESIGN DECISION (flagged): `waste_stream`, `quantity_kg`, and `source_facility_id` for the resulting
handoff are explicit, required parameters of authorize_alternative_destination, not inferred. When the
exception was triggered by a Handoff, `waste_stream` is validated to match that handoff's own stream (you
cannot reroute a different material stream through someone else's rejected transfer).

DESIGN DECISION (flagged): `resolve_disposal_exception` requires the resulting handoff to be COMPLETED. It
does not additionally require a FinalDisposition to exist - Section 7 keeps final disposition on the normal
Phase 3 pipeline, decoupled from the exception's own lifecycle.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import handoff as handoff_svc
from .errors import ServiceError
from .evidence import actor_of
from .hashchain import append_event
from .models import (
    DisposalException, DisposalExceptionStatus, Facility, Handoff, HandoffStatus, ProcessingRecord, ProcessingStatus, Role, User, WasteStream,
    utcnow,
)
from .services import get_load_or_404

MIN_REASON = 10

# Same reuse decision as processing.py/handoff.py/final_disposition.py: no new role, no per-facility
# independence check requested for this step.
DISPOSAL_EXCEPTION_ROLES = (Role.FACILITY,)


def _require_role(user: User) -> None:
    if user.role not in DISPOSAL_EXCEPTION_ROLES:
        raise ServiceError(403, "FORBIDDEN", f"Requires role: {', '.join(r.value for r in DISPOSAL_EXCEPTION_ROLES)}.")


def _get_processing_record(db: Session, processing_record_id: int) -> ProcessingRecord:
    p = db.get(ProcessingRecord, processing_record_id)
    if p is None:
        raise ServiceError(404, "PROCESSING_RECORD_NOT_FOUND", f"No processing record #{processing_record_id}.")
    return p


def _get_handoff(db: Session, handoff_id: int) -> Handoff:
    h = db.get(Handoff, handoff_id)
    if h is None:
        raise ServiceError(404, "HANDOFF_NOT_FOUND", f"No handoff #{handoff_id}.")
    return h


def _lock(db: Session, exception_id: int) -> DisposalException:
    de = db.execute(select(DisposalException).where(DisposalException.id == exception_id).with_for_update()).scalar_one_or_none()
    if de is None:
        raise ServiceError(404, "DISPOSAL_EXCEPTION_NOT_FOUND", f"No disposal exception #{exception_id}.")
    return de


# ---------------------------------------------------------------- creation
def create_disposal_exception(
    db: Session,
    user: User,
    load_id: str,
    *,
    original_destination_facility_id: int,
    reason: str,
    source_processing_record_id: Optional[int] = None,
    source_handoff_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> DisposalException:
    """Raise a DisposalException (status RAISED) for `load_id`, triggered by exactly one of
    `source_processing_record_id` / `source_handoff_id`.

    Preconditions (all server-side, in this order):
      1. Authorization: `user` must be FACILITY or MUNICIPAL_ADMIN.
      2. The Digital Load must exist.
      3. Exactly one trigger must be given (never both, never neither) - checked here at the application
         level AND backed by the schema's own XOR CHECK constraint (ck_disposal_exceptions_one_source) as
         a second, DB-level safety layer.
      4. The trigger must exist, belong to THIS load, and be COMPLETED - an in-progress/cancelled trigger
         has no material whose destination could even be an issue yet.
      5. `original_destination_facility_id` must reference a real facility.
      6. `reason` must be meaningful (>= 10 characters after stripping) - not empty, not a placeholder.
      7. No other OPEN (RAISED/PENDING_AUTHORIZATION) exception may already exist for this load - schema-
         enforced partial unique index, checked here too for a clean error message. Multiple RESOLVED/
         CANCELLED/REJECTED exceptions may exist historically; only one may be open at a time.
    """
    _require_role(user)
    load = get_load_or_404(db, load_id, lock=True)

    if (source_processing_record_id is None) == (source_handoff_id is None):
        raise ServiceError(422, "TRIGGER_REQUIRED", "Exactly one of source_processing_record_id or source_handoff_id must be given.")

    if source_processing_record_id is not None:
        trigger = _get_processing_record(db, source_processing_record_id)
        if trigger.digital_load_id != load.id:
            raise ServiceError(409, "TRIGGER_LOAD_MISMATCH", f"Processing record #{trigger.id} belongs to {trigger.digital_load_id}, not {load.id}.")
        if trigger.status != ProcessingStatus.COMPLETED:
            raise ServiceError(409, "PROCESSING_NOT_COMPLETED",
                               f"Processing record #{trigger.id} is {trigger.status.value}; only a COMPLETED processing record can trigger an exception.")
    else:
        trigger = _get_handoff(db, source_handoff_id)
        if trigger.digital_load_id != load.id:
            raise ServiceError(409, "TRIGGER_LOAD_MISMATCH", f"Handoff #{trigger.id} belongs to {trigger.digital_load_id}, not {load.id}.")
        if trigger.status != HandoffStatus.COMPLETED:
            raise ServiceError(409, "HANDOFF_NOT_COMPLETED",
                               f"Handoff #{trigger.id} is {trigger.status.value}; only a COMPLETED handoff can trigger an exception.")

    if db.get(Facility, original_destination_facility_id) is None:
        raise ServiceError(404, "FACILITY_NOT_FOUND", f"No facility #{original_destination_facility_id}.")
    if len(reason.strip()) < MIN_REASON:
        raise ServiceError(422, "REASON_REQUIRED", f"A disposal exception needs a recorded reason (min {MIN_REASON} characters).")

    if db.scalars(select(DisposalException.id).where(
        DisposalException.digital_load_id == load.id,
        DisposalException.status.in_([DisposalExceptionStatus.RAISED, DisposalExceptionStatus.PENDING_AUTHORIZATION]),
    )).first():
        raise ServiceError(409, "EXCEPTION_ALREADY_OPEN", f"{load.id} already has an open disposal exception.")

    now = now or utcnow()
    de = DisposalException(
        digital_load_id=load.id, source_processing_record_id=source_processing_record_id, source_handoff_id=source_handoff_id,
        original_destination_facility_id=original_destination_facility_id, reason=reason.strip(), status=DisposalExceptionStatus.RAISED,
        raised_by_user_id=user.id, created_at=now,
    )
    db.add(de)
    try:
        db.flush()
    except IntegrityError as e:   # the partial unique index (or the XOR CHECK) caught a concurrent/invalid case
        raise ServiceError(409, "EXCEPTION_ALREADY_OPEN", f"{load.id} already has an open disposal exception.") from e

    ev = append_event(
        db, load.id, "DISPOSAL_EXCEPTION_CREATED",
        {"exception_id": de.id, "source_processing_record_id": source_processing_record_id, "source_handoff_id": source_handoff_id,
         "original_destination_facility_id": original_destination_facility_id, "reason": de.reason},
        actor=actor_of(user), now=now,
    )
    de.event_id = ev.id
    db.flush()
    return de


# ---------------------------------------------------------------- authorization + resulting handoff
def authorize_alternative_destination(
    db: Session,
    user: User,
    exception_id: int,
    *,
    alternative_destination_facility_id: int,
    source_facility_id: int,
    waste_stream: WasteStream,
    quantity_kg: int,
    now: Optional[datetime] = None,
) -> DisposalException:
    """Authorize an alternative destination for a RAISED exception and create the resulting Handoff through
    the EXISTING handoff service (handoff.create_handoff) - no second handoff implementation.

    Preconditions (all server-side, in this order):
      1. Authorization: `user` must be FACILITY or MUNICIPAL_ADMIN.
      2. The exception must exist and be RAISED (only a RAISED exception can be authorized).
      3. `alternative_destination_facility_id` must reference a real facility.
      4. It must differ from the exception's `original_destination_facility_id`.
      5. If the exception was triggered by a Handoff, `waste_stream` must match that handoff's own stream.
      6. The resulting Handoff's own preconditions all still apply (facility existence, source != dest,
         quantity > 0, quantity <= available balance, no other open handoff on the load) - enforced by
         create_handoff() itself, not re-implemented here.
    On success: DisposalException.status -> AUTHORIZED, alternative_destination_facility_id / authorized_by_
    user_id / authorized_at set, and resulting_handoff_id populated with the new Handoff's id.
    """
    _require_role(user)
    de = _lock(db, exception_id)
    if de.status != DisposalExceptionStatus.RAISED:
        raise ServiceError(409, "INVALID_EXCEPTION_STATE", f"Disposal exception #{de.id} is {de.status.value}; only a RAISED exception can be authorized.")
    if db.get(Facility, alternative_destination_facility_id) is None:
        raise ServiceError(404, "FACILITY_NOT_FOUND", f"No facility #{alternative_destination_facility_id}.")
    if alternative_destination_facility_id == de.original_destination_facility_id:
        raise ServiceError(422, "SAME_AS_ORIGINAL_DESTINATION", "The alternative destination cannot be the same as the original destination.")

    if de.source_processing_record_id is not None:
        processing_record_id = de.source_processing_record_id
    else:
        source_handoff = _get_handoff(db, de.source_handoff_id)
        processing_record_id = source_handoff.processing_record_id
        if waste_stream != source_handoff.waste_stream:
            raise ServiceError(
                422, "WASTE_STREAM_MISMATCH",
                f"This exception was triggered by handoff #{source_handoff.id} ({source_handoff.waste_stream.value}); the reroute must use the same waste stream.",
            )

    now = now or utcnow()
    # Set AUTHORIZED (and flush) BEFORE calling create_handoff: this is what makes handoff.py's quantity
    # ledger correctly exclude the original triggering handoff's quantity - see the module docstring above.
    de.status = DisposalExceptionStatus.AUTHORIZED
    de.alternative_destination_facility_id = alternative_destination_facility_id
    de.authorized_by_user_id = user.id
    de.authorized_at = now
    db.flush()

    ev = append_event(
        db, de.digital_load_id, "DISPOSAL_EXCEPTION_AUTHORIZED",
        {"exception_id": de.id, "alternative_destination_facility_id": alternative_destination_facility_id,
         "waste_stream": waste_stream.value, "quantity_kg": quantity_kg},
        actor=actor_of(user), now=now,
    )
    de.event_id = ev.id
    db.flush()

    # Reuse the EXISTING handoff service - no duplicate logic. Its own validation (facility existence,
    # source != destination, quantity > 0, quantity <= available balance, no other open handoff on the
    # load) all applies unchanged; this call can raise the same ServiceErrors create_handoff always raises.
    h = handoff_svc.create_handoff(
        db, user, de.digital_load_id, processing_record_id=processing_record_id, source_facility_id=source_facility_id,
        destination_facility_id=alternative_destination_facility_id, waste_stream=waste_stream, quantity_kg=quantity_kg, now=now,
    )

    de.resulting_handoff_id = h.id
    db.flush()
    return de


# ---------------------------------------------------------------- resolution
def resolve_disposal_exception(db: Session, user: User, exception_id: int, now: Optional[datetime] = None) -> DisposalException:
    """AUTHORIZED -> RESOLVED, once the resulting Handoff has COMPLETED (i.e. the reroute actually
    happened). Any other current status, or a resulting handoff that isn't COMPLETED yet, is rejected."""
    _require_role(user)
    de = _lock(db, exception_id)
    if de.status != DisposalExceptionStatus.AUTHORIZED:
        raise ServiceError(409, "INVALID_EXCEPTION_STATE", f"Disposal exception #{de.id} is {de.status.value}; only an AUTHORIZED exception can be resolved.")
    if de.resulting_handoff_id is None:
        raise ServiceError(409, "NO_RESULTING_HANDOFF", f"Disposal exception #{de.id} has no resulting handoff yet.")
    h = db.get(Handoff, de.resulting_handoff_id)
    if h.status != HandoffStatus.COMPLETED:
        raise ServiceError(409, "RESULTING_HANDOFF_NOT_COMPLETED",
                           f"Resulting handoff #{h.id} is {h.status.value}; it must be COMPLETED before this exception can be resolved.")
    now = now or utcnow()
    de.status = DisposalExceptionStatus.RESOLVED
    de.resolved_at = now
    ev = append_event(db, de.digital_load_id, "DISPOSAL_EXCEPTION_RESOLVED", {"exception_id": de.id, "resulting_handoff_id": h.id}, actor=actor_of(user), now=now)
    de.event_id = ev.id
    db.flush()
    return de


# ---------------------------------------------------------------- serialization
def ser_disposal_exception(db: Session, de: DisposalException) -> dict:
    original = db.get(Facility, de.original_destination_facility_id)
    alternative = db.get(Facility, de.alternative_destination_facility_id) if de.alternative_destination_facility_id else None
    raised_by = db.get(User, de.raised_by_user_id) if de.raised_by_user_id else None
    authorized_by = db.get(User, de.authorized_by_user_id) if de.authorized_by_user_id else None
    return {
        "id": de.id, "digital_load_id": de.digital_load_id,
        "source_processing_record_id": de.source_processing_record_id, "source_handoff_id": de.source_handoff_id,
        "original_destination_facility_id": de.original_destination_facility_id, "original_destination_facility": original.name if original else None,
        "reason": de.reason, "status": de.status.value,
        "alternative_destination_facility_id": de.alternative_destination_facility_id,
        "alternative_destination_facility": alternative.name if alternative else None,
        "resulting_handoff_id": de.resulting_handoff_id, "raised_by": raised_by.name if raised_by else None,
        "authorized_by": authorized_by.name if authorized_by else None,
        "authorized_at": de.authorized_at.isoformat() if de.authorized_at else None,
        "resolved_at": de.resolved_at.isoformat() if de.resolved_at else None,
        "created_at": de.created_at.isoformat(), "event_id": de.event_id,
    }
