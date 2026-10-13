from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CollectionTrip, DigitalLoad, DiscrepancyEvent, EventLog, ReceivingRecord, Route, Vehicle, Worker
from .resolution import next_action


def iso(dt):
    return dt.isoformat() if dt else None


def ser_discrepancy(d: DiscrepancyEvent) -> dict:
    return {
        "id": d.id, "load_id": d.load_id, "type": d.type.value, "status": d.status.value,
        "created_at": iso(d.created_at), "resolved_at": iso(d.resolved_at),
        "next_action": next_action(d.status), "details": d.details_json,
    }


def ser_event(e: EventLog, index: int) -> dict:
    return {"index": index, "id": e.id, "load_id": e.load_id, "event_type": e.event_type,
            "payload": e.payload_json, "prev_hash": e.prev_hash, "hash": e.hash, "created_at": iso(e.created_at)}


def ser_load_row(db: Session, load: DigitalLoad) -> dict:
    route = db.get(Route, load.route_id)
    worker = db.get(Worker, route.worker_id) if route and route.worker_id else None
    disc = db.scalar(select(func.count()).select_from(DiscrepancyEvent).where(DiscrepancyEvent.load_id == load.id)) or 0
    trip = db.get(CollectionTrip, load.trip_id) if load.trip_id else None
    veh = db.get(Vehicle, load.vehicle_id) if load.vehicle_id else None
    return {
        "id": load.id, "route_id": load.route_id, "ward": route.ward if route else None,
        "worker": worker.name if worker else None,
        "trip_id": load.trip_id, "trip_code": trip.trip_code if trip else None,
        "vehicle_id": load.vehicle_id, "vehicle_registration": veh.registration_number if veh else None,
        "vehicle_type": veh.vehicle_type if veh else None,
        "status": load.status.value,
        "generated_at": iso(load.generated_at),
        "declared_quantity": load.declared_quantity_kg,
        "declared_quantity_kg": load.declared_quantity_kg,
        "discrepancy_count": disc,
    }


def ser_receiving(r: ReceivingRecord | None) -> dict | None:
    if not r:
        return None
    return {"id": r.id, "facility_id": r.facility_id, "quantity": r.quantity, "condition": r.condition.value, "timestamp": iso(r.timestamp)}
