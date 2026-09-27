"""Evidence capture.

Upload pipeline (any failure aborts before anything is stored or written to the audit chain):
    sanitise file name -> read first bytes -> identify type from CONTENT -> name/Content-Type must agree
    -> stream to a temp file while counting bytes (size cap by type) and computing SHA-256 of the real bytes
    -> images are fully decoded with Pillow (corrupt / decompression-bomb refused)
    -> duplicate check on the hash -> write to EvidenceStorage under a server-generated key
    -> DB row + hash-chained EVIDENCE_ADDED event carrying the file hash.

The API never returns a filesystem path or storage key; clients get an opaque `ev_...` id.
"""
from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import evidence_validation as ev_val
from . import geo, settings
from .errors import ServiceError
from .evidence_storage import get_storage
from .hashchain import append_event
from .independence import Parties, evidence_independence, get_parties
from .models import (Audit, AuditStatus, DigitalLoad, DiscrepancyEvent, Evidence, EvidenceCategory, EvidenceKind, EvidenceSide,
                     EventLog, Role, User, utcnow)

GPS_LABEL = "GPS reported by the uploader's device — UNVERIFIED. It can be wrong or spoofed."
CHUNK = 1024 * 1024


@dataclass
class Prepared:
    fp: BinaryIO
    sha256: str
    size: int
    detected: ev_val.Detected
    safe_name: str


def new_public_id() -> str:
    return "ev_" + uuid.uuid4().hex[:24]


def actor_of(user: User) -> str:
    return f"{user.role.value.lower()}:{user.id}"


# ---------------------------------------------------------------- upload validation
def prepare_upload(fileobj: BinaryIO, filename: Optional[str], declared_content_type: Optional[str]) -> Prepared:
    safe = ev_val.safe_filename(filename)
    head = fileobj.read(ev_val.HEAD_BYTES)
    if not head:
        raise ServiceError(422, "EMPTY_FILE", "The uploaded file is empty.")
    det = ev_val.sniff(head)
    if det is None:
        raise ServiceError(415, "UNSUPPORTED_CONTENT",
                           f"The file content is {ev_val.describe_rejected(head)}. Only JPEG, PNG, WebP images and MP4/MOV/WebM video are accepted.")
    ev_val.check_type_consistency(det, safe, declared_content_type)
    limit = settings.max_video_bytes() if det.kind == "VIDEO" else settings.max_image_bytes()

    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    h = hashlib.sha256()
    total = 0
    chunk = head
    while chunk:
        total += len(chunk)
        if total > limit:
            spool.close()
            raise ServiceError(413, "FILE_TOO_LARGE", f"{det.kind.title()} files are limited to {limit:,} bytes.")
        h.update(chunk)
        spool.write(chunk)
        chunk = fileobj.read(CHUNK)
    try:
        if det.kind == "IMAGE":
            ev_val.verify_image(spool, settings.max_image_pixels())
    except ServiceError:
        spool.close()
        raise
    spool.seek(0)
    return Prepared(spool, h.hexdigest(), total, det, safe)


# ---------------------------------------------------------------- who may attach what
def resolve_side(user: User, parties: Parties, requested: Optional[EvidenceSide]) -> EvidenceSide:
    """The uploader states which signal the evidence supports, within limits set by their relationship to the case."""
    if user.role == Role.WORKER:
        if requested not in (None, EvidenceSide.WORKER):
            raise ServiceError(422, "SIDE_NOT_ALLOWED", "A worker's own evidence can only be classified as WORKER.")
        return EvidenceSide.WORKER
    if user.role == Role.FACILITY and parties.receiving_facility_id is not None and user.facility_id == parties.receiving_facility_id:
        if requested not in (None, EvidenceSide.FACILITY):
            raise ServiceError(422, "SIDE_NOT_ALLOWED", "Evidence from the receiving facility can only be classified as FACILITY.")
        return EvidenceSide.FACILITY
    return requested or EvidenceSide.NEUTRAL


