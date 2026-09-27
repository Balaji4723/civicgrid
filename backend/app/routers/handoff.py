"""Handoff API. Exposes app/handoff.py's service functions - no business logic here."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import handoff as svc
from ..auth import require_capability, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..models import Handoff, HandoffStatus, Role, User, WasteStream

router = APIRouter(prefix="/handoffs", tags=["handoffs"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)
operator = require_capability("PROCESSING")


class CreateIn(BaseModel):
    load_id: str = Field(min_length=3, max_length=20)
    processing_record_id: int
    source_facility_id: int
    destination_facility_id: int
    waste_stream: WasteStream
    quantity_kg: int = Field(gt=0, le=100000)
    notes: str = Field(default="", max_length=2000)


class CancelIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


@router.post("")
def create(body: CreateIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    h = svc.create_handoff(db, user, body.load_id.strip().upper(), processing_record_id=body.processing_record_id,
                           source_facility_id=body.source_facility_id, destination_facility_id=body.destination_facility_id,
                           waste_stream=body.waste_stream, quantity_kg=body.quantity_kg, notes=body.notes)
    db.commit()
    return svc.ser_handoff(db, h)


@router.get("")
def list_handoffs(load_id: Optional[str] = None, status: Optional[HandoffStatus] = None, user: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(Handoff).order_by(Handoff.id.desc())
    if load_id:
        stmt = stmt.where(Handoff.digital_load_id == load_id.strip().upper())
    if status:
        stmt = stmt.where(Handoff.status == status)
    return [svc.ser_handoff(db, h) for h in db.scalars(stmt)]


@router.get("/{handoff_id}")
def get_handoff(handoff_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    h = db.get(Handoff, handoff_id)
    if h is None:
        raise ServiceError(404, "HANDOFF_NOT_FOUND", f"No handoff #{handoff_id}.")
    return svc.ser_handoff(db, h)


@router.post("/{handoff_id}/complete")
def complete(handoff_id: int, user: User = Depends(operator), db: Session = Depends(get_db)):
    h = svc.complete_handoff(db, user, handoff_id)
    db.commit()
    return svc.ser_handoff(db, h)


@router.post("/{handoff_id}/cancel")
def cancel(handoff_id: int, body: CancelIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    h = svc.cancel_handoff(db, user, handoff_id, body.reason)
    db.commit()
    return svc.ser_handoff(db, h)
