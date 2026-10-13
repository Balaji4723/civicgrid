"""Load lifecycle + receiving verification (the trigger for the Cross-Check Engine)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import crosscheck
from .errors import ServiceError
from .hashchain import append_event
from .models import (
    Audit, AuditMethod, AuditStatus, CollectionEvent, CollectionStatus, CollectionTrip, Condition, DigitalLoad, DiscrepancyEvent, DiscrepancyStatus,
    DiscrepancyType, Household, LoadStatus, ReceivingRecord, Route, TripCrew, Vehicle, Worker, utcnow,
)


def normalize_session_id(session_id: Optional[str] = None) -> Optional[str]:
    from .sessions import current_session_id
    sid = session_id or current_session_id.get()
    if not sid:
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", str(sid).strip())[:32]
    return cleaned or None


def crew_role_for_session(session_id: Optional[str]) -> str:
    sid = normalize_session_id(session_id)
    return f"CREW_LEAD:{sid}" if sid else "CREW_LEAD"


def is_load_in_session(db: Session, load_id: Optional[str], session_id: Optional[str] = None) -> bool:
    if not load_id:
        return True
    try:
        num = int(load_id.split("-")[1])
        if num <= 1021:
            return True
    except (IndexError, ValueError):
        return True
    load = db.get(DigitalLoad, load_id)
    if not load or not load.trip_id:
        return False
    sid = normalize_session_id(session_id)
    role = crew_role_for_session(sid)
    has_crew = db.scalar(
        select(TripCrew.id).where(TripCrew.trip_id == load.trip_id, TripCrew.role_in_crew == role)
    )
    if not has_crew:
        return False
    return True


def next_load_id(db: Session) -> str:
    n = db.scalar(select(func.count()).select_from(DigitalLoad)) or 0
    candidate = 1001 + n
    while db.get(DigitalLoad, f"DL-{candidate}"):
        candidate += 1
    return f"DL-{candidate}"


def get_audit_target_household_id(db: Session, route_id: int, trip_id: int) -> Optional[int]:
    """Deterministically pick ONE household from the route as the hidden random audit target.
    Uses a SHA-256 digest of (route_id, trip_id) as seed so selection is:
    - reproducible across requests (same trip always targets the same household)
    - backend-only (never sent in the household list)
    - independent of frontend Math.random()
    Returns None if no households exist on the route.
    """
    households = list(db.scalars(
        select(Household).where(Household.route_id == route_id).order_by(Household.id)
    ))
    if not households:
        return None
    seed_bytes = f"{route_id}:{trip_id}".encode()
    digest = hashlib.sha256(seed_bytes).digest()
    idx = int.from_bytes(digest[:4], "big") % len(households)
    return households[idx].id


def is_audit_required_for_household(db: Session, route_id: int, trip_id: int, household_id: int, load: Optional["DigitalLoad"]) -> bool:
    """Returns True if this household is the secret audit target AND no audit evidence has been captured yet."""
    target = get_audit_target_household_id(db, route_id, trip_id)
    if target != household_id:
        return False
    if load is None:
        return True
    # If any audit (status COMPLETED) is already on this load, the audit has been done
    from .models import AuditStatus
    existing = db.scalars(
        select(Audit).where(
            Audit.load_id == load.id,
            Audit.status == AuditStatus.COMPLETED,
        )
    ).first()
    return existing is None


def get_load_or_404(db: Session, load_id: str, lock: bool = False) -> DigitalLoad:
    stmt = select(DigitalLoad).where(DigitalLoad.id == load_id)
    if lock:
        stmt = stmt.with_for_update()
    load = db.execute(stmt).scalar_one_or_none()
    if not load:
        raise ServiceError(404, "LOAD_NOT_FOUND", f"No Digital Load with ID '{load_id}'.")
    return load


def active_load_for_route(db: Session, route_id: int, session_id: Optional[str] = None) -> Optional[DigitalLoad]:
    sid = normalize_session_id(session_id)
    stmt = select(DigitalLoad).where(DigitalLoad.route_id == route_id, DigitalLoad.status == LoadStatus.COLLECTING)
    if sid:
        stmt = stmt.join(TripCrew, TripCrew.trip_id == DigitalLoad.trip_id).where(
            TripCrew.role_in_crew == crew_role_for_session(sid)
        )
    else:
        stmt = stmt.join(TripCrew, TripCrew.trip_id == DigitalLoad.trip_id, isouter=True).where(
            (TripCrew.role_in_crew == "CREW_LEAD") | (TripCrew.role_in_crew.is_(None))
        )
    return db.execute(stmt.order_by(DigitalLoad.generated_at.desc())).scalars().first()


def active_trip_for_route(db: Session, route_id: int, session_id: Optional[str] = None) -> Optional[CollectionTrip]:
    sid = normalize_session_id(session_id)
    stmt = select(CollectionTrip).where(
        CollectionTrip.route_id == route_id,
        CollectionTrip.status.in_(["IN_PROGRESS", "VERIFICATION_PAUSED"]),
    )
    if sid:
        stmt = stmt.join(TripCrew, TripCrew.trip_id == CollectionTrip.id).where(
            TripCrew.role_in_crew == crew_role_for_session(sid)
        )
    else:
        stmt = stmt.join(TripCrew, TripCrew.trip_id == CollectionTrip.id, isouter=True).where(
            (TripCrew.role_in_crew == "CREW_LEAD") | (TripCrew.role_in_crew.is_(None))
        )
    return db.execute(stmt.order_by(CollectionTrip.start_time.desc())).scalars().first()


def get_or_create_active_trip(
    db: Session, route_id: int, worker_id: int, now: Optional[datetime] = None, session_id: Optional[str] = None
) -> CollectionTrip:
    now = now or utcnow()
    trip = active_trip_for_route(db, route_id, session_id=session_id)
    if trip is None:
        veh = db.get(Vehicle, route_id) or db.scalars(select(Vehicle).where(Vehicle.status == "ACTIVE")).first()
        veh_id = veh.id if veh else None
        # Use MAX(id) so trip codes never collide with seeded rows regardless of count
        max_id = db.scalar(select(func.max(CollectionTrip.id))) or 0
        trip_code = f"CT-2026-{41 + max_id:04d}"
        trip = CollectionTrip(
            trip_code=trip_code,
            route_id=route_id,
            vehicle_id=veh_id,
            start_time=now,
            status="IN_PROGRESS",
            verification_triggered=False,
            verification_acknowledged=False,
            verification_paused_at_count=3 if route_id in (1, 2) else None,
            receiving_facility_id=1,
        )
        db.add(trip)
        db.flush()
        crew = TripCrew(trip_id=trip.id, worker_id=worker_id, role_in_crew=crew_role_for_session(session_id))
        db.add(crew)
        db.flush()
    return trip


def get_or_create_active_load(
    db: Session,
    route_id: int,
    worker_id: int,
    trip: Optional[CollectionTrip] = None,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> DigitalLoad:
    """Gets the currently collecting load for route, or initializes a new DigitalLoad attached to the active trip."""
    now = now or utcnow()
    if trip is None:
        trip = get_or_create_active_trip(db, route_id, worker_id, now=now, session_id=session_id)
    load = active_load_for_route(db, route_id, session_id=session_id)
    if load is None:
        route = db.get(Route, route_id)
        load = DigitalLoad(
            id=next_load_id(db),
            route_id=route.id,
            trip_id=trip.id,
            vehicle_id=trip.vehicle_id,
            receiving_facility_id=trip.receiving_facility_id,
            generated_at=now,
            status=LoadStatus.COLLECTING,
        )
        db.add(load)
        db.flush()
        veh_reg = db.scalar(select(Vehicle.registration_number).where(Vehicle.id == trip.vehicle_id)) if trip.vehicle_id else None
        append_event(db, load.id, "LOAD_CREATED",
                     {"route_id": route.id, "ward": route.ward, "worker_id": worker_id, "trip_code": trip.trip_code, "vehicle": veh_reg},
                     actor=f"worker:{worker_id}", now=now)
    elif load.trip_id is not None and load.trip_id != trip.id:
        # Stale COLLECTING load belongs to a different trip — create a fresh one for this trip
        route = db.get(Route, route_id)
        load = DigitalLoad(
            id=next_load_id(db),
            route_id=route.id,
            trip_id=trip.id,
            vehicle_id=trip.vehicle_id,
            receiving_facility_id=trip.receiving_facility_id,
            generated_at=now,
            status=LoadStatus.COLLECTING,
        )
        db.add(load)
        db.flush()
        veh_reg = db.scalar(select(Vehicle.registration_number).where(Vehicle.id == trip.vehicle_id)) if trip.vehicle_id else None
        append_event(db, load.id, "LOAD_CREATED",
                     {"route_id": route.id, "ward": route.ward, "worker_id": worker_id, "trip_code": trip.trip_code, "vehicle": veh_reg},
                     actor=f"worker:{worker_id}", now=now)
    elif load.trip_id is None:
        load.trip_id = trip.id
        load.vehicle_id = trip.vehicle_id
        load.receiving_facility_id = trip.receiving_facility_id
    return load


def build_declaration(db: Session, load: DigitalLoad) -> dict:
    """The collection crew's declaration for a load, derived from its collection events + declared trip quantity."""
    events = list(db.scalars(select(CollectionEvent).where(CollectionEvent.load_id == load.id)))
    seg = sum(1 for e in events if e.status == CollectionStatus.SEGREGATED)
    total = len(events)
    veh_reg = None
    trip_code = None
    if load.vehicle_id:
        veh_reg = db.scalar(select(Vehicle.registration_number).where(Vehicle.id == load.vehicle_id))
    if load.trip_id:
        trip_code = db.scalar(select(CollectionTrip.trip_code).where(CollectionTrip.id == load.trip_id))
    return {
        "source": crosscheck.WORKER_SOURCE,
        "trip_code": trip_code,
        "vehicle_registration": veh_reg,
        "households_collected": total,
        "segregated": seg,
        "unsegregated": total - seg,
        "stream": crosscheck.declared_stream(seg, total),
        "quantity": load.declared_quantity_kg,
    }


