"""Read-mostly screens backed by SEEDED data (households, workers, citizen profile) + the stored-only sanitation report."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..db import get_db
from ..errors import ServiceError
from ..models import (CollectionEvent, DigitalLoad, DiscrepancyEvent, DiscrepancyStatus, Household, Role, Route,
                      User, Worker)
from ..serializers import iso

router = APIRouter(tags=["seeded"])
admin = require_roles(Role.MUNICIPAL_ADMIN, Role.FACILITY)
citizen = require_roles(Role.CITIZEN)


@router.get("/households")
def households(user: User = Depends(admin), db: Session = Depends(get_db)):
    return [{"id": h.id, "ward": h.ward, "route_id": h.route_id, "address": h.address, "owner_name": h.owner_name,
             "civic_credits": h.civic_credits} for h in db.scalars(select(Household).order_by(Household.id))]


@router.get("/workers")
def workers(user: User = Depends(admin), db: Session = Depends(get_db)):
    out = []
    for w in db.scalars(select(Worker).order_by(Worker.id)):
        route = db.get(Route, w.assigned_route_id) if w.assigned_route_id else None
        out.append({"id": w.id, "name": w.name, "route_id": w.assigned_route_id, "ward": route.ward if route else None})
    return out


@router.get("/stats")
def stats(user: User = Depends(admin), db: Session = Depends(get_db)):
    def n(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    return {"households": n(Household), "workers": n(Worker), "loads": n(DigitalLoad),
            "open_discrepancies": n(DiscrepancyEvent, DiscrepancyEvent.status != DiscrepancyStatus.CLOSED),
            "closed_discrepancies": n(DiscrepancyEvent, DiscrepancyEvent.status == DiscrepancyStatus.CLOSED)}


@router.get("/citizen/me")
def citizen_me(user: User = Depends(citizen), db: Session = Depends(get_db)):
    hh = db.get(Household, user.household_id)
    if not hh:
        raise ServiceError(409, "NO_HOUSEHOLD", "This account is not linked to a household.")
    events = db.scalars(select(CollectionEvent).where(CollectionEvent.household_id == hh.id).order_by(CollectionEvent.timestamp.desc()))
    return {
        "household": {"id": hh.id, "ward": hh.ward, "address": hh.address, "owner_name": hh.owner_name},
        "civic_credits": hh.civic_credits,   # SEEDED, static
        "collection_history": [{"load_id": e.load_id, "status": e.status.value, "timestamp": iso(e.timestamp)} for e in events],
    }
