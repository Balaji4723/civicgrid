export type Role = "CITIZEN" | "WORKER" | "FACILITY" | "MUNICIPAL_ADMIN";
export type DiscStatus = "FLAGGED" | "EVIDENCE_PENDING" | "CORROBORATED" | "INVESTIGATING" | "RESOLVED" | "CLOSED";
export const DISC_STATUSES: DiscStatus[] = ["FLAGGED", "EVIDENCE_PENDING", "CORROBORATED", "INVESTIGATING", "RESOLVED", "CLOSED"];

export interface User { id: number; username: string; name: string; role: Role; worker_id: number | null; household_id: number | null; facility_id: number | null; capability?: string | null }

export interface Declaration { source: string; households_collected: number; segregated: number; unsegregated: number; stream: string; quantity: number | null }
export interface Signal { source: string; quantity: number | null; condition: string | null; auditor?: string; verdict?: string }

export interface Discrepancy {
  id: number; load_id: string; type: "QUANTITY" | "STREAM"; status: DiscStatus;
  created_at: string; resolved_at: string | null; next_action: string | null;
  details: {
    declaration: Declaration; receiving: Signal; audit: Signal | null;
    evidence: { note: string; evidence_ref: string | null; by: string; at: string }[];
    resolution: { finding: string; attributed_to: string; by: string; at: string } | null;
    closing_note: string | null; investigation_note?: string | null;
  };
  trail?: LogEvent[];
}

export interface Vehicle {
  id: number;
  registration_number: string;
  vehicle_type: string;
  capacity_kg: number;
}

export interface CollectionTrip {
  id: number;
  trip_code: string;
  status: string;
  verification_triggered: boolean;
  verification_acknowledged: boolean;
  verification_paused: boolean;
  verification_paused_at_count?: number | null;
}

export interface CrewMember {
  id: number;
  name: string;
  role: string;
}

export interface LoadRow {
  id: string;
  route_id: number;
  ward: string;
  worker: string | null;
  trip_id?: number | null;
  trip_code?: string | null;
  vehicle_id?: number | null;
  vehicle_registration?: string | null;
  vehicle_type?: string | null;
  status: string;
  generated_at: string;
  declared_quantity_kg: number | null;
  discrepancy_count: number;
}

export interface LoadDetail extends LoadRow {
  vehicle?: Vehicle | null;
  trip?: CollectionTrip | null;
  crew?: CrewMember[];
  declaration: Declaration;
  receiving: { id: number; facility_id: number; quantity: number; condition: string; timestamp: string } | null;
  discrepancies: Discrepancy[];
  event_count: number;
  head_hash: string | null;
}
export interface LogEvent { index: number; id: number; load_id: string; event_type: string; payload: Record<string, unknown>; prev_hash: string; hash: string; created_at: string }
export interface Integrity { load_id: string; valid: boolean; broken_at_index: number | null; broken_event_id: number | null; reason: string | null; total_events: number; head_hash: string }

// ---------------------------------------------------------------- Phase 1: geo + sanitation
export type TicketStatus = "SUBMITTED" | "ROUTED" | "UNROUTABLE" | "IN_PROGRESS" | "RESOLVED";
export const ISSUE_TYPES = ["OVERFLOWING_BIN", "ILLEGAL_DUMPING", "BLOCKED_DRAIN", "MISSED_COLLECTION", "OTHER"] as const;
export type IssueType = (typeof ISSUE_TYPES)[number];
export const ISSUE_LABEL: Record<IssueType, string> = {
  OVERFLOWING_BIN: "Overflowing bin", ILLEGAL_DUMPING: "Illegal dumping", BLOCKED_DRAIN: "Blocked drain",
  MISSED_COLLECTION: "Missed collection", OTHER: "Other",
};

