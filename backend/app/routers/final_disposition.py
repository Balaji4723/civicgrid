"""Final Disposition API. Exposes app/final_disposition.py's service functions - no business logic here."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import final_disposition as svc
from ..auth import require_capability, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..models import DispositionStatus, DispositionType, FinalDisposition, Role, User

router = APIRouter(prefix="/final-dispositions", tags=["final dispositions"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)
operator = require_capability("PROCESSING")


class CreateIn(BaseModel):
    load_id: str = Field(min_length=3, max_length=20)
    disposition_type: DispositionType
    destination_facility_id: int
    quantity_kg: int = Field(gt=0, le=100000)
    handoff_id: Optional[int] = None
    processing_record_id: Optional[int] = None
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if (self.handoff_id is None) == (self.processing_record_id is None):
            raise ValueError("Exactly one of handoff_id or processing_record_id must be given.")
        return self


class CancelIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


@router.post("")
def create(body: CreateIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    fd = svc.record_final_disposition(db, user, body.load_id.strip().upper(), disposition_type=body.disposition_type,
                                      destination_facility_id=body.destination_facility_id, quantity_kg=body.quantity_kg,
                                      handoff_id=body.handoff_id, processing_record_id=body.processing_record_id, notes=body.notes)
    db.commit()
    return svc.ser_final_disposition(db, fd)


@router.get("")
def list_final_dispositions(load_id: Optional[str] = None, status: Optional[DispositionStatus] = None,
                            user: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(FinalDisposition).order_by(FinalDisposition.id.desc())
    if load_id:
        stmt = stmt.where(FinalDisposition.digital_load_id == load_id.strip().upper())
    if status:
        stmt = stmt.where(FinalDisposition.status == status)
    return [svc.ser_final_disposition(db, fd) for fd in db.scalars(stmt)]


@router.get("/{final_disposition_id}")
def get_final_disposition(final_disposition_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    fd = db.get(FinalDisposition, final_disposition_id)
    if fd is None:
        raise ServiceError(404, "FINAL_DISPOSITION_NOT_FOUND", f"No final disposition #{final_disposition_id}.")
    return svc.ser_final_disposition(db, fd)


@router.post("/{final_disposition_id}/verify")
def verify(final_disposition_id: int, user: User = Depends(operator), db: Session = Depends(get_db)):
    fd = svc.verify_disposition(db, user, final_disposition_id)
    db.commit()
    return svc.ser_final_disposition(db, fd)


@router.post("/{final_disposition_id}/cancel")
def cancel(final_disposition_id: int, body: CancelIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    fd = svc.cancel_disposition(db, user, final_disposition_id, body.reason)
    db.commit()
    return svc.ser_final_disposition(db, fd)
