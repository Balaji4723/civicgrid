"""Postgres schema. Columns beyond the spec are marked  # +  and listed in the README."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from geoalchemy2 import Geography, Geometry
from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    CITIZEN = "CITIZEN"
    WORKER = "WORKER"
    FACILITY = "FACILITY"
    MUNICIPAL_ADMIN = "MUNICIPAL_ADMIN"


class CollectionStatus(str, enum.Enum):
    SEGREGATED = "SEGREGATED"
    UNSEGREGATED = "UNSEGREGATED"


class Condition(str, enum.Enum):
    ACCEPTABLE = "ACCEPTABLE"
    UNACCEPTABLE = "UNACCEPTABLE"


class DiscrepancyType(str, enum.Enum):
    QUANTITY = "QUANTITY"
    STREAM = "STREAM"


class DiscrepancyStatus(str, enum.Enum):
    FLAGGED = "FLAGGED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    CORROBORATED = "CORROBORATED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IssueType(str, enum.Enum):
    OVERFLOWING_BIN = "OVERFLOWING_BIN"
    ILLEGAL_DUMPING = "ILLEGAL_DUMPING"
    BLOCKED_DRAIN = "BLOCKED_DRAIN"
    MISSED_COLLECTION = "MISSED_COLLECTION"
    OTHER = "OTHER"


class TicketStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"        # received, not routed yet (also the state of legacy reports before backfill)
    ROUTED = "ROUTED"              # point-in-polygon matched exactly one ward with a queue
    UNROUTABLE = "UNROUTABLE"      # no GPS / outside every ward / overlapping wards -> manual triage
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class RoutingOutcome(str, enum.Enum):
    ROUTED = "ROUTED"
    UNROUTABLE = "UNROUTABLE"


class EvidenceKind(str, enum.Enum):
    FILE_EVIDENCE = "FILE_EVIDENCE"   # a real uploaded file (hashed, stored)
    AUDIT_RESULT = "AUDIT_RESULT"     # structured result submitted by an auditor (no file)
    NOTE = "NOTE"                     # free text only. NOT equivalent to file evidence.


class EvidenceSide(str, enum.Enum):
    WORKER = "WORKER"      # supports the worker's declaration
    FACILITY = "FACILITY"  # supports the facility's receiving record
    NEUTRAL = "NEUTRAL"


class EvidenceCategory(str, enum.Enum):
    LOAD_PHOTO = "LOAD_PHOTO"
    WEIGHBRIDGE_SLIP = "WEIGHBRIDGE_SLIP"
    VIDEO_WALKTHROUGH = "VIDEO_WALKTHROUGH"
    AUDIT_OBSERVATION = "AUDIT_OBSERVATION"
    OTHER = "OTHER"


class AuditTargetType(str, enum.Enum):
    COLLECTION_EVENT = "COLLECTION_EVENT"
    DIGITAL_LOAD = "DIGITAL_LOAD"


class AuditMethod(str, enum.Enum):
    RANDOM = "RANDOM"
    RISK_BASED = "RISK_BASED"
    MANUAL = "MANUAL"


class AuditStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CorroborationOutcome(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_SUPPORTS_WORKER = "REJECTED_SUPPORTS_WORKER"
    REJECTED_INCONCLUSIVE = "REJECTED_INCONCLUSIVE"
    REJECTED_NOT_INDEPENDENT = "REJECTED_NOT_INDEPENDENT"
    REJECTED_NO_EVIDENCE = "REJECTED_NO_EVIDENCE"


class LoadStatus(str, enum.Enum):  # +  spec leaves digital_loads.status open
    COLLECTING = "COLLECTING"   # worker still marking households
    DECLARED = "DECLARED"       # worker declared quantity; awaiting facility
    VERIFIED = "VERIFIED"       # facility record matched declaration
    DISPUTED = "DISPUTED"       # >=1 open discrepancy
    SETTLED = "SETTLED"         # all discrepancies closed
    # NOTE (Phase 3): this enum is intentionally left untouched. What happens to a load AFTER receiving
    # (processing / handoff / final disposition) is tracked by the status of its own Phase 3 rows below,
    # not by adding states here - see the architecture note above the Phase 3 models.


# Phase 3: ProcessingStatus mirrors AuditStatus's PENDING/IN_PROGRESS/COMPLETED/CANCELLED shape - same kind
# of "one worker-driven task with a lifecycle" as an Audit, just at a processing facility instead of an auditor.
class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WasteStream(str, enum.Enum):
    """The material stream a quantity belongs to at a processing/handoff step. Distinct from the
    collection-time CollectionStatus (SEGREGATED/UNSEGREGATED): this describes what a facility is
    moving or processing, not how a household set it out.
    OPEN DESIGN DECISION (flagged for product confirmation): this taxonomy is a reasonable default,
    not something the spec pinned down. RECOVERED/RESIDUAL cover a ProcessingRecord's two output
    quantities; the rest cover a load's material category. Confirm/adjust before Step 2."""
    ORGANIC = "ORGANIC"
    RECYCLABLE = "RECYCLABLE"
    MIXED = "MIXED"
    RESIDUAL = "RESIDUAL"
    RECOVERED = "RECOVERED"
    HAZARDOUS = "HAZARDOUS"
    OTHER = "OTHER"