# ---------------------------------------------------------------- worker side
def record_collection(
    db: Session,
    worker: Worker,
    household_id: int,
    status: CollectionStatus,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> tuple[DigitalLoad, CollectionEvent]:
    """Worker records household collection. Links to the vehicle collection trip."""
    if worker.assigned_route_id is None:
        raise ServiceError(409, "NO_ROUTE", "This worker has no assigned route.")
    hh = db.get(Household, household_id)
    if not hh or hh.route_id != worker.assigned_route_id:
        raise ServiceError(403, "NOT_ON_ROUTE", "That household is not on your assigned route.")
    now = now or utcnow()

    trip = get_or_create_active_trip(db, worker.assigned_route_id, worker.id, now=now, session_id=session_id)
    if trip.status == "VERIFICATION_PAUSED" and not trip.verification_acknowledged:
        raise ServiceError(409, "VERIFICATION_PAUSED", "Collection is paused for system verification. Please acknowledge protocol before continuing.")

    load = get_or_create_active_load(db, worker.assigned_route_id, worker.id, trip=trip, now=now, session_id=session_id)

    already = db.scalar(select(CollectionEvent.id).where(
        CollectionEvent.load_id == load.id, CollectionEvent.household_id == household_id))
    if already:
        raise ServiceError(409, "ALREADY_MARKED", f"Household {household_id} is already marked on {load.id}.")

    ev = CollectionEvent(household_id=household_id, worker_id=worker.id, load_id=load.id, status=status, timestamp=now)
    db.add(ev)
    db.flush()
    append_event(db, load.id, "COLLECTION_RECORDED",
                 {"collection_event_id": ev.id, "household_id": household_id, "status": status.value},
                 actor=f"worker:{worker.id}", now=now)

    return load, ev


def acknowledge_trip_verification(
    db: Session, worker: Worker, now: Optional[datetime] = None, session_id: Optional[str] = None
) -> CollectionTrip:
    if worker.assigned_route_id is None:
        raise ServiceError(409, "NO_ROUTE", "This worker has no assigned route.")
    trip = active_trip_for_route(db, worker.assigned_route_id, session_id=session_id)
    if not trip:
        raise ServiceError(404, "NO_ACTIVE_TRIP", "No active collection trip found.")
    now = now or utcnow()
    trip.verification_acknowledged = True
    trip.status = "IN_PROGRESS"
    load = active_load_for_route(db, worker.assigned_route_id, session_id=session_id)
    if load:
        append_event(db, load.id, "SYSTEM_VERIFICATION_ACKNOWLEDGED",
                     {"trip_code": trip.trip_code, "worker_id": worker.id, "note": "Worker acknowledged system verification protocol."},
                     actor=f"worker:{worker.id}", now=now)
    return trip


def declare_load(
    db: Session,
    worker: Worker,
    load_id: str,
    quantity_kg: Optional[int] = None,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> DigitalLoad:
    load = get_load_or_404(db, load_id, lock=True)
    route = db.get(Route, load.route_id)
    if route.worker_id != worker.id:
        raise ServiceError(403, "NOT_YOUR_LOAD", "This load belongs to another worker's route.")
    if load.status != LoadStatus.COLLECTING:
        raise ServiceError(409, "ALREADY_DECLARED", f"{load.id} is {load.status.value}; it can no longer be declared.")
    now = now or utcnow()
    if quantity_kg is not None:
        load.declared_quantity_kg = quantity_kg
    declaration = build_declaration(db, load)
    if declaration["households_collected"] == 0:
        raise ServiceError(409, "NOTHING_COLLECTED", "Mark at least one household before declaring the load.")
    load.status = LoadStatus.DECLARED
    trip = db.get(CollectionTrip, load.trip_id) if load.trip_id else active_trip_for_route(db, load.route_id, session_id=session_id)
    if trip:
        trip.status = "COMPLETED"
        trip.end_time = now
    append_event(db, load.id, "LOAD_DECLARED", {"declaration": declaration}, actor=f"worker:{worker.id}", now=now)
    return load


# ---------------------------------------------------- receiving -> Cross-Check
def create_receiving_record(
    db: Session, load_id: str, facility_id: int, quantity: int, condition: Condition,
    actor: str, now: Optional[datetime] = None, recorded_by_user_id: Optional[int] = None,
) -> dict:
    load = get_load_or_404(db, load_id, lock=True)
    if load.status != LoadStatus.DECLARED:
        raise ServiceError(409, "LOAD_NOT_RECEIVABLE",
                           f"{load.id} is {load.status.value}. Only a DECLARED load (worker has submitted) can be received.")
    now = now or utcnow()
    rec = ReceivingRecord(load_id=load.id, facility_id=facility_id, quantity=quantity, condition=condition, timestamp=now,
                          recorded_by_user_id=recorded_by_user_id)
    db.add(rec)
    db.flush()
    append_event(db, load.id, "RECEIVING_RECORDED",
                 {"receiving_record_id": rec.id, "facility_id": facility_id, "quantity": quantity, "condition": condition.value},
                 actor=actor, now=now)

    # ---- Cross-Check Engine trigger
    declaration = build_declaration(db, load)
    signal = {"source": "FACILITY_RECEIVING", "quantity": quantity, "condition": condition.value}
    result = crosscheck.compare_records(declaration, signal)

    created: list[DiscrepancyEvent] = []
    if result == crosscheck.MATCH:
        load.status = LoadStatus.VERIFIED
        append_event(db, load.id, "CROSSCHECK_MATCH",
                     {"declared_quantity": declaration["quantity"], "received_quantity": quantity}, actor="cross-check-engine", now=now)
    else:
        load.status = LoadStatus.DISPUTED
        for dim in crosscheck.find_mismatches(declaration, signal):
            d = DiscrepancyEvent(
                load_id=load.id, type=DiscrepancyType(dim), status=DiscrepancyStatus.FLAGGED, created_at=now,
                details_json={"declaration": declaration, "receiving": signal, "evidence": [], "audit": None,
                              "resolution": None, "closing_note": None},
            )
            db.add(d)
            db.flush()
            created.append(d)
            append_event(db, load.id, "DISCREPANCY_FLAGGED",
                         {"discrepancy_id": d.id, "type": dim, "declared": declaration["quantity"] if dim == "QUANTITY" else declaration["stream"],
                          "observed": quantity if dim == "QUANTITY" else condition.value,
                          "attribution": "NONE - flagged for review only; awaiting an independent second signal"},
                         actor="cross-check-engine", now=now)
    return {"result": result, "load": load, "receiving": rec, "discrepancies": created, "declaration": declaration}


def sync_load_status_after_close(db: Session, load_id: str) -> None:
    load = db.get(DigitalLoad, load_id)
    open_count = db.scalar(select(func.count()).select_from(DiscrepancyEvent).where(
        DiscrepancyEvent.load_id == load_id, DiscrepancyEvent.status != DiscrepancyStatus.CLOSED))
    if open_count == 0:
        load.status = LoadStatus.SETTLED
