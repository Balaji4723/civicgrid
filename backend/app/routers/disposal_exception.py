"""Disposal Exception API. Exposes app/disposal_exception.py's service functions - no business logic here."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import disposal_exception as svc
from ..auth import require_capability, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..models import DisposalException, DisposalExceptionStatus, Role, User, WasteStream

router = APIRouter(prefix="/disposal-exceptions", tags=["disposal exceptions"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)
operator = require_capability("PROCESSING")


class CreateIn(BaseModel):
    load_id: str = Field(min_length=3, max_length=20)
    original_destination_facility_id: int
    reason: str = Field(min_length=10, max_length=1000)
    source_processing_record_id: Optional[int] = None
    source_handoff_id: Optional[int] = None

    @model_validator(mode="after")
    def _exactly_one_trigger(self):
        if (self.source_processing_record_id is None) == (self.source_handoff_id is None):
            raise ValueError("Exactly one of source_processing_record_id or source_handoff_id must be given.")
        return self


class AuthorizeIn(BaseModel):
    alternative_destination_facility_id: int
    source_facility_id: int
    waste_stream: WasteStream
    quantity_kg: int = Field(gt=0, le=100000)


@router.post("")
def create(body: CreateIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    de = svc.create_disposal_exception(db, user, body.load_id.strip().upper(), original_destination_facility_id=body.original_destination_facility_id,
                                       reason=body.reason, source_processing_record_id=body.source_processing_record_id,
                                       source_handoff_id=body.source_handoff_id)
    db.commit()
    return svc.ser_disposal_exception(db, de)


@router.get("")
def list_disposal_exceptions(load_id: Optional[str] = None, status: Optional[DisposalExceptionStatus] = None,
                             user: User = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(DisposalException).order_by(DisposalException.id.desc())
    if load_id:
        stmt = stmt.where(DisposalException.digital_load_id == load_id.strip().upper())
    if status:
        stmt = stmt.where(DisposalException.status == status)
    return [svc.ser_disposal_exception(db, de) for de in db.scalars(stmt)]


@router.get("/{exception_id}")
def get_disposal_exception(exception_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    de = db.get(DisposalException, exception_id)
    if de is None:
        raise ServiceError(404, "DISPOSAL_EXCEPTION_NOT_FOUND", f"No disposal exception #{exception_id}.")
    return svc.ser_disposal_exception(db, de)


@router.post("/{exception_id}/authorize")
def authorize(exception_id: int, body: AuthorizeIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    de = svc.authorize_alternative_destination(db, user, exception_id, alternative_destination_facility_id=body.alternative_destination_facility_id,
                                               source_facility_id=body.source_facility_id, waste_stream=body.waste_stream, quantity_kg=body.quantity_kg)
    db.commit()
    return svc.ser_disposal_exception(db, de)


@router.post("/{exception_id}/resolve")
def resolve(exception_id: int, user: User = Depends(operator), db: Session = Depends(get_db)):
    de = svc.resolve_disposal_exception(db, user, exception_id)
    db.commit()
    return svc.ser_disposal_exception(db, de)