class ProcessingMethod(str, enum.Enum):
    """OPEN DESIGN DECISION: taxonomy not specified by the brief; confirm/adjust before Step 2."""
    COMPOSTING = "COMPOSTING"
    RECYCLING = "RECYCLING"
    MATERIAL_RECOVERY = "MATERIAL_RECOVERY"
    INCINERATION = "INCINERATION"
    LANDFILL = "LANDFILL"
    OTHER = "OTHER"


class HandoffStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DispositionType(str, enum.Enum):
    """OPEN DESIGN DECISION: taxonomy not specified by the brief; confirm/adjust before Step 2."""
    LANDFILL = "LANDFILL"
    RECYCLING = "RECYCLING"
    COMPOSTING = "COMPOSTING"
    INCINERATION = "INCINERATION"
    WASTE_TO_ENERGY = "WASTE_TO_ENERGY"
    OTHER = "OTHER"


class DispositionStatus(str, enum.Enum):
    RECORDED = "RECORDED"     # entered by facility/admin
    VERIFIED = "VERIFIED"     # confirmed independently (e.g. weighbridge slip at the terminal site)
    CANCELLED = "CANCELLED"   # entered in error


class DisposalExceptionStatus(str, enum.Enum):
    RAISED = "RAISED"                             # exception opened; awaiting a decision
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"  # an alternative destination has been proposed
    AUTHORIZED = "AUTHORIZED"                      # alternative destination approved; reroute may proceed
    REJECTED = "REJECTED"                          # no alternative destination was authorized
    RESOLVED = "RESOLVED"                          # the rerouted handoff/disposition completed the load's path
    CANCELLED = "CANCELLED"                        # opened in error / superseded


class Facility(Base):  # +  needed for receiving_records.facility_id
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(60))
    location = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=True)
    __table_args__ = (Index("idx_facilities_location", "location", postgresql_using="gist"),)


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # Plain integer (no FK): routes.worker_id already carries the FK; avoids a circular FK.
    assigned_route_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AuthorityQueue(Base):
    """A municipal team/queue that sanitation tickets are routed to."""
    __tablename__ = "authority_queues"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(255), default="")


class Ward(Base):
    """Ward boundary polygon. The default dataset is SYNTHETIC DEMO DATA - see source_label / is_official."""
    __tablename__ = "wards"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    boundary = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False)
    queue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("authority_queues.id"))
    source_name: Mapped[str] = mapped_column(String(120))
    source_label: Mapped[str] = mapped_column(String(255))
    source_version: Mapped[str] = mapped_column(String(60), default="")
    is_official: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("idx_wards_boundary", "boundary", postgresql_using="gist"),)


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ward: Mapped[str] = mapped_column(String(64))  # legacy display label, kept in sync with ward_id by geo.assign_wards
    worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"))
    ward_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wards.id"), index=True)
    path = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=False), nullable=True)
    __table_args__ = (Index("idx_routes_path", "path", postgresql_using="gist"),)


