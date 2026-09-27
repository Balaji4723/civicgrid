"""The ONE demo-only admin endpoint: deliberately corrupts an event WITHOUT recomputing its hash."""
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..auth import require_roles
from ..db import get_db
from ..errors import ServiceError
from ..models import EventLog, Role, User
from ..services import get_load_or_404

router = APIRouter(prefix="/admin", tags=["admin (demo only)"])


class CorruptIn(BaseModel):
    patch: Optional[dict[str, Any]] = None  # optional; default is chosen automatically


@router.post("/loads/{load_id}/corrupt-event/{event_id}")
def corrupt_event(load_id: str, event_id: int, body: Optional[CorruptIn] = None,
                  user: User = Depends(require_roles(Role.MUNICIPAL_ADMIN)), db: Session = Depends(get_db)):
    get_load_or_404(db, load_id)
    ev = db.execute(select(EventLog).where(EventLog.id == event_id, EventLog.load_id == load_id)).scalar_one_or_none()
    if not ev:
        raise ServiceError(404, "EVENT_NOT_FOUND", f"Event {event_id} does not belong to {load_id}.")
    before = dict(ev.payload_json)
    patch = (body.patch if body and body.patch else None)
    if patch is None:
        # Default: quietly inflate a recorded quantity (i.e. hide a shortfall); else just stamp the payload.
        patch = {"quantity": int(before["quantity"] * 1.3)} if isinstance(before.get("quantity"), int) else {"tampered": True}
    after = {**before, **patch}
    ev.payload_json = after      # payload changes ...
    flag_modified(ev, "payload_json")
    # ... but ev.hash / ev.prev_hash are deliberately left untouched.
    db.commit()
    return {"load_id": load_id, "event_id": event_id, "event_type": ev.event_type, "before": before, "after": after,
            "hash_recomputed": False, "next_step": f"GET /loads/{load_id}/verify-integrity"}