export interface WardFeature {
  type: "Feature"; geometry: GeoJSON.Geometry;
  properties: { id: number; code: string; name: string; queue_code: string | null; queue_name: string | null; source_label: string; is_official: boolean; source_name: string; source_version: string };
}
export interface WardCollection {
  type: "FeatureCollection"; features: WardFeature[];
  source: { label: string; all_official: boolean; sources: { name: string; label: string; version: string; is_official: boolean; ward_count: number }[] };
}
export interface WardLookup {
  outcome: "ROUTABLE" | "OUTSIDE_ALL_WARDS" | "AMBIGUOUS_OR_NO_QUEUE";
  ward: { id: number; code: string; name: string; queue: { id: number; code: string; name: string } | null; source_label: string; is_official: boolean } | null;
  wards: { code: string }[];
}
export interface Ticket {
  id: number; issue_type: IssueType; description: string; status: TicketStatus; photo_name: string | null;
  created_at: string; updated_at: string | null; resolution_note: string | null; chain_id: string;
  ward: { id: number; code: string; name: string; source_label: string; is_official: boolean } | null;
  queue: { id: number; code: string; name: string } | null;
  location: { latitude: number; longitude: number; source: string; verified: boolean; accuracy_m: number | null; note: string } | null;
  routing?: RoutingDecision;
  routing_history?: RoutingDecision[];
}
export interface RoutingDecision {
  id: number; outcome: "ROUTED" | "UNROUTABLE"; method: string; reason: string; ward: string | null; queue: string | null;
  boundary_source: string | null; boundary_is_official: boolean; decided_by_user_id: number | null; decided_at: string; event_id: number | null; candidates?: string[] | null;
}
export interface QueueSummary { id: number | null; code: string; name: string; counts: Partial<Record<TicketStatus, number>> }
export interface FacilityCollection { type: "FeatureCollection"; features: { geometry: GeoJSON.Point; properties: { id: number; name: string; kind: string } }[] }

// ---------------------------------------------------------------- Phase 2: evidence + audits
export type EvidenceKind = "FILE_EVIDENCE" | "AUDIT_RESULT" | "NOTE";
export type EvidenceSide = "WORKER" | "FACILITY" | "NEUTRAL";
export const EVIDENCE_CATEGORIES = ["LOAD_PHOTO", "WEIGHBRIDGE_SLIP", "VIDEO_WALKTHROUGH", "AUDIT_OBSERVATION", "OTHER"] as const;
export interface EvidenceItem {
  id: string; kind: EvidenceKind; side: EvidenceSide; category: string | null;
  provenance?: string | null; household_id?: number | null; collection_event_id?: number | null;
  load_id: string; discrepancy_id: number | null; audit_id: number | null;
  uploader: { actor: string; name: string | null; role: string | null }; created_at: string; description: string;
  filename: string | null; media_type: string | null; size_bytes: number | null; sha256: string | null; content_url: string | null;
  gps: { latitude: number; longitude: number; accuracy_m: number | null; source: string; verified: false; label: string } | null;
  duplicate_of: string | null; audit_event_id: number | null; evidence_backed: boolean;
  independence: { independent: boolean; reasons: string[] };
}
export interface IndependenceAudit {
  audit_id: number; status: string; method: string; auditor: string | null; auditor_role: string | null; independent: boolean | null;
  violations: { code: string; message: string }[]; overall: string | null; evaluated: { outcome: string; reason_code: string } | null;
}
export interface CaseView {
  evidence: EvidenceItem[]; evidence_mode: "FILE_BACKED" | "LEGACY_NOTE_ONLY" | "NONE";
  evidence_summary: { files: number; notes: number; independent_files: number };
  corroboration_path: string | null; corroboration_evidence_backed: boolean; require_file_evidence: boolean;
  independence: {
    principle: string;
    parties: { worker: { id: number | null; name: string | null }; facility_recorder: { user_id: number | null; name: string | null }; receiving_facility: { id: number | null; name: string | null } };
    audits: IndependenceAudit[];
  };
}
export interface EvidenceConfig { require_file_evidence: boolean; max_image_bytes: number; max_video_bytes: number; allowed_types: Record<string, string[]>; gps_note: string }

export type AuditTargetType = "COLLECTION_EVENT" | "DIGITAL_LOAD";
export type AuditMethod = "RANDOM" | "RISK_BASED" | "MANUAL";
export type AuditStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export interface RiskFactor { key: string; label: string; raw: number; raw_text: string; cap: number; normalised: number; weight: number; weight_share: number; contribution: number; explanation: string }
export interface AuditRow {
  id: number; target_type?: AuditTargetType; household_id?: number | null; collection_event_id?: number | null;
  load_id: string; ward: string | null; worker: string | null; actor?: { id?: number; name?: string; role?: string } | null;
  facility: string | null; method: AuditMethod; risk_score: number | null;
  selection_reason: string; run_id: number | null; selected_at: string; selected_by: string; status: AuditStatus;
  auditor: { id: number; name: string; role: string } | null; started_at: string | null; completed_at: string | null;
  discrepancies: { id: number; type: string; status: DiscStatus }[];
  evidence_status: { files: number; independent_files: number; has_result: boolean }; result_overall: string | null;
  can_conduct: boolean | null; independence_violations: { code: string; message: string }[] | null;
}
export interface AuditDetail extends AuditRow {
  risk_factors: RiskFactor[]; cancel_reason: string | null; declaration: Declaration;
  receiving: { quantity: number; condition: string; facility: string | null } | null;
  result: { quantity: number; condition: string; observations: string; verdicts: Record<string, string>; overall: string; requires_followup: boolean; evidence_ids: string[] } | null;
  run: { id: number; method: string; seed: number | null; eligible_count: number; selected_count: number; config: AuditConfig; executed_at: string } | null;
  corroborations: { discrepancy_id: number; outcome: string; reason_code: string; evaluated_at: string }[];
}
export interface AuditConfig { random_sample_pct: number; risk_threshold: number; risk_max_selected: number; cooldown_days: number; lookback_days: number; weights: Record<string, number>; caps: Record<string, number> }
export interface SelectionResult {
  method: AuditMethod; dry_run: boolean; seed: number | null; config: AuditConfig; eligible_count: number; selected_count: number; run_id: number | null;
  candidates: { load_id: string; selected: boolean; risk_score: number | null; top_factors?: string[]; factors?: RiskFactor[] }[]; audits: AuditRow[];
}
export interface WorkerEvidenceRequest { load_id: string; discrepancy_id: number; type: string; status: string; accepting_evidence: boolean; my_files: number; audit: { id: number; status: string; method: string } | null }