class Household(Base):
    __tablename__ = "households"
    id: Mapped[int] = mapped_column(primary_key=True)
    ward: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[Optional[int]] = mapped_column(ForeignKey("routes.id"))
    address: Mapped[str] = mapped_column(String(255))
    owner_name: Mapped[str] = mapped_column(String(120), default="")   # +
    civic_credits: Mapped[int] = mapped_column(Integer, default=0)      # +  SEEDED, static
    ward_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wards.id"), index=True)
    location = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=True)
    __table_args__ = (Index("idx_households_location", "location", postgresql_using="gist"),)


class User(Base):  # +  JWT auth with 4 roles and facility capabilities
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    name: Mapped[str] = mapped_column(String(120))
    capability: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, default=None)  # e.g. RECEIVING, PROCESSING, INDEPENDENT_VERIFIER
    worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"))
    household_id: Mapped[Optional[int]] = mapped_column(ForeignKey("households.id"))
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facilities.id"))


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(primary_key=True)
    registration_number: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. "MH-01-AB-1234"
    vehicle_type: Mapped[str] = mapped_column(String(60), default="COMPACTOR")  # e.g. "COMPACTOR", "TIPPER", "ELECTRIC_LCV"
    capacity_kg: Mapped[int] = mapped_column(Integer, default=5000)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    assigned_ward: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class CollectionTrip(Base):
    __tablename__ = "collection_trips"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_code: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. "CT-2026-0041"
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"))
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="IN_PROGRESS")  # IN_PROGRESS, VERIFICATION_PAUSED, COMPLETED
    verification_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_paused_at_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    receiving_facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facilities.id"), nullable=True)


class TripCrew(Base):
    __tablename__ = "trip_crews"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("collection_trips.id"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    role_in_crew: Mapped[str] = mapped_column(String(60), default="COLLECTOR")  # CREW_LEAD, DRIVER, COLLECTOR


class DigitalLoad(Base):
    __tablename__ = "digital_loads"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. "DL-1002"
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"))
    trip_id: Mapped[Optional[int]] = mapped_column(ForeignKey("collection_trips.id"), nullable=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    receiving_facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[LoadStatus] = mapped_column(Enum(LoadStatus, name="load_status"), default=LoadStatus.COLLECTING)
    declared_quantity_kg: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # +  worker's load summary


class CollectionEvent(Base):
    __tablename__ = "collection_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"))
    load_id: Mapped[Optional[str]] = mapped_column(ForeignKey("digital_loads.id"))  # +  links event to its load
    status: Mapped[CollectionStatus] = mapped_column(Enum(CollectionStatus, name="collection_status"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReceivingRecord(Base):
    __tablename__ = "receiving_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    quantity: Mapped[int] = mapped_column(Integer)  # kg
    condition: Mapped[Condition] = mapped_column(Enum(Condition, name="receiving_condition"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # WHO recorded the facility signal - needed to enforce independence (an auditor must not be this person)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class DiscrepancyEvent(Base):
    __tablename__ = "discrepancy_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    type: Mapped[DiscrepancyType] = mapped_column(Enum(DiscrepancyType, name="discrepancy_type"))
    status: Mapped[DiscrepancyStatus] = mapped_column(
        Enum(DiscrepancyStatus, name="discrepancy_status"), default=DiscrepancyStatus.FLAGGED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # +  snapshots of both signals, evidence, audit result, resolution
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)


class EventLog(Base):
    """Hash-chained, per-load. hash = sha256(json.dumps(payload, sort_keys=True) + prev_hash)."""
    __tablename__ = "event_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    # A chain is one independent hash chain. For Digital Loads chain_id == load_id (unchanged behaviour);
    # other entities use their own key, e.g. "SR-12" for a sanitation ticket. Same table, same hash function.
    chain_id: Mapped[str] = mapped_column(String(40))
    load_id: Mapped[Optional[str]] = mapped_column(ForeignKey("digital_loads.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload_json: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        Index("ix_event_log_load_id_id", "load_id", "id"),
        Index("ix_event_log_chain_id_id", "chain_id", "id"),
        CheckConstraint("load_id IS NULL OR chain_id = load_id", name="ck_event_log_chain_matches_load"),
    )


class SanitationReport(Base):
    """A citizen sanitation report = a ticket. Location is a PostGIS geography point (device-reported, unverified)."""
    __tablename__ = "sanitation_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    legacy_ward_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # pre-PostGIS value, read-only
    description: Mapped[str] = mapped_column(Text)
    issue_type: Mapped[IssueType] = mapped_column(Enum(IssueType, name="issue_type"), default=IssueType.OTHER, server_default="OTHER")
    photo_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # real photo upload arrives in Phase 2
    location = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=True)
    location_source: Mapped[str] = mapped_column(String(30), default="DEVICE_REPORTED", server_default="DEVICE_REPORTED")
    location_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    location_accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus, name="ticket_status"), default=TicketStatus.SUBMITTED, server_default="SUBMITTED")
    ward_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wards.id"))
    queue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("authority_queues.id"))
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("idx_sanitation_reports_location", "location", postgresql_using="gist"),
        Index("ix_sanitation_reports_ward_status", "ward_id", "status"),
    )