def assert_can_attach_to_discrepancy(user: User, parties: Parties) -> None:
    if user.role == Role.WORKER:
        if user.worker_id is None or user.worker_id != parties.worker_id:
            raise ServiceError(403, "NOT_YOUR_LOAD", "You can only add evidence to discrepancies on your own loads.")
    elif user.role == Role.FACILITY:
        if getattr(user, "capability", None) == "INDEPENDENT_VERIFIER":
            return
        if user.facility_id is None or user.facility_id != parties.receiving_facility_id:
            raise ServiceError(403, "NOT_YOUR_FACILITY",
                               "Facility users can add evidence to loads their own facility received. Independent auditors attach evidence through their audit.")
    elif user.role != Role.MUNICIPAL_ADMIN:
        raise ServiceError(403, "FORBIDDEN", "Your role cannot add evidence.")


# ---------------------------------------------------------------- store
def _location(lat: Optional[float], lng: Optional[float]):
    if (lat is None) != (lng is None):
        raise ServiceError(422, "BAD_COORDINATES", "Send both latitude and longitude, or neither.")
    if lat is None:
        return None
    geo.validate_lat_lng(lat, lng)
    return geo.point_wkt(lat, lng)


def _event_payload(ev: Evidence, load_side_desc_hash: str, dup_public: Optional[str], loc: Optional[dict]) -> dict:
    return {
        "evidence_id": ev.public_id, "evidence_kind": ev.kind.value, "side": ev.side.value,
        "category": ev.category.value if ev.category else None, "media_type": ev.media_type, "size_bytes": ev.size_bytes,
        "sha256": ev.sha256, "uploader": ev.uploader_actor, "uploader_role": ev.uploader_role,
        "discrepancy_id": ev.discrepancy_id, "audit_id": ev.audit_id, "description_sha256": load_side_desc_hash,
        "duplicate_of": dup_public, "location": loc,
    }


def store_file_evidence(db: Session, *, user: User, load: DigitalLoad, fileobj: BinaryIO, filename: Optional[str],
                        declared_content_type: Optional[str], side: EvidenceSide, category: EvidenceCategory,
                        description: str, lat: Optional[float] = None, lng: Optional[float] = None,
                        accuracy_m: Optional[float] = None, discrepancy: Optional[DiscrepancyEvent] = None,
                        audit: Optional[Audit] = None, provenance: Optional[str] = None,
                        collection_event_id: Optional[int] = None, household_id: Optional[int] = None,
                        now: Optional[datetime] = None) -> Evidence:
    prepared = prepare_upload(fileobj, filename, declared_content_type)
    try:
        point = _location(lat, lng)
        # Check for any prior upload with the same bytes (for cross-referencing as duplicate_of)
        first_same = db.scalars(select(Evidence).where(Evidence.sha256 == prepared.sha256).order_by(Evidence.id)).first()
        if first_same is not None:
            # Only reject as DUPLICATE if SAME uploader is re-submitting the EXACT SAME file
            # in the EXACT SAME operational context (same load + same discrepancy + same audit + same provenance).
            same_case = db.scalars(select(Evidence).where(
                Evidence.sha256 == prepared.sha256,
                Evidence.load_id == load.id,
                Evidence.uploader_id == user.id,
                Evidence.discrepancy_id == (discrepancy.id if discrepancy else None),
                Evidence.audit_id == (audit.id if audit else None),
                Evidence.provenance == provenance,
            )).first()
            if same_case is not None:
                raise ServiceError(409, "DUPLICATE_EVIDENCE", "You already uploaded this exact file for this load.",
                                   existing_evidence_id=same_case.public_id)

        storage = get_storage()
        key = storage.new_key()
        storage.put(key, prepared.fp)
        now = now or utcnow()
        ev = Evidence(
            public_id=new_public_id(), kind=EvidenceKind.FILE_EVIDENCE, side=side, category=category,
            provenance=provenance, load_id=load.id, collection_event_id=collection_event_id, household_id=household_id,
            discrepancy_id=discrepancy.id if discrepancy else None, audit_id=audit.id if audit else None,
            uploader_id=user.id, uploader_actor=actor_of(user), uploader_role=user.role.value, description=description.strip(),
            original_filename=prepared.safe_name, media_type=prepared.detected.media_type, size_bytes=prepared.size,
            sha256=prepared.sha256, storage_backend=storage.backend, storage_key=key, location=point,
            location_source="DEVICE_REPORTED", location_verified=False, location_accuracy_m=accuracy_m,
            duplicate_of_id=first_same.id if first_same else None, created_at=now)
        db.add(ev)
        try:
            db.flush()
            loc = None if point is None else {"lat": f"{lat:.6f}", "lng": f"{lng:.6f}", "verified": False, "source": "DEVICE_REPORTED", "note": GPS_LABEL}
            payload = _event_payload(ev, hashlib.sha256(ev.description.encode()).hexdigest(),
                                     first_same.public_id if first_same else None, loc)
            if provenance:
                payload["provenance"] = provenance
            if household_id:
                payload["household_id"] = household_id
            if collection_event_id:
                payload["collection_event_id"] = collection_event_id
            event = append_event(db, load.id, "EVIDENCE_ADDED", payload, actor=ev.uploader_actor, now=now)
            ev.event_id = event.id
        except BaseException:
            storage.delete(key)          # never leave an unreferenced file behind when the DB write fails
            raise
        return ev
    finally:
        prepared.fp.close()


