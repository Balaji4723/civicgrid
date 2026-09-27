"""Sanitation reports as routed tickets.

    citizen report (+GPS) -> validate -> PostGIS point -> point-in-polygon against wards
        -> ward -> authority queue -> routing decision row + hash-chained audit event

Audit: every state change appends to the ticket's own hash chain (chain_id "SR-<id>") through the SAME
event_log table and SAME hash function as Digital Load chains (hashchain.append_chain_event).
Free text (description, resolution notes) is deliberately NOT written into the immutable chain: the chain
carries a SHA-256 of the note instead, so it stays tamper-evident without making free text permanent.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session

from .config import LOCATION_NOTE, LOCATION_NOTES
from .errors import ServiceError
from .geo import point_wkt, validate_lat_lng
from .hashchain import append_chain_event
from .models import (AuthorityQueue, IssueType, RoutingOutcome, SanitationReport, SanitationRoutingDecision,
                     TicketStatus, User, Ward, utcnow)

CHAIN_PREFIX = "SR-"
# Status transitions available to the municipal team after routing.
STATUS_FLOW = {TicketStatus.ROUTED: TicketStatus.IN_PROGRESS, TicketStatus.IN_PROGRESS: TicketStatus.RESOLVED}


def location_note(source: str) -> str:
    return LOCATION_NOTES.get(source, LOCATION_NOTE)


def chain_id(report_id: int) -> str:
    return f"{CHAIN_PREFIX}{report_id}"


def _lock(report_id: int):
    return select(SanitationReport).where(SanitationReport.id == report_id)


def _emit(db: Session, report_id: int, event_type: str, data: dict[str, Any], actor: str, now: Optional[datetime]):
    return append_chain_event(db, chain_id(report_id), _lock(report_id), event_type, data, actor, now)


def clean_filename(name: Optional[str]) -> Optional[str]:
    """Keep only a safe display name (no paths, no control characters). Real uploads arrive in Phase 2."""
    if not name:
        return None
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r"[^\w.\- ]", "_", base).strip()[:120]
    return base or None


def _latlng(db: Session, report_id: int) -> Optional[tuple[float, float]]:
    r = db.execute(select(func.ST_Y(cast(SanitationReport.location, Geometry)), func.ST_X(cast(SanitationReport.location, Geometry)))
                   .where(SanitationReport.id == report_id, SanitationReport.location.is_not(None))).first()
    return (r[0], r[1]) if r else None


def _location_payload(db: Session, report: SanitationReport) -> Optional[dict]:
    ll = _latlng(db, report.id)
    if not ll:
        return None
    return {"lat": f"{ll[0]:.6f}", "lng": f"{ll[1]:.6f}", "source": report.location_source,
            "verified": report.location_verified,
            "accuracy_m": None if report.location_accuracy_m is None else f"{report.location_accuracy_m:.1f}",
            "note": location_note(report.location_source)}


# ------------------------------------------------------------------ routing
def _find_wards(db: Session, report_id: int) -> list[Ward]:
    """PostGIS point-in-polygon using the STORED point of the report."""
    ids = db.execute(text(
        "SELECT w.id FROM wards w JOIN sanitation_reports r ON r.id = :rid "
        "WHERE r.location IS NOT NULL AND ST_Covers(w.boundary, r.location::geometry) ORDER BY w.id"), {"rid": report_id}).scalars().all()
    return [db.get(Ward, i) for i in ids]


def _record_decision(db: Session, report: SanitationReport, *, outcome: RoutingOutcome, method: str, ward: Optional[Ward],
                     queue: Optional[AuthorityQueue], reason: str, detail: dict, event_type: str,
                     actor_user: Optional[User], now: datetime) -> SanitationRoutingDecision:
    d = SanitationRoutingDecision(
        report_id=report.id, outcome=outcome, method=method, ward_id=ward.id if ward else None,
        queue_id=queue.id if queue else None, reason=reason,
        boundary_source=f"{ward.source_name} v{ward.source_version}" if ward else None,
        boundary_is_official=bool(ward.is_official) if ward else False, detail_json=detail,
        decided_by=actor_user.id if actor_user else None, decided_at=now)
    db.add(d)
    db.flush()
    payload = {"report_id": report.id, "decision_id": d.id, "outcome": outcome.value, "method": method, "reason": reason,
              "ward_code": ward.code if ward else None, "ward_name": ward.name if ward else None,
              "queue_code": queue.code if queue else None,
              "boundary_source": d.boundary_source, "boundary_is_official": d.boundary_is_official,
              "location": _location_payload(db, report), **{k: v for k, v in detail.items() if k == "candidate_ward_codes"}}
    ev = _emit(db, report.id, event_type, payload, f"user:{actor_user.id}" if actor_user else "routing-engine", now)
    d.event_id = ev.id
    report.ward_id, report.queue_id = (ward.id if ward else None), (queue.id if queue else None)
    report.status = TicketStatus.ROUTED if outcome == RoutingOutcome.ROUTED else TicketStatus.UNROUTABLE
    report.updated_at = now
    return d


def route_report(db: Session, report: SanitationReport, actor_user: Optional[User] = None, now: Optional[datetime] = None,
                 event_type: str = "SANITATION_ROUTED") -> SanitationRoutingDecision:
    """Automatic GPS routing. Never guesses: no point, no ward, several wards, or no queue -> UNROUTABLE (manual triage)."""
    now = now or utcnow()
    if _latlng(db, report.id) is None:
        return _record_decision(db, report, outcome=RoutingOutcome.UNROUTABLE, method="POINT_IN_POLYGON", ward=None, queue=None,
                                reason="NO_LOCATION", detail={}, event_type="SANITATION_UNROUTABLE", actor_user=actor_user, now=now)
    wards = _find_wards(db, report.id)
    if not wards:
        return _record_decision(db, report, outcome=RoutingOutcome.UNROUTABLE, method="POINT_IN_POLYGON", ward=None, queue=None,
                                reason="OUTSIDE_ALL_WARDS", detail={}, event_type="SANITATION_UNROUTABLE", actor_user=actor_user, now=now)
    if len(wards) > 1:
        return _record_decision(db, report, outcome=RoutingOutcome.UNROUTABLE, method="POINT_IN_POLYGON", ward=None, queue=None,
                                reason="OVERLAPPING_WARDS", detail={"candidate_ward_codes": [w.code for w in wards]},
                                event_type="SANITATION_UNROUTABLE", actor_user=actor_user, now=now)
    ward = wards[0]
    queue = db.get(AuthorityQueue, ward.queue_id) if ward.queue_id else None
    if not queue:
        return _record_decision(db, report, outcome=RoutingOutcome.UNROUTABLE, method="POINT_IN_POLYGON", ward=ward, queue=None,
                                reason="WARD_HAS_NO_QUEUE", detail={}, event_type="SANITATION_UNROUTABLE", actor_user=actor_user, now=now)
    return _record_decision(db, report, outcome=RoutingOutcome.ROUTED, method="POINT_IN_POLYGON", ward=ward, queue=queue,
                            reason="POINT_INSIDE_WARD_POLYGON", detail={}, event_type=event_type, actor_user=actor_user, now=now)


def create_report(db: Session, user: User, *, description: str, issue_type: IssueType, lat: Optional[float], lng: Optional[float],
                  accuracy_m: Optional[float], photo_name: Optional[str], location_source: str = "DEVICE_REPORTED",
                  now: Optional[datetime] = None) -> SanitationReport:
    now = now or utcnow()
    if location_source not in LOCATION_NOTES:
        raise ServiceError(422, "BAD_LOCATION_SOURCE", f"location_source must be one of {sorted(LOCATION_NOTES)}.")
    if (lat is None) != (lng is None):
        raise ServiceError(422, "BAD_COORDINATES", "Send both latitude and longitude, or neither.")
    if lat is not None:
        validate_lat_lng(lat, lng)
    report = SanitationReport(
        user_id=user.id, description=description, issue_type=issue_type, photo_name=clean_filename(photo_name),
        location=point_wkt(lat, lng) if lat is not None else None, location_source=location_source, location_verified=False,
        location_accuracy_m=accuracy_m, status=TicketStatus.SUBMITTED, created_at=now)
    db.add(report)
    db.flush()
    _emit(db, report.id, "SANITATION_SUBMITTED",
          {"report_id": report.id, "issue_type": issue_type.value, "has_photo": bool(report.photo_name),
           "description_sha256": hashlib.sha256(description.encode()).hexdigest(), "location": _location_payload(db, report)},
          f"citizen:{user.id}", now)
    route_report(db, report, now=now)
    return report


# ------------------------------------------------------------------ authority actions
def _get(db: Session, report_id: int) -> SanitationReport:
    r = db.execute(select(SanitationReport).where(SanitationReport.id == report_id).with_for_update()).scalar_one_or_none()
    if not r:
        raise ServiceError(404, "TICKET_NOT_FOUND", f"No sanitation ticket #{report_id}.")
    return r


def set_status(db: Session, report_id: int, actor: User, new_status: TicketStatus, note: Optional[str] = None,
               now: Optional[datetime] = None) -> SanitationReport:
    r = _get(db, report_id)
    allowed = STATUS_FLOW.get(r.status)
    if allowed is None or new_status != allowed:
        raise ServiceError(409, "INVALID_TRANSITION",
                           f"Ticket is {r.status.value}; " + (f"the only valid next status is {allowed.value}." if allowed else "no further status change is possible here."),
                           current_status=r.status.value, allowed_status=allowed.value if allowed else None)
    if new_status == TicketStatus.RESOLVED and not (note and len(note.strip()) >= 3):
        raise ServiceError(422, "NOTE_REQUIRED", "Describe how the issue was resolved (min 3 characters).")
    now = now or utcnow()
    prev = r.status
    r.status, r.updated_at = new_status, now
    if note:
        r.resolution_note = note.strip()
    _emit(db, r.id, "SANITATION_STATUS_CHANGED",
          {"report_id": r.id, "from": prev.value, "to": new_status.value,
           "note_sha256": hashlib.sha256(note.strip().encode()).hexdigest() if note else None,
           "queue_code": db.get(AuthorityQueue, r.queue_id).code if r.queue_id else None}, f"user:{actor.id}", now)
    return r


def reroute(db: Session, report_id: int, actor: User, ward_id: Optional[int], reason: str, now: Optional[datetime] = None) -> SanitationReport:
    """ward_id given -> MANUAL_OVERRIDE by a person (reason required); None -> re-run automatic point-in-polygon."""
    r = _get(db, report_id)
    if r.status in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED):
        raise ServiceError(409, "CANNOT_REROUTE", f"Ticket is {r.status.value}; only unrouted or routed tickets can be re-routed.")
    if len((reason or "").strip()) < 5:
        raise ServiceError(422, "REASON_REQUIRED", "Give a reason for the re-routing (min 5 characters).")
    now = now or utcnow()
    if ward_id is None:
        route_report(db, r, actor_user=actor, now=now, event_type="SANITATION_REROUTED")
        return r
    ward = db.get(Ward, ward_id)
    if not ward:
        raise ServiceError(404, "WARD_NOT_FOUND", f"No ward {ward_id}.")
    queue = db.get(AuthorityQueue, ward.queue_id) if ward.queue_id else None
    if not queue:
        raise ServiceError(409, "WARD_HAS_NO_QUEUE", f"{ward.name} has no authority queue configured.")
    _record_decision(db, r, outcome=RoutingOutcome.ROUTED, method="MANUAL_OVERRIDE", ward=ward, queue=queue,
                     reason=reason.strip()[:255], detail={}, event_type="SANITATION_REROUTED", actor_user=actor, now=now)
    return r


def route_backfill(db: Session) -> dict:
    """Route legacy reports (created before PostGIS) that have a location but no routing decision yet."""
    ids = db.execute(text(
        "SELECT r.id FROM sanitation_reports r WHERE NOT EXISTS "
        "(SELECT 1 FROM sanitation_routing_decisions d WHERE d.report_id = r.id) ORDER BY r.id")).scalars().all()
    routed = unroutable = 0
    for rid in ids:
        r = _get(db, rid)
        legacy_user_actor = None
        if not db.execute(text("SELECT 1 FROM event_log WHERE chain_id = :c LIMIT 1"), {"c": chain_id(rid)}).first():
            _emit(db, rid, "SANITATION_SUBMITTED",
                  {"report_id": rid, "issue_type": r.issue_type.value, "has_photo": bool(r.photo_name),
                   "description_sha256": hashlib.sha256(r.description.encode()).hexdigest(),
                   "location": _location_payload(db, r), "backfilled": True}, "migration-backfill", r.created_at)
        d = route_report(db, r, actor_user=legacy_user_actor)
        routed += d.outcome == RoutingOutcome.ROUTED
        unroutable += d.outcome == RoutingOutcome.UNROUTABLE
    db.commit()
    return {"reports_processed": len(ids), "routed": routed, "unroutable": unroutable}


# ------------------------------------------------------------------ read models
def ticket_rows(db: Session, *, user_id: Optional[int] = None, status: Optional[TicketStatus] = None, ward_id: Optional[int] = None,
                queue_id: Optional[int] = None, report_id: Optional[int] = None, limit: int = 500) -> list[dict]:
    stmt = (select(SanitationReport, func.ST_Y(cast(SanitationReport.location, Geometry)), func.ST_X(cast(SanitationReport.location, Geometry)),
                   Ward, AuthorityQueue)
            .outerjoin(Ward, Ward.id == SanitationReport.ward_id).outerjoin(AuthorityQueue, AuthorityQueue.id == SanitationReport.queue_id)
            .order_by(SanitationReport.id.desc()).limit(limit))
    if user_id is not None:
        stmt = stmt.where(SanitationReport.user_id == user_id)
    if status:
        stmt = stmt.where(SanitationReport.status == status)
    if ward_id:
        stmt = stmt.where(SanitationReport.ward_id == ward_id)
    if queue_id:
        stmt = stmt.where(SanitationReport.queue_id == queue_id)
    if report_id:
        stmt = stmt.where(SanitationReport.id == report_id)
    out = []
    for r, lat, lng, w, q in db.execute(stmt).all():
        out.append({
            "id": r.id, "issue_type": r.issue_type.value, "description": r.description, "status": r.status.value,
            "photo_name": r.photo_name, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "resolution_note": r.resolution_note,
            "ward": {"id": w.id, "code": w.code, "name": w.name, "source_label": w.source_label, "is_official": w.is_official} if w else None,
            "queue": {"id": q.id, "code": q.code, "name": q.name} if q else None,
            "location": None if lat is None else {"latitude": lat, "longitude": lng, "source": r.location_source, "verified": r.location_verified,
                                                   "accuracy_m": r.location_accuracy_m, "note": location_note(r.location_source)},
            "chain_id": chain_id(r.id)})
    return out


def routing_history(db: Session, report_id: int) -> list[dict]:
    rows = db.execute(select(SanitationRoutingDecision, Ward, AuthorityQueue)
                      .outerjoin(Ward, Ward.id == SanitationRoutingDecision.ward_id)
                      .outerjoin(AuthorityQueue, AuthorityQueue.id == SanitationRoutingDecision.queue_id)
                      .where(SanitationRoutingDecision.report_id == report_id).order_by(SanitationRoutingDecision.id)).all()
    return [{"id": d.id, "outcome": d.outcome.value, "method": d.method, "reason": d.reason, "ward": w.name if w else None,
             "queue": q.name if q else None, "boundary_source": d.boundary_source, "boundary_is_official": d.boundary_is_official,
             "decided_by_user_id": d.decided_by, "decided_at": d.decided_at.isoformat(), "event_id": d.event_id,
             "candidates": d.detail_json.get("candidate_ward_codes")} for d, w, q in rows]


def queue_summary(db: Session) -> list[dict]:
    rows = db.execute(select(AuthorityQueue, SanitationReport.status, func.count(SanitationReport.id))
                      .outerjoin(SanitationReport, SanitationReport.queue_id == AuthorityQueue.id)
                      .group_by(AuthorityQueue.id, SanitationReport.status).order_by(AuthorityQueue.id)).all()
    out: dict[int, dict] = {}
    for q, st, n in rows:
        o = out.setdefault(q.id, {"id": q.id, "code": q.code, "name": q.name, "counts": {s.value: 0 for s in TicketStatus}})
        if st is not None:
            o["counts"][st.value] = n
    unrouted = db.scalar(select(func.count()).select_from(SanitationReport).where(SanitationReport.status.in_([TicketStatus.UNROUTABLE, TicketStatus.SUBMITTED])))
    return list(out.values()) + [{"id": None, "code": "MANUAL_TRIAGE", "name": "Manual triage (no ward could be determined)",
                                  "counts": {"UNROUTABLE": unrouted or 0}}]