class SanitationRoutingDecision(Base):
    """Every routing decision (automatic or manual) is stored; the newest one is the report's current routing."""
    __tablename__ = "sanitation_routing_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("sanitation_reports.id"), index=True)
    outcome: Mapped[RoutingOutcome] = mapped_column(Enum(RoutingOutcome, name="routing_outcome"))
    method: Mapped[str] = mapped_column(String(40))  # POINT_IN_POLYGON | MANUAL_OVERRIDE
    ward_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wards.id"))
    queue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("authority_queues.id"))
    reason: Mapped[str] = mapped_column(String(255), default="")
    boundary_source: Mapped[Optional[str]] = mapped_column(String(120))
    boundary_is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))  # NULL = automatic
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"))  # the hash-chained audit event


# =============================================================================== Phase 2: evidence + audits
class Evidence(Base):
    """One evidence item. The bytes live in EvidenceStorage; only an opaque key is stored here, and it is never
    returned by the API. There is intentionally no delete/update endpoint (see README: retention)."""
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(40), unique=True)   # what the API exposes, e.g. "ev_3f9c..."
    kind: Mapped[EvidenceKind] = mapped_column(Enum(EvidenceKind, name="evidence_kind"))
    side: Mapped[EvidenceSide] = mapped_column(Enum(EvidenceSide, name="evidence_side"))
    category: Mapped[Optional[EvidenceCategory]] = mapped_column(Enum(EvidenceCategory, name="evidence_category"), nullable=True)
    provenance: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)  # RANDOM_AUDIT, NEGATIVE_EVENT, INDEPENDENT_AUDIT
    load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    collection_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("collection_events.id"), nullable=True)
    household_id: Mapped[Optional[int]] = mapped_column(ForeignKey("households.id"), nullable=True)
    discrepancy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("discrepancy_events.id"), nullable=True)
    audit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audits.id"), nullable=True)
    uploader_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploader_actor: Mapped[str] = mapped_column(String(60))           # e.g. "worker:3" - snapshot for provenance
    uploader_role: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)   # sanitised, display only
    media_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)           # DETECTED from bytes
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    storage_backend: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    location = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=True)
    location_source: Mapped[str] = mapped_column(String(30), default="DEVICE_REPORTED", server_default="DEVICE_REPORTED")
    location_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    location_accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"), nullable=True)   # the hash-chained audit event
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("(kind = 'FILE_EVIDENCE') = (storage_key IS NOT NULL AND sha256 IS NOT NULL)", name="ck_evidence_file_iff_stored"),
        CheckConstraint("location_verified = false", name="ck_evidence_gps_never_verified"),
        Index("ix_evidence_load_id", "load_id"),
        Index("ix_evidence_discrepancy_id", "discrepancy_id"),
        Index("ix_evidence_audit_id", "audit_id"),
        Index("ix_evidence_sha256", "sha256"),
        Index("idx_evidence_location", "location", postgresql_using="gist"),
    )


