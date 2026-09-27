"""Citizen sanitation reports + the municipal ticket queue. Paths /citizen/sanitation-reports are unchanged from Phase 0."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .. import sanitation as svc
from ..auth import current_user, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..hashchain import list_events, verify_chain
from ..models import IssueType, Role, SanitationReport, TicketStatus, User
from ..serializers import ser_event

router = APIRouter(tags=["sanitation"])
citizen = require_roles(Role.CITIZEN)
admin = require_roles(Role.MUNICIPAL_ADMIN)


class SanitationIn(BaseModel):
    description: str = Field(min_length=5, max_length=1000)
    issue_type: IssueType = IssueType.OTHER
    latitude: Optional[float] = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: Optional[float] = Field(default=None, ge=0, le=100_000, allow_inf_nan=False)
    # DEVICE_REPORTED = browser/OS geolocation; CITIZEN_PLACED = pin dropped or coordinates typed by the citizen.
    # Neither is verified. The default is only an assumption about API callers who do not say.
    location_source: Literal["DEVICE_REPORTED", "CITIZEN_PLACED"] = "DEVICE_REPORTED"
    photo_name: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("send both latitude and longitude, or neither")
        if self.latitude == 0 and self.longitude == 0:
            raise ValueError("0,0 is treated as 'no GPS fix', not a real location")
        return self


class StatusIn(BaseModel):
    status: TicketStatus
    note: Optional[str] = Field(default=None, max_length=1000)


class RerouteIn(BaseModel):
    ward_id: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(min_length=5, max_length=255)


def _one(db: Session, report_id: int, **kw) -> dict:
    rows = svc.ticket_rows(db, report_id=report_id, **kw)
    if not rows:
        raise ServiceError(404, "TICKET_NOT_FOUND", f"No sanitation ticket #{report_id}.")
    return rows[0]


# ---------------------------------------------------------------- citizen
@router.post("/citizen/sanitation-reports")
def submit_report(body: SanitationIn, user: User = Depends(citizen), db: Session = Depends(get_db)):
    r = svc.create_report(db, user, description=body.description, issue_type=body.issue_type, lat=body.latitude,
                          lng=body.longitude, accuracy_m=body.accuracy_m, photo_name=body.photo_name,
                          location_source=body.location_source)
    db.commit()
    out = _one(db, r.id)
    out["routing"] = svc.routing_history(db, r.id)[-1]
    out["location_note"] = out["location"]["note"] if out["location"] else None
    return out


@router.get("/citizen/sanitation-reports")
def my_reports(user: User = Depends(citizen), db: Session = Depends(get_db)):
    return svc.ticket_rows(db, user_id=user.id)


# ---------------------------------------------------------------- municipal queue
@router.get("/sanitation/queues")
def queues(user: User = Depends(admin), db: Session = Depends(get_db)):
    return svc.queue_summary(db)


@router.get("/sanitation/tickets")
def tickets(status: Optional[TicketStatus] = None, ward_id: Optional[int] = None, queue_id: Optional[int] = None,
            user: User = Depends(admin), db: Session = Depends(get_db)):
    return svc.ticket_rows(db, status=status, ward_id=ward_id, queue_id=queue_id)


@router.get("/sanitation/tickets/{ticket_id}")
def ticket_detail(ticket_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    t = _one(db, ticket_id)
    return {**t, "routing_history": svc.routing_history(db, ticket_id)}


@router.post("/sanitation/tickets/{ticket_id}/status")
def ticket_status(ticket_id: int, body: StatusIn, user: User = Depends(admin), db: Session = Depends(get_db)):
    svc.set_status(db, ticket_id, user, body.status, body.note)
    db.commit()
    return {**_one(db, ticket_id), "routing_history": svc.routing_history(db, ticket_id)}


@router.post("/sanitation/tickets/{ticket_id}/reroute")
def ticket_reroute(ticket_id: int, body: RerouteIn, user: User = Depends(admin), db: Session = Depends(get_db)):
    svc.reroute(db, ticket_id, user, body.ward_id, body.reason)
    db.commit()
    return {**_one(db, ticket_id), "routing_history": svc.routing_history(db, ticket_id)}


@router.get("/sanitation/tickets/{ticket_id}/events")
def ticket_events(ticket_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    _one(db, ticket_id)
    return [ser_event(e, i) for i, e in enumerate(list_events(db, svc.chain_id(ticket_id)))]


@router.get("/sanitation/tickets/{ticket_id}/verify-integrity")
def ticket_verify(ticket_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in (Role.MUNICIPAL_ADMIN,) and not (user.role == Role.CITIZEN and _owns(db, user, ticket_id)):
        raise ServiceError(403, "FORBIDDEN", "You can only verify the audit trail of your own report.")
    if not db.get(SanitationReport, ticket_id):
        raise ServiceError(404, "TICKET_NOT_FOUND", f"No sanitation ticket #{ticket_id}.")
    return verify_chain(db, svc.chain_id(ticket_id))


def _owns(db: Session, user: User, ticket_id: int) -> bool:
    r = db.get(SanitationReport, ticket_id)
    return bool(r and r.user_id == user.id)
