"""CORE COMPONENT 3 - hash-chained, tamper-evident event log.

    event_hash = sha256( json.dumps(payload, sort_keys=True) + prev_hash )

Each load has its own chain. The first event of a load chains to GENESIS_HASH.
The hashed payload always carries `event_type`, `ts` and `actor` so those fields are
covered by the hash too (a tamper of the event_type column is caught by verify_chain).

Technique: linked-hash secure log (cf. Schneier & Kelsey, 1998). We implement the hash
linking only - not their forward-secure MAC keys - so this is *tamper-evident*, not
tamper-proof against someone who can rewrite every subsequent row (see README).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import GENESIS_HASH
from .models import DigitalLoad, EventLog, utcnow


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True)


def compute_hash(payload: dict, prev_hash: str) -> str:
    return hashlib.sha256((canonical(payload) + prev_hash).encode("utf-8")).hexdigest()


def _append(db: Session, chain_id: str, load_id: Optional[str], lock_stmt, event_type: str,
            data: Optional[dict[str, Any]], actor: str, now: Optional[datetime]) -> EventLog:
    # Lock the owning row so two concurrent writers cannot both chain to the same prev_hash.
    db.execute(lock_stmt.with_for_update()).scalar_one()
    last = db.execute(
        select(EventLog).where(EventLog.chain_id == chain_id).order_by(EventLog.id.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = last.hash if last else GENESIS_HASH

    now = now or utcnow()
    payload = {"event_type": event_type, "ts": now.isoformat(), "actor": actor, **(data or {})}
    payload = json.loads(canonical(payload))  # normalise exactly as it will round-trip through the DB

    row = EventLog(
        chain_id=chain_id,
        load_id=load_id,
        event_type=event_type,
        payload_json=payload,
        prev_hash=prev_hash,
        hash=compute_hash(payload, prev_hash),
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def append_event(
    db: Session,
    load_id: str,
    event_type: str,
    data: Optional[dict[str, Any]] = None,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> EventLog:
    """Append one event to a Digital Load's chain. Every load state change calls this (unchanged behaviour)."""
    lock = select(DigitalLoad).where(DigitalLoad.id == load_id)
    return _append(db, load_id, load_id, lock, event_type, data, actor, now)


def append_chain_event(
    db: Session,
    chain_id: str,
    lock_stmt,
    event_type: str,
    data: Optional[dict[str, Any]] = None,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> EventLog:
    """Append to a chain that is not a Digital Load (e.g. a sanitation ticket, chain_id "SR-12").

    Same table, same hash function, same verification as load chains. `lock_stmt` selects the owning row
    (e.g. the ticket) so writers to one chain are serialised.
    """
    return _append(db, chain_id, None, lock_stmt, event_type, data, actor, now)


def list_events(db: Session, chain_id: str) -> list[EventLog]:
    return list(db.scalars(select(EventLog).where(EventLog.chain_id == chain_id).order_by(EventLog.id)))


def verify_chain(db: Session, chain_id: str) -> dict:
    """Walk the chain, recompute every hash. Returns {valid, broken_at_index, ...}."""
    load_id = chain_id if chain_id.startswith("DL-") else None  # response key kept for load chains
    rows = list_events(db, chain_id)
    prev = GENESIS_HASH
    for index, row in enumerate(rows):
        reason = None
        if compute_hash(row.payload_json, row.prev_hash) != row.hash:
            reason = "Stored hash does not match the recomputed hash - this event's payload was modified."
        elif row.prev_hash != prev:
            reason = "prev_hash does not link to the previous event - an event was removed, inserted or reordered."
        elif row.payload_json.get("event_type") != row.event_type:
            reason = "event_type column differs from the hashed payload."
        if reason:
            return {
                "load_id": load_id,
                "chain_id": chain_id,
                "valid": False,
                "broken_at_index": index,
                "broken_event_id": row.id,
                "reason": reason,
                "total_events": len(rows),
                "head_hash": rows[-1].hash if rows else GENESIS_HASH,
            }
        prev = row.hash
    return {
        "load_id": load_id,
        "chain_id": chain_id,
        "valid": True,
        "broken_at_index": None,
        "broken_event_id": None,
        "reason": None,
        "total_events": len(rows),
        "head_hash": prev,
    }