def store_note_evidence(db: Session, *, user: Optional[User], actor: str, load: DigitalLoad, discrepancy: DiscrepancyEvent,
                        note: str, side: EvidenceSide, now: Optional[datetime] = None) -> Evidence:
    """LEGACY note-only evidence. Recorded as kind NOTE - never counted as file evidence and never independent."""
    now = now or utcnow()
    ev = Evidence(public_id=new_public_id(), kind=EvidenceKind.NOTE, side=side, category=None, load_id=load.id,
                  discrepancy_id=discrepancy.id, uploader_id=user.id if user else None, uploader_actor=actor,
                  uploader_role=user.role.value if user else None, description=note, created_at=now)
    db.add(ev)
    db.flush()
    return ev


# ---------------------------------------------------------------- read models
def evidence_for_discrepancy(db: Session, d: DiscrepancyEvent) -> list[Evidence]:
    """Everything attached to the discrepancy itself, plus evidence attached to audits on the same load."""
    return list(db.scalars(select(Evidence).where(or_(Evidence.discrepancy_id == d.id,
                                                       (Evidence.load_id == d.load_id) & (Evidence.audit_id.is_not(None)))).order_by(Evidence.id)))


def ser_evidence(db: Session, ev: Evidence, parties: Optional[Parties] = None) -> dict:
    uploader = db.get(User, ev.uploader_id) if ev.uploader_id else None
    if parties is None:
        parties = get_parties(db, db.get(DigitalLoad, ev.load_id))
    dup = db.get(Evidence, ev.duplicate_of_id).public_id if ev.duplicate_of_id else None
    loc = None
    if ev.location is not None:
        from sqlalchemy import cast, func
        from geoalchemy2 import Geometry
        la, ln = db.execute(select(func.ST_Y(cast(Evidence.location, Geometry)), func.ST_X(cast(Evidence.location, Geometry))).where(Evidence.id == ev.id)).one()
        loc = {"latitude": la, "longitude": ln, "accuracy_m": ev.location_accuracy_m, "source": ev.location_source,
               "verified": False, "label": GPS_LABEL}
    return {
        "id": ev.public_id, "kind": ev.kind.value, "side": ev.side.value, "category": ev.category.value if ev.category else None,
        "provenance": ev.provenance, "load_id": ev.load_id, "household_id": ev.household_id,
        "collection_event_id": ev.collection_event_id, "discrepancy_id": ev.discrepancy_id, "audit_id": ev.audit_id,
        "uploader": {"actor": ev.uploader_actor, "name": uploader.name if uploader else None, "role": ev.uploader_role},
        "created_at": ev.created_at.isoformat(), "description": ev.description,
        "filename": ev.original_filename, "media_type": ev.media_type, "size_bytes": ev.size_bytes, "sha256": ev.sha256,
        "content_url": f"/evidence/{ev.public_id}/content" if ev.kind == EvidenceKind.FILE_EVIDENCE else None,
        "gps": loc, "gps_unverified_note": GPS_LABEL if loc else None,
        "duplicate_of": dup, "audit_event_id": ev.event_id,
        "independence": evidence_independence(ev, uploader, parties),
        "evidence_backed": ev.kind == EvidenceKind.FILE_EVIDENCE,
    }