class AuditSelectionRun(Base):
    """One execution of the selection engine, kept so a selection can be explained and reproduced afterwards."""
    __tablename__ = "audit_selection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    method: Mapped[AuditMethod] = mapped_column(Enum(AuditMethod, name="audit_method"))
    seed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON)          # the exact configuration used (incl. per-run overrides)
    eligible_count: Mapped[int] = mapped_column(Integer)
    selected_count: Mapped[int] = mapped_column(Integer)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)   # every candidate with score/explanation, selected or not
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class Audit(Base):
    __tablename__ = "audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[AuditTargetType] = mapped_column(
        Enum(AuditTargetType, name="audit_target_type"),
        default=AuditTargetType.DIGITAL_LOAD,
        server_default="DIGITAL_LOAD",
    )
    load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    collection_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("collection_events.id"), nullable=True)
    household_id: Mapped[Optional[int]] = mapped_column(ForeignKey("households.id"), nullable=True)
    worker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("workers.id"), nullable=True)      # responsible worker (snapshot)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)   # worker user who executed collection
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facilities.id"), nullable=True) # receiving facility (snapshot)
    method: Mapped[AuditMethod] = mapped_column(Enum(AuditMethod, name="audit_method"))
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_factors: Mapped[dict] = mapped_column(JSON, default=dict)
    selection_reason: Mapped[str] = mapped_column(Text)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audit_selection_runs.id"), nullable=True)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    selected_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # NULL = the engine
    status: Mapped[AuditStatus] = mapped_column(Enum(AuditStatus, name="audit_status"), default=AuditStatus.PENDING)
    auditor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint("length(selection_reason) >= 10", name="ck_audits_reason_recorded"),   # never selected silently
        Index("ix_audits_load_id", "load_id"),
        Index("ix_audits_status", "status"),
        # at most one OPEN audit per load
        Index("uq_audits_one_open_per_load", "load_id", unique=True, postgresql_where=text("status IN ('PENDING','IN_PROGRESS')")),
    )


class AuditCorroboration(Base):
    """The Cross-Check decision for (audit, discrepancy): accepted or rejected, and why. Never an attribution."""
    __tablename__ = "audit_corroborations"
    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id"))
    discrepancy_id: Mapped[int] = mapped_column(ForeignKey("discrepancy_events.id"))
    outcome: Mapped[CorroborationOutcome] = mapped_column(Enum(CorroborationOutcome, name="corroboration_outcome"))
    reason_code: Mapped[str] = mapped_column(String(60))
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    evaluated_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"), nullable=True)
    __table_args__ = (UniqueConstraint("audit_id", "discrepancy_id", name="uq_audit_corroborations_pair"),)


