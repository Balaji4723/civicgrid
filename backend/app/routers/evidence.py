"""Evidence: multipart upload, provenance, authorised download, integrity check. There is deliberately NO update or delete."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import evidence as svc
from .. import resolution, settings
from ..auth import current_user, require_roles
from ..db import get_db
from ..errors import ServiceError
from ..independence import auditor_violations, get_parties
from ..models import (Audit, AuditCorroboration, AuditTargetType, DiscrepancyEvent, DiscrepancyStatus, EvidenceCategory, EvidenceKind, EvidenceSide, Role, User)
from ..models import DigitalLoad
from ..serializers import iso

router = APIRouter(tags=["evidence"])
uploader = require_roles(Role.WORKER, Role.FACILITY, Role.MUNICIPAL_ADMIN)
OPEN_FOR_EVIDENCE = (DiscrepancyStatus.FLAGGED, DiscrepancyStatus.EVIDENCE_PENDING, DiscrepancyStatus.CORROBORATED, DiscrepancyStatus.INVESTIGATING)


def limit_body(request: Request) -> None:
    """Refuse an obviously oversized body from its Content-Length before reading it. (A reverse proxy must enforce a
    hard cap for chunked uploads - see README.)"""
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > settings.max_video_bytes() + 2 * 1024 * 1024:
        raise ServiceError(413, "BODY_TOO_LARGE", "The request is larger than the maximum evidence upload size.")


@router.get("/config/evidence")
def evidence_config(user: User = Depends(current_user)):
    return settings.public_evidence_config()


@router.post("/discrepancy/{discrepancy_id}/evidence")
def upload_for_discrepancy(
    discrepancy_id: int, _: None = Depends(limit_body), file: UploadFile = File(...),
    side: Optional[EvidenceSide] = Form(None), category: EvidenceCategory = Form(EvidenceCategory.LOAD_PHOTO),
    description: str = Form(..., min_length=3, max_length=1000),
    latitude: Optional[float] = Form(None, ge=-90, le=90, allow_inf_nan=False), longitude: Optional[float] = Form(None, ge=-180, le=180, allow_inf_nan=False),
    accuracy_m: Optional[float] = Form(None, ge=0, le=100000, allow_inf_nan=False),
    user: User = Depends(uploader), db: Session = Depends(get_db),
):
    d = db.get(DiscrepancyEvent, discrepancy_id)
    if d is None:
        raise ServiceError(404, "DISCREPANCY_NOT_FOUND", f"No discrepancy #{discrepancy_id}.")
    load = db.get(DigitalLoad, d.load_id)
    parties = get_parties(db, load)
    svc.assert_can_attach_to_discrepancy(user, parties)
    if d.status not in OPEN_FOR_EVIDENCE:
        raise ServiceError(409, "DISCREPANCY_CLOSED_FOR_EVIDENCE", f"Discrepancy #{d.id} is {d.status.value}; evidence can no longer be added.")
    ev = svc.store_file_evidence(db, user=user, load=load, fileobj=file.file, filename=file.filename, declared_content_type=file.content_type,
                                 side=svc.resolve_side(user, parties, side), category=category, description=description,
                                 lat=latitude, lng=longitude, accuracy_m=accuracy_m, discrepancy=d)
    db.commit()
    return svc.ser_evidence(db, ev, parties)


@router.post("/loads/{load_id}/evidence")
def upload_for_load(
    load_id: str, _: None = Depends(limit_body), file: UploadFile = File(...),
    side: Optional[EvidenceSide] = Form(None), category: EvidenceCategory = Form(EvidenceCategory.LOAD_PHOTO),
    provenance: Optional[str] = Form(None), household_id: Optional[int] = Form(None),
    collection_event_id: Optional[int] = Form(None),
    description: str = Form(..., min_length=3, max_length=1000),
    latitude: Optional[float] = Form(None, ge=-90, le=90, allow_inf_nan=False), longitude: Optional[float] = Form(None, ge=-180, le=180, allow_inf_nan=False),
    accuracy_m: Optional[float] = Form(None, ge=0, le=100000, allow_inf_nan=False),
    user: User = Depends(uploader), db: Session = Depends(get_db),
):
    load = db.get(DigitalLoad, load_id.strip().upper())
    if load is None:
        raise ServiceError(404, "LOAD_NOT_FOUND", f"No load '{load_id}'.")
    parties = get_parties(db, load)
    if user.role == Role.WORKER and user.worker_id != parties.worker_id:
        raise ServiceError(403, "NOT_YOUR_LOAD", "You can only add evidence to your own assigned load.")
    
    # Resolve default provenance if not passed explicitly
    prov = provenance
    if not prov:
        if "random audit" in description.lower() or "random verification" in description.lower() or category == EvidenceCategory.AUDIT_OBSERVATION:
            prov = "RANDOM_AUDIT"
        elif "non-compliance" in description.lower() or "unsegregated" in description.lower() or "negative" in description.lower():
            prov = "NEGATIVE_EVENT"

    ev = svc.store_file_evidence(db, user=user, load=load, fileobj=file.file, filename=file.filename, declared_content_type=file.content_type,
                                 side=svc.resolve_side(user, parties, side), category=category, description=description,
                                 lat=latitude, lng=longitude, accuracy_m=accuracy_m, provenance=prov,
                                 collection_event_id=collection_event_id, household_id=household_id)
    
    if (prov == "RANDOM_AUDIT" or (category == EvidenceCategory.AUDIT_OBSERVATION and prov != "NEGATIVE_EVENT") or ("random audit" in description.lower() and prov != "NEGATIVE_EVENT")) and (collection_event_id is not None or household_id is not None):
        reason = description.strip()
        if len(reason) < 10:
            hh_label = f"Household HH-{household_id}" if household_id else "household"
            reason = f"Random Audit photo evidence captured during {hh_label} collection"
        from ..models import Audit, AuditMethod, AuditStatus, AuditTargetType, utcnow
        audit = Audit(
            target_type=AuditTargetType.COLLECTION_EVENT,
            load_id=load.id,
            household_id=household_id,
            collection_event_id=collection_event_id,
            worker_id=parties.worker_id,
            actor_user_id=user.id,
            facility_id=parties.receiving_facility_id,
            method=AuditMethod.RANDOM,
            risk_score=0.0,
            risk_factors={"source": "COLLECTION_EVENT_RANDOM_AUDIT", "target": f"HH-{household_id}" if household_id else None},
            selection_reason=reason,
            status=AuditStatus.COMPLETED,
            auditor_id=None,
            started_at=utcnow(),
            completed_at=utcnow(),
            result_json={
                "type": "COLLECTION_EVENT_AUDIT",
                "target": f"HH-{household_id}" if household_id else "COLLECTION_EVENT",
                "actor": f"worker:{user.worker_id or user.id}",
                "observations": description.strip(),
                "verdicts": {"STREAM": "BOTH_AGREE", "QUANTITY": "BOTH_AGREE"},
                "overall": "BOTH_AGREE",
                "evidence_ids": [ev.public_id],
            }
        )
        db.add(audit)
        db.flush()
        ev.audit_id = audit.id

    db.commit()
    return svc.ser_evidence(db, ev, parties)


def case_view(db: Session, d: DiscrepancyEvent, viewer: User) -> dict:
    """Evidence list + independence panel for a discrepancy (staff view)."""
    load = db.get(DigitalLoad, d.load_id)
    parties = get_parties(db, load)
    items = [svc.ser_evidence(db, e, parties) for e in svc.evidence_for_discrepancy(db, d)]
    files = [i for i in items if i["kind"] == "FILE_EVIDENCE"]
    notes = [i for i in items if i["kind"] == "NOTE"]
    legacy = bool((d.details_json or {}).get("evidence")) and not files
    mode = "FILE_BACKED" if files else ("LEGACY_NOTE_ONLY" if (notes or legacy) else "NONE")
    from ..models import Worker, Facility
    w = db.get(Worker, parties.worker_id) if parties.worker_id else None
    rec_user = db.get(User, parties.recorder_user_id) if parties.recorder_user_id else None
    fac = db.get(Facility, parties.receiving_facility_id) if parties.receiving_facility_id else None
    audits = []
    for a in db.scalars(select(Audit).where(Audit.load_id == d.load_id, Audit.target_type == AuditTargetType.DIGITAL_LOAD).order_by(Audit.id)):
        auditor = db.get(User, a.auditor_id) if a.auditor_id else None
        viol = auditor_violations(auditor, parties) if auditor else []
        corr = db.scalars(select(AuditCorroboration).where(AuditCorroboration.audit_id == a.id, AuditCorroboration.discrepancy_id == d.id)).first()
        audits.append({"audit_id": a.id, "status": a.status.value, "method": a.method.value, "auditor": auditor.name if auditor else None,
                       "auditor_role": auditor.role.value if auditor else None, "independent": None if auditor is None else not viol,
                       "violations": viol, "overall": (a.result_json or {}).get("overall"),
                       "evaluated": {"outcome": corr.outcome.value, "reason_code": corr.reason_code} if corr else None})
    audit_info = (d.details_json or {}).get("audit")
    return {
        "evidence": items, "evidence_mode": mode,
        "evidence_summary": {"files": len(files), "notes": len(notes), "independent_files": sum(1 for i in files if i["independence"]["independent"])},
        "corroboration_path": None if not audit_info else audit_info.get("path", "LEGACY_MANUAL_ENTRY"),
        "corroboration_evidence_backed": bool(audit_info and audit_info.get("evidence_backed")),
        "require_file_evidence": settings.require_file_evidence(),
        "independence": {
            "principle": "AI can flag. Independent evidence corroborates.",
            "parties": {"worker": {"id": parties.worker_id, "name": w.name if w else None},
                        "facility_recorder": {"user_id": parties.recorder_user_id, "name": rec_user.name if rec_user else None},
                        "receiving_facility": {"id": parties.receiving_facility_id, "name": fac.name if fac else None}},
            "audits": audits,
        },
    }


@router.get("/discrepancy/{discrepancy_id}/evidence")
def list_for_discrepancy(discrepancy_id: int, user: User = Depends(require_roles(Role.FACILITY, Role.MUNICIPAL_ADMIN)), db: Session = Depends(get_db)):
    d = db.get(DiscrepancyEvent, discrepancy_id)
    if d is None:
        raise ServiceError(404, "DISCREPANCY_NOT_FOUND", f"No discrepancy #{discrepancy_id}.")
    view = case_view(db, d, user)
    if user.role == Role.FACILITY:     # facility users see what they are entitled to see
        allowed = {e.public_id for e in svc.evidence_for_discrepancy(db, d) if svc.can_view(db, user, e)}
        view["evidence"] = [e for e in view["evidence"] if e["id"] in allowed]
    return view


@router.get("/evidence/{public_id}")
def evidence_meta(public_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = svc.get_evidence_or_404(db, public_id)
    if not svc.can_view(db, user, ev):
        raise ServiceError(403, "FORBIDDEN", "You are not allowed to view this evidence.")
    return svc.ser_evidence(db, ev)


@router.get("/evidence/{public_id}/content")
def evidence_content(public_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = svc.get_evidence_or_404(db, public_id)
    if not svc.can_view(db, user, ev):
        raise ServiceError(403, "FORBIDDEN", "You are not allowed to view this evidence.")
    if ev.kind != EvidenceKind.FILE_EVIDENCE:
        raise ServiceError(404, "NO_FILE", "This evidence item has no file.")
    data = svc.read_verified_bytes(ev)       # refuses (500 EVIDENCE_TAMPERED) if the bytes no longer match the recorded hash
    return Response(content=data, media_type=ev.media_type, headers={
        "Content-Disposition": f'inline; filename="{ev.original_filename}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox", "X-Evidence-SHA256": ev.sha256,
    })


@router.get("/evidence/{public_id}/verify")
def evidence_verify(public_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = svc.get_evidence_or_404(db, public_id)
    if not svc.can_view(db, user, ev):
        raise ServiceError(403, "FORBIDDEN", "You are not allowed to view this evidence.")
    return svc.verify_evidence(db, ev)