# ---------------------------------------------------------------- who may read
def can_view(db: Session, user: User, ev: Evidence) -> bool:
    if user.role == Role.MUNICIPAL_ADMIN:
        return True
    if ev.uploader_id == user.id:
        return True
    if user.role == Role.FACILITY:
        parties = get_parties(db, db.get(DigitalLoad, ev.load_id))
        if user.facility_id is not None and user.facility_id == parties.receiving_facility_id:
            return True
        # an independent auditor may inspect the evidence of a load they are auditing (in progress or done)
        return db.scalars(select(Audit.id).where(Audit.load_id == ev.load_id, Audit.auditor_id == user.id,
                                                  Audit.status.in_([AuditStatus.IN_PROGRESS, AuditStatus.COMPLETED]))).first() is not None
    return False   # workers see only what they uploaded; citizens see nothing


def get_evidence_or_404(db: Session, public_id: str) -> Evidence:
    ev = db.scalars(select(Evidence).where(Evidence.public_id == public_id)).first()
    if ev is None:
        raise ServiceError(404, "EVIDENCE_NOT_FOUND", "No such evidence item.")
    return ev


# ---------------------------------------------------------------- integrity
def _read_all(ev: Evidence) -> bytes:
    storage = get_storage()
    if ev.storage_key is None or not storage.exists(ev.storage_key):
        raise ServiceError(500, "EVIDENCE_FILE_MISSING", "The stored file for this evidence item is missing.")
    with storage.open(ev.storage_key) as f:
        return f.read()


def verify_evidence(db: Session, ev: Evidence) -> dict:
    """Three-way check: file bytes  ==  hash stored in the DB  ==  hash written into the immutable audit event."""
    if ev.kind != EvidenceKind.FILE_EVIDENCE:
        return {"id": ev.public_id, "valid": None, "note": "Not a file: nothing to hash."}
    try:
        computed = hashlib.sha256(_read_all(ev)).hexdigest()
    except ServiceError:
        computed = None
    row = db.get(EventLog, ev.event_id) if ev.event_id else None
    chain_hash = row.payload_json.get("sha256") if row else None
    file_ok = computed == ev.sha256
    chain_ok = chain_hash == ev.sha256
    return {"id": ev.public_id, "stored_sha256": ev.sha256, "computed_sha256": computed, "chain_event_sha256": chain_hash,
            "file_matches_database": file_ok, "database_matches_audit_chain": chain_ok, "valid": bool(file_ok and chain_ok)}


def read_verified_bytes(ev: Evidence) -> bytes:
    """Bytes for download - refused if they no longer match the recorded hash (evidence was altered on disk)."""
    data = _read_all(ev)
    if hashlib.sha256(data).hexdigest() != ev.sha256:
        raise ServiceError(500, "EVIDENCE_TAMPERED", "The stored file no longer matches its recorded SHA-256. It was altered after upload.")
    return data
