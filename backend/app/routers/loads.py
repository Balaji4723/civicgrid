from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_capability, require_roles
from ..db import get_db
from ..hashchain import list_events, verify_chain
from ..models import Condition, DigitalLoad, DiscrepancyEvent, DisposalException, FinalDisposition, Handoff, ProcessingRecord, ReceivingRecord, Role, User
from ..serializers import ser_discrepancy, ser_event, ser_load_row, ser_receiving
from ..services import build_declaration, create_receiving_record, get_load_or_404
from .. import disposal_exception as de_svc
from .. import final_disposition as fd_svc
from .. import handoff as ho_svc
from .. import processing as proc_svc

router = APIRouter(tags=["loads"])
staff = require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)


class ReceivingIn(BaseModel):
    quantity: int = Field(gt=0, le=100000)
    condition: Condition


@router.get("/loads")
def list_loads(user: User = Depends(staff), db: Session = Depends(get_db)):
    loads = db.scalars(select(DigitalLoad).order_by(DigitalLoad.id))
    return [ser_load_row(db, l) for l in loads]


@router.get("/loads/{load_id}")
def load_detail(load_id: str, user: User = Depends(staff), db: Session = Depends(get_db)):
    load = get_load_or_404(db, load_id)
    rec = db.scalars(select(ReceivingRecord).where(ReceivingRecord.load_id == load.id)).first()
    discs = db.scalars(select(DiscrepancyEvent).where(DiscrepancyEvent.load_id == load.id).order_by(DiscrepancyEvent.id))
    events = list_events(db, load.id)
    crew = []
    if load.trip_id:
        from ..models import TripCrew, Worker
        crews = db.scalars(select(TripCrew).where(TripCrew.trip_id == load.trip_id)).all()
        for c in crews:
            w = db.get(Worker, c.worker_id)
            if w:
                crew.append({"id": w.id, "name": w.name, "role": c.role_in_crew})
    return {
        **ser_load_row(db, load),
        "crew": crew,
        "declaration": build_declaration(db, load),
        "receiving": ser_receiving(rec),
        "discrepancies": [ser_discrepancy(d) for d in discs],
        "event_count": len(events),
        "head_hash": events[-1].hash if events else None,
    }


@router.get("/loads/{load_id}/events")
def load_events(load_id: str, user: User = Depends(staff), db: Session = Depends(get_db)):
    get_load_or_404(db, load_id)
    return [ser_event(e, i) for i, e in enumerate(list_events(db, load_id))]


@router.get("/loads/{load_id}/verify-integrity")
def verify_integrity(load_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_load_or_404(db, load_id)
    return verify_chain(db, load_id)


@router.get("/loads/{load_id}/timeline")
def load_timeline(load_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The load's complete journey, built entirely from real persisted records: the chronological,
    tamper-evident event_log (the same data verify-integrity checks) plus the current Phase 3 entities
    (processing/handoff/final-disposition/disposal-exception rows) tied to this load. Nothing here is
    fabricated or static - every field is a direct read of a persisted row."""
    load = get_load_or_404(db, load_id)
    events = list_events(db, load_id)
    return {
        "load_id": load.id, "load_status": load.status.value,
        "events": [ser_event(e, i) for i, e in enumerate(events)],
        "processing_records": [proc_svc.ser_processing(db, p) for p in
                               db.scalars(select(ProcessingRecord).where(ProcessingRecord.digital_load_id == load.id).order_by(ProcessingRecord.id))],
        "handoffs": [ho_svc.ser_handoff(db, h) for h in
                    db.scalars(select(Handoff).where(Handoff.digital_load_id == load.id).order_by(Handoff.id))],
        "final_dispositions": [fd_svc.ser_final_disposition(db, fd) for fd in
                               db.scalars(select(FinalDisposition).where(FinalDisposition.digital_load_id == load.id).order_by(FinalDisposition.id))],
        "disposal_exceptions": [de_svc.ser_disposal_exception(db, de) for de in
                                db.scalars(select(DisposalException).where(DisposalException.digital_load_id == load.id).order_by(DisposalException.id))],
    }


operator = require_capability("RECEIVING")


@router.post("/loads/{load_id}/receiving")
def receive(load_id: str, body: ReceivingIn, user: User = Depends(operator), db: Session = Depends(get_db)):
    out = create_receiving_record(db, load_id, user.facility_id or 1, body.quantity, body.condition, actor=f"{user.role.value.lower()}:{user.id}",
                                   recorded_by_user_id=user.id)
    db.commit()
    return {"cross_check_result": out["result"], "load": ser_load_row(db, out["load"]),
            "receiving": ser_receiving(out["receiving"]),
            "discrepancies": [ser_discrepancy(d) for d in out["discrepancies"]],
            "note": ("Records match within tolerance; no discrepancy created." if out["result"] == "MATCH"
                     else "Mismatch flagged for review. Nobody is blamed until an independent second signal corroborates it.")}