# =============================================================================== Phase 3: post-receiving pipeline
# ARCHITECTURE DECISION - post-receiving status:
#   digital_loads.status (LoadStatus) is left completely unchanged: COLLECTING -> DECLARED -> VERIFIED/DISPUTED
#   -> SETTLED still means exactly what it meant in Phase 1/2 (has the load's declared-vs-received cross-check
#   settled?). Altering that Postgres enum in place (ALTER TYPE ... ADD VALUE) is a real risk to every existing
#   read of load.status, to the 182 Phase 0-2 tests, and to autogenerate/`alembic check` drift detection - and
#   it isn't necessary. Instead, "where is this load in the post-receiving pipeline?" is answered by which of
#   the four tables below exist for it and what THEIR OWN status is: no ProcessingRecord yet = not started;
#   a ProcessingRecord.status of COMPLETED + a Handoff.status of COMPLETED + >=1 FinalDisposition row = done.
#   A load can be VERIFIED/SETTLED (Phase 1/2 sense) and simultaneously anywhere in this second, independent
#   pipeline (Phase 3 sense) - the two statuses answer different questions and are not meant to be merged.
#   Deriving a single combined "pipeline stage" label for the API/UI is explicitly deferred to a later step.
#
# Reuses (no new audit/hash system): users, facilities, digital_loads, event_log + hashchain.append_event.
# Every state-changing action here gets an `event_id` FK to event_log, exactly like Evidence/Audit/
# AuditCorroboration in Phase 2, so a future service layer can call append_event() and store the row's id -
# the column exists now so no further migration is needed to wire that in.
class ProcessingRecord(Base):
    """A facility processing a load's material (composting, recycling, MRF sorting, ...). One load may have
    more than one ProcessingRecord over time (e.g. reprocessing), so this is a many-per-load table."""
    __tablename__ = "processing_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    digital_load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    waste_stream: Mapped[WasteStream] = mapped_column(Enum(WasteStream, name="waste_stream"))
    processing_method: Mapped[ProcessingMethod] = mapped_column(Enum(ProcessingMethod, name="processing_method"))
    processed_quantity_kg: Mapped[int] = mapped_column(Integer)
    recovered_quantity_kg: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    residual_quantity_kg: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[ProcessingStatus] = mapped_column(Enum(ProcessingStatus, name="processing_status"), default=ProcessingStatus.PENDING)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"), nullable=True)
    __table_args__ = (
        CheckConstraint("processed_quantity_kg > 0", name="ck_processing_records_processed_qty_positive"),
        CheckConstraint("recovered_quantity_kg >= 0", name="ck_processing_records_recovered_qty_non_negative"),
        CheckConstraint("residual_quantity_kg >= 0", name="ck_processing_records_residual_qty_non_negative"),
        # mass out cannot exceed mass in (moisture loss etc. can make it less; it can never be more)
        CheckConstraint("recovered_quantity_kg + residual_quantity_kg <= processed_quantity_kg",
                        name="ck_processing_records_output_within_input"),
        CheckConstraint("status <> 'COMPLETED' OR completed_at IS NOT NULL", name="ck_processing_records_completed_has_timestamp"),
        Index("ix_processing_records_load_id", "digital_load_id"),
        Index("ix_processing_records_facility_id", "facility_id"),
        Index("ix_processing_records_status", "status"),
        # at most one OPEN (PENDING/IN_PROGRESS) processing record per load, same pattern as audits
        Index("uq_processing_records_one_open_per_load", "digital_load_id", unique=True,
              postgresql_where=text("status IN ('PENDING','IN_PROGRESS')")),
    )


class Handoff(Base):
    """One physical transfer of (part of) a load's material between two facilities. Optionally tied to the
    ProcessingRecord it followed. A Handoff created to fulfil an authorized DisposalException is identified
    from the DisposalException side (disposal_exceptions.resulting_handoff_id), not from here - see the note
    on DisposalException for why the link is one-directional."""
    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    digital_load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    processing_record_id: Mapped[Optional[int]] = mapped_column(ForeignKey("processing_records.id"), nullable=True)
    source_facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    destination_facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    quantity_kg: Mapped[int] = mapped_column(Integer)
    waste_stream: Mapped[WasteStream] = mapped_column(Enum(WasteStream, name="waste_stream"))
    status: Mapped[HandoffStatus] = mapped_column(Enum(HandoffStatus, name="handoff_status"), default=HandoffStatus.PENDING)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"), nullable=True)
    __table_args__ = (
        CheckConstraint("quantity_kg > 0", name="ck_handoffs_qty_positive"),
        CheckConstraint("source_facility_id <> destination_facility_id", name="ck_handoffs_source_ne_destination"),
        Index("ix_handoffs_load_id", "digital_load_id"),
        Index("ix_handoffs_processing_record_id", "processing_record_id"),
        Index("ix_handoffs_status", "status"),
        # at most one OPEN (PENDING/IN_TRANSIT) handoff per load
        Index("uq_handoffs_one_open_per_load", "digital_load_id", unique=True,
              postgresql_where=text("status IN ('PENDING','IN_TRANSIT')")),
    )


