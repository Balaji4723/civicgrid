"""Processing API. Exposes app/processing.py's service functions - no business logic here, only request
parsing, RBAC (defense-in-depth alongside the service layer's own check), and serialization."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import processing as svc
from ..auth import require_capability, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..models import ProcessingMethod, ProcessingRecord, ProcessingStatus, Role, User, WasteStream

router = APIRouter(prefix="/processing", tags=["processing"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)
operator = require_capability("PROCESSING")


class StartIn(BaseModel):
    load_id: str = Field(min_length=3, max_length=20)
    facility_id: int
    waste_stream: WasteStream
    processing_method: ProcessingMethod
    processed_quantity_kg: int = Field(gt=0, le=100000)
    recovered_quantity_kg: int = Field(default=0, ge=0, le=100000)
    residual_quantity_kg: int = Field(default=0, ge=0, le=100000)
    notes: str = Field(default="", max_length=2000)


class CancelIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


@router.post("")
def start(body: StartIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    p = svc.start_processing(db, user, body.load_id.strip().upper(), facility_id=body.facility_id, waste_stream=body.waste_stream,
                             processing_method=body.processing_method, processed_quantity_kg=body.processed_quantity_kg,
                             recovered_quantity_kg=body.recovered_quantity_kg, residual_quantity_kg=body.residual_quantity_kg, notes=body.notes)
    db.commit()
    return svc.ser_processing(db, p)


@router.get("")
def list_processing(load_id: Optional[str] = None, status: Optional[ProcessingStatus] = None, user: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(ProcessingRecord).order_by(ProcessingRecord.id.desc())
    if load_id:
        stmt = stmt.where(ProcessingRecord.digital_load_id == load_id.strip().upper())
    if status:
        stmt = stmt.where(ProcessingRecord.status == status)
    return [svc.ser_processing(db, p) for p in db.scalars(stmt)]


@router.get("/{processing_record_id}")
def get_processing(processing_record_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    p = db.get(ProcessingRecord, processing_record_id)
    if p is None:
        raise ServiceError(404, "PROCESSING_RECORD_NOT_FOUND", f"No processing record #{processing_record_id}.")
    return svc.ser_processing(db, p)


@router.post("/{processing_record_id}/complete")
def complete(processing_record_id: int, user: User = Depends(operator), db: Session = Depends(get_db)):
    p = svc.complete_processing(db, user, processing_record_id)
    db.commit()
    return svc.ser_processing(db, p)


@router.post("/{processing_record_id}/cancel")
def cancel(processing_record_id: int, body: CancelIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    p = svc.cancel_processing(db, user, processing_record_id, body.reason)
    db.commit()
    return svc.ser_processing(db, p)