// ---------------------------------------------------------------- Phase 3: processing / handoff / final disposition / disposal exception
export type ProcessingStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export type WasteStream = "ORGANIC" | "RECYCLABLE" | "MIXED" | "RESIDUAL" | "RECOVERED" | "HAZARDOUS" | "OTHER";
export type ProcessingMethod = "COMPOSTING" | "RECYCLING" | "MATERIAL_RECOVERY" | "INCINERATION" | "LANDFILL" | "OTHER";
export type HandoffStatus = "PENDING" | "IN_TRANSIT" | "COMPLETED" | "CANCELLED";
export type DispositionType = "LANDFILL" | "RECYCLING" | "COMPOSTING" | "INCINERATION" | "WASTE_TO_ENERGY" | "OTHER";
export type DispositionStatus = "RECORDED" | "VERIFIED" | "CANCELLED";
export type DisposalExceptionStatus = "RAISED" | "PENDING_AUTHORIZATION" | "AUTHORIZED" | "REJECTED" | "RESOLVED" | "CANCELLED";

export const WASTE_STREAMS: WasteStream[] = ["ORGANIC", "RECYCLABLE", "MIXED", "RESIDUAL", "RECOVERED", "HAZARDOUS", "OTHER"];
export const PROCESSING_METHODS: ProcessingMethod[] = ["COMPOSTING", "RECYCLING", "MATERIAL_RECOVERY", "INCINERATION", "LANDFILL", "OTHER"];
export const DISPOSITION_TYPES: DispositionType[] = ["LANDFILL", "RECYCLING", "COMPOSTING", "INCINERATION", "WASTE_TO_ENERGY", "OTHER"];

export interface ProcessingRecord {
  id: number; digital_load_id: string; facility_id: number; facility: string | null; waste_stream: WasteStream; processing_method: ProcessingMethod;
  processed_quantity_kg: number; recovered_quantity_kg: number; residual_quantity_kg: number; status: ProcessingStatus;
  started_at: string | null; completed_at: string | null; recorded_by: string | null; notes: string; created_at: string; event_id: number | null;
}
export interface Handoff {
  id: number; digital_load_id: string; processing_record_id: number | null; source_facility_id: number; source_facility: string | null;
  destination_facility_id: number; destination_facility: string | null; quantity_kg: number; waste_stream: WasteStream; status: HandoffStatus;
  timestamp: string | null; recorded_by: string | null; notes: string; created_at: string; event_id: number | null;
}
export interface FinalDisposition {
  id: number; digital_load_id: string; handoff_id: number | null; processing_record_id: number | null; disposition_type: DispositionType;
  destination_facility_id: number; destination_facility: string | null; quantity_kg: number; status: DispositionStatus;
  timestamp: string | null; recorded_by: string | null; notes: string; created_at: string; event_id: number | null;
}
export interface DisposalException {
  id: number; digital_load_id: string; source_processing_record_id: number | null; source_handoff_id: number | null;
  original_destination_facility_id: number; original_destination_facility: string | null; reason: string; status: DisposalExceptionStatus;
  alternative_destination_facility_id: number | null; alternative_destination_facility: string | null; resulting_handoff_id: number | null;
  raised_by: string | null; authorized_by: string | null; authorized_at: string | null; resolved_at: string | null; created_at: string; event_id: number | null;
}
export interface LoadTimeline {
  load_id: string; load_status: string; events: LogEvent[];
  processing_records: ProcessingRecord[]; handoffs: Handoff[]; final_dispositions: FinalDisposition[]; disposal_exceptions: DisposalException[];
}