class FinalDisposition(Base):
    """Where a load's material ultimately ended up. Many-per-load on purpose: a ProcessingRecord can split a
    load into a recovered stream and a residual stream, and each can end at a different terminal destination
    (e.g. recovered -> a recycler, residual -> a landfill), so this is not forced to one row per load."""
    __tablename__ = "final_dispositions"
    id: Mapped[int] = mapped_column(primary_key=True)
    digital_load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    handoff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("handoffs.id"), nullable=True)
    processing_record_id: Mapped[Optional[int]] = mapped_column(ForeignKey("processing_records.id"), nullable=True)
    disposition_type: Mapped[DispositionType] = mapped_column(Enum(DispositionType, name="disposition_type"))
    destination_facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    quantity_kg: Mapped[int] = mapped_column(Integer)
    status: Mapped[DispositionStatus] = mapped_column(Enum(DispositionStatus, name="disposition_status"), default=DispositionStatus.RECORDED)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    recorded_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"), nullable=True)
    __table_args__ = (
        CheckConstraint("quantity_kg > 0", name="ck_final_dispositions_qty_positive"),
        Index("ix_final_dispositions_load_id", "digital_load_id"),
        Index("ix_final_dispositions_handoff_id", "handoff_id"),
        Index("ix_final_dispositions_processing_record_id", "processing_record_id"),
        Index("ix_final_dispositions_status", "status"),
    )


class DisposalException(Base):
    """Raised when a load cannot go to its intended destination from Processing or a Handoff. Points back to
    whichever ONE stage triggered it (never both), and forward to the Handoff created once an alternative
    destination is authorized. That forward link (resulting_handoff_id) is deliberately one-directional -
    Handoff does not carry a reference back to the exception that produced it - so that handoffs/disposal_
    exceptions have no circular foreign-key dependency at table-creation time; the exception row is always
    created first (it is the cause), the rerouted Handoff second (it is the effect), and this row is updated
    with the new handoff's id once it exists."""
    __tablename__ = "disposal_exceptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    digital_load_id: Mapped[str] = mapped_column(ForeignKey("digital_loads.id"))
    source_processing_record_id: Mapped[Optional[int]] = mapped_column(ForeignKey("processing_records.id"), nullable=True)
    source_handoff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("handoffs.id"), nullable=True)
    original_destination_facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[DisposalExceptionStatus] = mapped_column(Enum(DisposalExceptionStatus, name="disposal_exception_status"),
                                                              default=DisposalExceptionStatus.RAISED)
    alternative_destination_facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facilities.id"), nullable=True)
    resulting_handoff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("handoffs.id"), nullable=True)
    raised_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    authorized_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("event_log.id"), nullable=True)
    __table_args__ = (
        CheckConstraint("length(reason) >= 10", name="ck_disposal_exceptions_reason_recorded"),  # never raised silently
        # exactly one triggering stage - never both, never neither
        CheckConstraint(
            "(CASE WHEN source_processing_record_id IS NOT NULL THEN 1 ELSE 0 END) "
            "+ (CASE WHEN source_handoff_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_disposal_exceptions_one_source"),
        CheckConstraint(
            "alternative_destination_facility_id IS NULL OR alternative_destination_facility_id <> original_destination_facility_id",
            name="ck_disposal_exceptions_alt_ne_original"),
        # an AUTHORIZED or RESOLVED exception must have an alternative destination on record
        CheckConstraint(
            "status NOT IN ('AUTHORIZED','RESOLVED') OR alternative_destination_facility_id IS NOT NULL",
            name="ck_disposal_exceptions_authorized_has_alt_destination"),
        UniqueConstraint("resulting_handoff_id", name="uq_disposal_exceptions_resulting_handoff"),
        Index("ix_disposal_exceptions_load_id", "digital_load_id"),
        Index("ix_disposal_exceptions_status", "status"),
        # at most one OPEN (RAISED/PENDING_AUTHORIZATION) exception per load
        Index("uq_disposal_exceptions_one_open_per_load", "digital_load_id", unique=True,
              postgresql_where=text("status IN ('RAISED','PENDING_AUTHORIZATION')")),
    )
