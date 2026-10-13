"use client";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Award,
  Calendar,
  Camera,
  Check,
  CheckCircle2,
  Clock,
  Coins,
  History,
  LocateFixed,
  Package,
  PackageCheck,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Truck,
  Users,
} from "lucide-react";
import { api, ApiError, apiUpload } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import type { LoadRow } from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Kpi,
  LoadBadge,
  Notice,
  Spinner,
  StatusBadge,
  Table,
} from "@/components/ui";
import { Shell } from "@/components/Shell";
import { CameraCapture, type CaptureResult } from "@/components/CameraCapture";
import { cleanLabel } from "@/lib/nav";

interface RouteView {
  worker: { id: number; name: string };
  route: { id: number; ward: string };
  trip?: {
    id: number;
    trip_code: string;
    status: string;
    verification_triggered: boolean;
    verification_acknowledged: boolean;
    verification_paused: boolean;
    verification_paused_at_count?: number | null;
    verification_target?: {
      audit_id?: number | null;
      audit_code?: string;
      household_id: number;
      household_label: string;
      address: string;
      recorded_status: string;
      selection_reason: string;
    } | null;
  } | null;
  vehicle?: {
    id: number;
    registration_number: string;
    vehicle_type: string;
    capacity_kg: number;
  } | null;
  crew?: { id: number; name: string; role: string }[];
  active_load: LoadRow | null;
  households: {
    id: number;
    address: string;
    owner_name: string;
    status: "PENDING" | "SEGREGATED" | "UNSEGREGATED";
    audit_selected?: boolean;
    audit_reason?: string | null;
    marked_at: string | null;
  }[];
}

interface WorkerHistoryItem {
  id: number;
  trip_code: string;
  date: string;
  end_time: string | null;
  ward: string;
  vehicle_registration: string;
  vehicle_type: string;
  households_serviced: number;
  segregated: number;
  unsegregated: number;
  random_audits: number;
  evidence_count: number;
  status: string;
  load_id: string | null;
  credits_earned: number;
}

interface WorkerIntegrityData {
  worker: { id: number; name: string };
  total_credits: number;
  collections_completed: number;
  random_audits_completed: number;
  audit_evidence_compliance_pct: number;
  integrity_events: {
    id: string;
    points: number;
    type: string;
    title: string;
    description: string;
    household_label: string;
    timestamp: string;
  }[];
}

type EvidenceState =
  | { phase: "idle" }
  | { phase: "capture" }
  | { phase: "uploading" }
  | { phase: "done"; capturedAt: string; hasGps: boolean }
  | { phase: "error"; message: string };

type WorkerTab = "collection" | "history" | "integrity";

export default function WorkerPortal() {
  const [activeTab, setActiveTab] = useState<WorkerTab>("collection");
  const { data: rawData, error, reload } = useLoad(() => api<RouteView>("/worker/route"));
  const historyLoad = useLoad(() => api<WorkerHistoryItem[]>("/worker/history"), [], activeTab === "history");
  const integrityLoad = useLoad(() => api<WorkerIntegrityData>("/worker/integrity"), [], activeTab === "integrity");

  const [busyId, setBusyId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [completing, setCompleting] = useState(false);
  const [tripCompleted, setTripCompleted] = useState(false);
  const [completedSnapshot, setCompletedSnapshot] = useState<RouteView | null>(null);
  const [ackBusy, setAckBusy] = useState(false);

  useEffect(() => {
    if (!rawData) return;
    try {
      localStorage.removeItem(`civicgrid_completed_route_${rawData.route.id}`);
    } catch {
      // ignore storage errors
    }
    if (rawData.active_load?.status === "DECLARED" || rawData.trip?.status === "COMPLETED") {
      setCompletedSnapshot(null);
      setTripCompleted(true);
    } else {
      setCompletedSnapshot(null);
      setTripCompleted(false);
    }
  }, [rawData]);

  const data = completedSnapshot ?? rawData;

  // Single active evidence-capture workflow state: at most ONE camera workflow can ever be active
  type ActiveWorkflow =
    | {
        type: "RANDOM_AUDIT";
        householdId: number;
        householdAddress: string;
        pendingStatus: "SEGREGATED" | "UNSEGREGATED";
        loadId?: string | null;
      }
    | {
        type: "NEGATIVE_EVENT";
        householdId: number;
        householdAddress: string;
      }
    | null;

  const [activeWorkflow, setActiveWorkflow] = useState<ActiveWorkflow>(null);

  // Per-household evidence state keyed by household id
  const [evidenceStates, setEvidenceStates] = useState<Record<number, EvidenceState>>({});

  const marked = data?.households.filter((h) => h.status !== "PENDING").length ?? 0;
  const total = data?.households.length ?? 0;
  const progressPct = total > 0 ? Math.round((marked / total) * 100) : 0;
  const isAllMarked = total > 0 && marked === total;

  const segregatedCount = data?.households.filter((h) => h.status === "SEGREGATED").length ?? 0;
  const unsegregatedCount = data?.households.filter((h) => h.status === "UNSEGREGATED").length ?? 0;
  const isTripPaused = Boolean(data?.trip?.verification_paused);

  function setHouseholdEvidence(id: number, state: EvidenceState) {
    setEvidenceStates((prev) => ({ ...prev, [id]: state }));
  }

  /** Normal or Gated Household marking */
  async function initiateMarkHousehold(hh: RouteView["households"][0], status: "SEGREGATED" | "UNSEGREGATED") {
    // If a camera workflow is already active, close it before proceeding
    if (activeWorkflow?.type === "NEGATIVE_EVENT") {
      setActiveWorkflow(null);
    }

    setBusyId(hh.id);
    setErr(null);
    try {
      // Check whether this household requires a Random Audit gate before collection
      const gate = await api<{
        household_id: number;
        household_address: string;
        audit_required: boolean;
        audit_reason?: string | null;
        load_id?: string | null;
      }>("/worker/collections/check-audit", {
        method: "POST",
        body: { household_id: hh.id },
      });

      if (gate.audit_required && (!evidenceStates[hh.id] || evidenceStates[hh.id].phase !== "done")) {
        // Enforce single active workflow: open Random Audit Gate
        setActiveWorkflow({
          type: "RANDOM_AUDIT",
          householdId: hh.id,
          householdAddress: hh.address,
          pendingStatus: status,
          loadId: gate.load_id || data?.active_load?.id,
        });
        return;
      }

      // Normal direct collection recording
      await executeMarkHousehold(hh.id, status, hh.address);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to verify collection gate.");
    } finally {
      setBusyId(null);
    }
  }

  async function executeMarkHousehold(id: number, status: "SEGREGATED" | "UNSEGREGATED", address?: string) {
    setBusyId(id);
    setErr(null);
    try {
      await api("/worker/collections", { method: "POST", body: { household_id: id, status } });
      await reload();
      if (status === "UNSEGREGATED" && (!evidenceStates[id] || evidenceStates[id].phase !== "done")) {
        // Open single active negative-event capture workflow
        setActiveWorkflow({
          type: "NEGATIVE_EVENT",
          householdId: id,
          householdAddress: address || `Flat ${id}`,
        });
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to record collection status.");
    } finally {
      setBusyId(null);
    }
  }

  /** Handles Random Audit photo evidence capture */
  async function handleRandomAuditEvidence(result: CaptureResult) {
    if (!activeWorkflow || activeWorkflow.type !== "RANDOM_AUDIT") return;
    const { householdId, pendingStatus, householdAddress, loadId: gateLoadId } = activeWorkflow;
    const loadId = gateLoadId || data?.active_load?.id;
    if (!loadId) {
      setErr("Active Digital Load required to attach evidence.");
      return;
    }

    setHouseholdEvidence(householdId, { phase: "uploading" });
    try {
      const fd = new FormData();
      fd.append("file", result.file);
      fd.append("provenance", "RANDOM_AUDIT");
      fd.append("category", "LOAD_PHOTO");
      fd.append("household_id", String(householdId));
      fd.append("description", `Point-of-collection random audit photo evidence for household #${householdId}`);
      if (result.gps?.lat != null) fd.append("latitude", String(result.gps.lat));
      if (result.gps?.lng != null) fd.append("longitude", String(result.gps.lng));
      if (result.gps?.accuracy != null) fd.append("accuracy_m", String(result.gps.accuracy));

      await apiUpload(`/loads/${loadId}/evidence`, fd);

      setHouseholdEvidence(householdId, {
        phase: "done",
        capturedAt: new Date().toISOString(),
        hasGps: result.gps != null,
      });

      // Clear active workflow and finalize the collection record
      setActiveWorkflow(null);
      await executeMarkHousehold(householdId, pendingStatus, householdAddress);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Evidence upload failed. Please retry capture.");
      setHouseholdEvidence(householdId, {
        phase: "error",
        message: e instanceof ApiError ? e.message : "Evidence upload failed.",
      });
    }
  }

  /** Negative-event evidence capture (Unsegregated) */
  async function handleNegativeEvidenceCapture(householdId: number, result: CaptureResult) {
    const loadId = data?.active_load?.id;
    if (!loadId) {
      setHouseholdEvidence(householdId, { phase: "error", message: "No active Digital Load found." });
      return;
    }

    setHouseholdEvidence(householdId, { phase: "uploading" });
    try {
      const fd = new FormData();
      fd.append("file", result.file);
      fd.append("provenance", "NEGATIVE_EVENT");
      fd.append("category", "LOAD_PHOTO");
      fd.append("household_id", String(householdId));
      fd.append("description", `Contextual negative-event evidence for unsegregated waste at household #${householdId}`);
      if (result.gps?.lat != null) fd.append("latitude", String(result.gps.lat));
      if (result.gps?.lng != null) fd.append("longitude", String(result.gps.lng));
      if (result.gps?.accuracy != null) fd.append("accuracy_m", String(result.gps.accuracy));

      await apiUpload(`/loads/${loadId}/evidence`, fd);

      setHouseholdEvidence(householdId, {
        phase: "done",
        capturedAt: new Date().toISOString(),
        hasGps: result.gps != null,
      });
      setActiveWorkflow(null);
    } catch (e) {
      setHouseholdEvidence(householdId, {
        phase: "error",
        message: e instanceof ApiError ? e.message : "Failed to upload photo evidence.",
      });
    }
  }

  async function handleAcknowledgeProtocol() {
    setAckBusy(true);
    setErr(null);
    try {
      await api("/worker/trip/acknowledge-verification", { method: "POST", body: {} });
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to acknowledge verification.");
    } finally {
      setAckBusy(false);
    }
  }

  async function handleCompleteCollectionTrip() {
    if (!data || !isAllMarked) {
      setErr("Please record collection status for all assigned households before completing the trip.");
      return;
    }
    if (!data.active_load) return;
    setCompleting(true);
    setErr(null);
    try {
      const sealedLoad = await api<LoadRow>("/worker/trip/complete", {
        method: "POST",
        body: {},
      });
      const snapshot: RouteView = {
        ...data,
        trip: data.trip
          ? {
              ...data.trip,
              status: "COMPLETED",
              verification_paused: false,
            }
          : null,
        active_load: sealedLoad,
      };
      setCompletedSnapshot(snapshot);
      setTripCompleted(true);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to complete collection trip.");
    } finally {
      setCompleting(false);
    }
  }

  const isLoadDeclared = data?.active_load?.status === "DECLARED" || tripCompleted;

  return (
    <Shell
      allow={["WORKER"]}
      accent="track"
      title="Field Worker Portal"
      subtitle={data ? `Assigned Route: ${cleanLabel(data.route.ward)} • Operator: ${data.worker.name}` : "Assigned collection route and household collections"}
    >
      {/* 3 Main Role Tabs: Collection Beat, Worker History, Worker Integrity */}
      <div className="mb-6 flex flex-wrap items-center gap-2 border-b border-line pb-3">
        <button
          type="button"
          onClick={() => setActiveTab("collection")}
          className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-colors ${
            activeTab === "collection"
              ? "bg-track-600 text-white shadow-xs"
              : "bg-paper text-ink-soft hover:bg-paper-subtle hover:text-ink"
          }`}
        >
          <Truck className="h-4 w-4" />
          Active Beat & Collections
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("history")}
          className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-colors ${
            activeTab === "history"
              ? "bg-track-600 text-white shadow-xs"
              : "bg-paper text-ink-soft hover:bg-paper-subtle hover:text-ink"
          }`}
        >
          <History className="h-4 w-4" />
          Worker History
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("integrity")}
          className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-colors ${
            activeTab === "integrity"
              ? "bg-track-600 text-white shadow-xs"
              : "bg-paper text-ink-soft hover:bg-paper-subtle hover:text-ink"
          }`}
        >
          <Award className="h-4 w-4" />
          Worker Integrity & Credits
        </button>
      </div>

      {error && (
        <div className="mb-4">
          <Notice tone="flag" title="Failed to load route data">
            {error}
          </Notice>
        </div>
      )}

      {err && (
        <div className="mb-4">
          <Notice tone="flag" title="Action failed">
            {err}
          </Notice>
        </div>
      )}

      {/* TAB 1: ACTIVE BEAT & COLLECTIONS */}
      {activeTab === "collection" && (
        <>
          {!data && <Spinner label="Loading route information and assigned vehicle" />}

          {data && (
            <div className="space-y-6">
              {/* 4 Summary Cards: Vehicle, Trip, Crew, Progress */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Card>
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-track-50 text-track-700">
                      <Truck className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-ink-soft">Assigned Vehicle</p>
                      <p className="text-base font-bold text-ink">
                        {data.vehicle?.registration_number ?? "MH-01-AB-1234"}
                      </p>
                      <p className="text-[11px] text-ink-soft">
                        {data.vehicle?.vehicle_type ?? "Compactor"} • {data.vehicle?.capacity_kg ?? 5000} kg
                      </p>
                    </div>
                  </div>
                </Card>

                <Card>
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-track-50 text-track-700">
                      <Package className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-ink-soft">Collection Trip</p>
                      <p className="font-mono text-base font-bold text-ink">
                        {data.trip?.trip_code ?? "—"}
                      </p>
                      <p className="text-[11px] text-ink-soft">
                        Status: <span className="font-semibold text-track-700">{isLoadDeclared ? "COMPLETED" : (data.trip?.status ?? "IN_PROGRESS")}</span>
                      </p>
                    </div>
                  </div>
                </Card>

                <Card>
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-track-50 text-track-700">
                      <Users className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-ink-soft">Collection Crew</p>
                      <p className="truncate text-sm font-bold text-ink">
                        {data.crew && data.crew.length > 0
                          ? data.crew.map((c) => c.name).join(", ")
                          : data.worker.name}
                      </p>
                      <p className="text-[11px] text-ink-soft">{data.crew?.length ?? 3} Members Assigned</p>
                    </div>
                  </div>
                </Card>

                <Card>
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-track-50 text-track-700">
                      <PackageCheck className="h-5 w-5" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-semibold text-ink-soft">Household Progress</p>
                        <span className="text-xs font-bold text-ink">
                          {marked} / {total} ({progressPct}%)
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-paper-subtle">
                        <div
                          className="h-full bg-track-600 transition-all duration-300"
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </Card>
              </div>

              {/* RANDOM AUDIT EVIDENCE GATE MODAL / BANNER */}
              {activeWorkflow?.type === "RANDOM_AUDIT" && (
                <div className="rounded-2xl border-2 border-amber-500 bg-amber-50/95 p-5 shadow-md animate-in fade-in duration-200">
                  <div className="flex items-start gap-3.5">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-600 text-white shadow-xs">
                      <ShieldAlert className="h-6 w-6" />
                    </div>
                    <div className="space-y-2 flex-1">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center rounded-md bg-amber-200 px-2 py-0.5 text-xs font-bold text-amber-900 uppercase">
                            Random Audit Selected
                          </span>
                          <span className="text-xs font-mono font-bold text-amber-900">
                            Flat {activeWorkflow.householdId} (HH-{activeWorkflow.householdId})
                          </span>
                        </div>
                        <h3 className="text-base font-bold text-amber-950 mt-1">
                          Photo Evidence Required Before Recording Collection
                        </h3>
                      </div>

                      <p className="text-xs text-amber-900 leading-relaxed">
                        This household collection has been selected by the system for Random Audit. You must capture an on-device camera photo of the household waste bin to verify segregation accuracy before this record can be finalized.
                      </p>

                      <div className="rounded-xl border border-amber-300 bg-white p-4 mt-3">
                        <p className="text-xs font-bold text-ink mb-2">Capture Household Bin Photo (Device GPS + Timestamp)</p>
                        <CameraCapture
                          withGps
                          label="Open System Camera & Capture Random Audit Evidence"
                          onCapture={handleRandomAuditEvidence}
                        />
                      </div>

                      <div className="flex items-center justify-between pt-2">
                        <span className="text-[11px] text-amber-800 font-medium">
                          Provenance: RANDOM_AUDIT • Target: HH-{activeWorkflow.householdId} • Category: COLLECTION_EVENT_AUDIT
                        </span>
                        <button
                          type="button"
                          onClick={() => setActiveWorkflow(null)}
                          className="text-xs text-amber-900 hover:underline font-semibold"
                        >
                          Cancel / Return to List
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* IN-ROUTE SYSTEM VERIFICATION INTERRUPTION BANNER */}
              {isTripPaused && (
                <div className="rounded-2xl border-2 border-flag-500 bg-flag-50/90 p-5 shadow-sm">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-start gap-3.5">
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-flag-500 text-white shadow-xs">
                        <ShieldAlert className="h-6 w-6" />
                      </div>
                      <div className="space-y-1">
                        <h3 className="text-sm font-bold tracking-tight text-flag-900">
                          SYSTEM VERIFICATION TRIGGERED
                        </h3>
                        <p className="text-xs text-flag-800">
                          Collection record <strong className="font-bold text-flag-950">{data.trip?.verification_target?.household_label ?? "HH-8"}</strong> has been selected for independent verification.
                        </p>
                        <p className="text-xs text-flag-800">
                          Recorded result: <span className="inline-flex items-center rounded-md bg-white/80 px-2 py-0.5 font-mono text-[11px] font-bold text-flag-900 border border-flag-300">{data.trip?.verification_target?.recorded_status ?? "SEGREGATED"}</span> • Reason: <span className="font-mono text-[11px] font-semibold text-flag-700">RANDOM_VERIFICATION</span>
                        </p>
                      </div>
                    </div>
                    <div className="shrink-0 pt-2 sm:pt-0">
                      <Btn
                        tone="flag"
                        busy={ackBusy}
                        onClick={handleAcknowledgeProtocol}
                      >
                        <ShieldCheck className="mr-1.5 h-4 w-4" />
                        Acknowledge Protocol & Resume
                      </Btn>
                    </div>
                  </div>
                </div>
              )}

              {/* HOUSEHOLD COLLECTIONS LIST */}
              <Card
                title="Household Collections"
                right={<span className="text-xs text-ink-soft">Beat households in {cleanLabel(data.route.ward)}</span>}
              >
                <div className="divide-y divide-line/60">
                  {data.households.map((h) => {
                    const isMarked = h.status !== "PENDING";
                    const isBusy = busyId === h.id;
                    const isLockedByPause = isTripPaused && !isMarked;
                    const evState = evidenceStates[h.id] ?? { phase: "idle" };

                    return (
                      <div key={h.id} className="py-3.5 first:pt-0 last:pb-0">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div className="flex items-center gap-3">
                            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-paper-subtle font-mono text-xs font-bold text-ink-soft">
                              HH-{h.id}
                            </span>
                            <div>
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-semibold text-ink">{h.address}</p>
                              </div>
                              <p className="text-xs text-ink-soft">Resident: {h.owner_name}</p>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            {isMarked ? (
                              <div className="flex items-center gap-2">
                                <Badge
                                  tone={h.status === "SEGREGATED" ? "ok" : "flag"}
                                >
                                  {h.status === "SEGREGATED" ? "SEGREGATED" : "UNSEGREGATED"}
                                </Badge>
                                {h.marked_at && (
                                  <span className="text-[11px] text-ink-soft">
                                    {fmtDate(h.marked_at)}
                                  </span>
                                )}
                              </div>
                            ) : (
                              <div className="flex items-center gap-2">
                                <Btn
                                  className="!px-3 !py-1 text-xs"
                                  tone="ok"
                                  disabled={isBusy || isLockedByPause || isLoadDeclared}
                                  busy={isBusy}
                                  onClick={() => initiateMarkHousehold(h, "SEGREGATED")}
                                >
                                  Segregated
                                </Btn>
                                <Btn
                                  className="!px-3 !py-1 text-xs"
                                  tone="flag"
                                  disabled={isBusy || isLockedByPause || isLoadDeclared}
                                  busy={isBusy}
                                  onClick={() => initiateMarkHousehold(h, "UNSEGREGATED")}
                                >
                                  Unsegregated
                                </Btn>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Negative-Event Camera Capture (Unsegregated) */}
                        {h.status === "UNSEGREGATED" && evState.phase !== "done" && (
                          <div className="mt-3 rounded-xl border border-flag-200 bg-flag-50/50 p-3.5">
                            {(!activeWorkflow || (activeWorkflow.type === "NEGATIVE_EVENT" && activeWorkflow.householdId !== h.id)) && (
                              <div className="flex items-center justify-between gap-3">
                                <div className="flex items-center gap-2 text-xs text-flag-800">
                                  <AlertTriangle className="h-4 w-4 shrink-0 text-flag-600" />
                                  <span>Negative-event evidence recommended for unsegregated waste.</span>
                                </div>
                                <Btn
                                  className="!px-3 !py-1 text-xs"
                                  tone="flag"
                                  disabled={Boolean(activeWorkflow)}
                                  onClick={() => setActiveWorkflow({
                                    type: "NEGATIVE_EVENT",
                                    householdId: h.id,
                                    householdAddress: h.address,
                                  })}
                                >
                                  Open System Camera
                                </Btn>
                              </div>
                            )}

                            {activeWorkflow?.type === "NEGATIVE_EVENT" && activeWorkflow.householdId === h.id && (
                              <div>
                                <p className="mb-2 text-xs font-semibold text-flag-900">
                                  Capture Non-Compliance Evidence — HH-{h.id} ({h.address})
                                </p>
                                <CameraCapture
                                  withGps
                                  label="Capture Point-of-Collection Negative Event Photo"
                                  onCapture={(res) => handleNegativeEvidenceCapture(h.id, res)}
                                />
                                <div className="mt-2 text-right">
                                  <button
                                    type="button"
                                    className="text-xs text-ink-soft hover:text-ink underline"
                                    onClick={() => setActiveWorkflow(null)}
                                  >
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            )}

                            {evState.phase === "uploading" && (
                              <div className="py-2 text-center text-xs text-flag-800">
                                <Spinner label="Uploading tamper-evident photo..." />
                              </div>
                            )}

                            {evState.phase === "error" && (
                              <div className="space-y-2">
                                <Notice tone="flag" title="Upload failed">
                                  {evState.message}
                                </Notice>
                                <Btn
                                  className="!px-3 !py-1 text-xs"
                                  tone="flag"
                                  disabled={activeWorkflow?.type === "RANDOM_AUDIT"}
                                  onClick={() => setActiveWorkflow({
                                    type: "NEGATIVE_EVENT",
                                    householdId: h.id,
                                    householdAddress: h.address,
                                  })}
                                >
                                  Try Again
                                </Btn>
                              </div>
                            )}
                          </div>
                        )}

                        {evState.phase === "done" && (
                          <div className="mt-2 flex items-center gap-2 text-xs text-ok-700">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            <span>Photo evidence recorded at point of collection (Current Trip).</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Card>

              {/* TRIP COMPLETION & AUTOMATIC DIGITAL LOAD CREATION */}
              {isAllMarked && !isLoadDeclared && (
                <Card tone="track" title="Collection Complete">
                  <div className="space-y-4">
                    <div className="rounded-xl bg-paper/80 p-4 border border-line/60">
                      <p className="text-xs font-semibold text-ink-soft uppercase tracking-wider">Shift Summary</p>
                      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 text-sm">
                        <div>
                          <dt className="text-xs text-ink-soft">Households Serviced</dt>
                          <dd className="font-bold text-ink mt-0.5">{total}</dd>
                        </div>
                        <div>
                          <dt className="text-xs text-ink-soft">Segregated</dt>
                          <dd className="font-bold text-ok-700 mt-0.5">{segregatedCount}</dd>
                        </div>
                        <div>
                          <dt className="text-xs text-ink-soft">Unsegregated</dt>
                          <dd className="font-bold text-flag-700 mt-0.5">{unsegregatedCount}</dd>
                        </div>
                        <div>
                          <dt className="text-xs text-ink-soft">Assigned Vehicle</dt>
                          <dd className="font-bold text-ink mt-0.5">{data.vehicle?.registration_number ?? "MH-01-AB-1234"}</dd>
                        </div>
                      </dl>
                    </div>

                    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-2">
                      <p className="text-xs text-ink-soft">
                        All assigned households collected. Completing the trip seals the collection trail and queues the Digital Load for weighbridge receiving intake. Zero worker weight input required.
                      </p>
                      <Btn
                        tone="track"
                        busy={completing}
                        onClick={handleCompleteCollectionTrip}
                      >
                        <PackageCheck className="mr-1.5 h-4 w-4" />
                        Complete Collection Trip
                      </Btn>
                    </div>
                  </div>
                </Card>
              )}

              {/* DIGITAL LOAD SEALED & AWAITING RECEIVING */}
              {isLoadDeclared && (
                <Card tone="ok">
                  <div className="flex items-start gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-ok-600 text-white shadow-xs">
                      <PackageCheck className="h-6 w-6" />
                    </div>
                    <div className="space-y-3 flex-1">
                      <div>
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-ok-100 px-2.5 py-0.5 text-xs font-bold text-ok-800">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Collection Trip Completed
                        </span>
                        <h3 className="mt-1 font-mono text-xl font-bold text-ink">
                          {data.active_load?.id ?? "—"}
                        </h3>
                      </div>

                      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-xl bg-paper/60 p-3.5 border border-line/60 text-xs">
                        <div>
                          <dt className="text-ink-soft">Route Jurisdiction</dt>
                          <dd className="font-bold text-ink mt-0.5">{cleanLabel(data.route.ward)}</dd>
                        </div>
                        <div>
                          <dt className="text-ink-soft">Collection Vehicle</dt>
                          <dd className="font-bold text-ink mt-0.5">{data.vehicle?.registration_number ?? "MH-01-AB-1234"}</dd>
                        </div>
                        <div>
                          <dt className="text-ink-soft">Trip Code</dt>
                          <dd className="font-mono font-bold text-ink mt-0.5">{data.trip?.trip_code ?? "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-ink-soft">Load Status</dt>
                          <dd className="font-bold text-track-700 mt-0.5">AWAITING RECEIVING</dd>
                        </div>
                      </dl>

                      <p className="text-xs text-ink-soft leading-relaxed">
                        Collection trip completed. Digital Load <strong className="font-mono text-ink font-bold">{data.active_load?.id}</strong> has been sealed and is awaiting receiving intake at the facility weighbridge.
                      </p>
                    </div>
                  </div>
                </Card>
              )}
            </div>
          )}
        </>
      )}

      {/* TAB 2: WORKER HISTORY */}
      {activeTab === "history" && (
        <div className="space-y-6">
          <Card
            title="Operational Collection History"
            right={<span className="text-xs text-ink-soft">Historical collection trips and shift logs</span>}
          >
            {historyLoad.loading && !historyLoad.data && <Spinner label="Loading collection history..." />}
            {historyLoad.data && (
              <Table
                head={[
                  "Date",
                  "Trip Code",
                  "Route / Ward",
                  "Vehicle",
                  "Households",
                  "Seg / Unseg",
                  "Random Audits",
                  "Status",
                  "Credits",
                ]}
                empty="No historical collection records found."
                rows={historyLoad.data.map((item) => [
                  fmtDate(item.date),
                  <span key="tc" className="font-mono font-bold text-ink">{item.trip_code}</span>,
                  cleanLabel(item.ward),
                  <span key="v" className="font-semibold text-ink">{item.vehicle_registration}</span>,
                  `${item.households_serviced} serviced`,
                  <span key="su" className="text-xs">
                    <span className="font-bold text-ok-700">{item.segregated}</span> / <span className="font-bold text-flag-700">{item.unsegregated}</span>
                  </span>,
                  item.random_audits > 0 ? (
                    <Badge key="ra" tone="ok">✓ Completed</Badge>
                  ) : (
                    <span key="ra" className="text-xs text-ink-soft">—</span>
                  ),
                  <Badge key="s" tone={item.status === "COMPLETED" ? "ok" : "track"}>{item.status}</Badge>,
                  <span key="c" className="font-mono font-bold text-ok-700">+{item.credits_earned} pts</span>,
                ])}
              />
            )}
          </Card>
        </div>
      )}

      {/* TAB 3: WORKER INTEGRITY & CREDITS */}
      {activeTab === "integrity" && (
        <div className="space-y-6">
          {integrityLoad.loading && !integrityLoad.data && <Spinner label="Loading integrity metrics..." />}
          {integrityLoad.data && (
            <>
              {/* Current Shift Summary */}
              {data?.trip && (
                <Card title="Current Collection Shift Status" tone="track">
                  <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
                    <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                      <dt className="text-ink-soft">Active Trip Code</dt>
                      <dd className="font-mono font-bold text-ink mt-0.5">{data.trip.trip_code}</dd>
                    </div>
                    <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                      <dt className="text-ink-soft">Current Shift Progress</dt>
                      <dd className="font-bold text-ink mt-0.5">{marked} / {total} Serviced</dd>
                    </div>
                    <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                      <dt className="text-ink-soft">Active Digital Load</dt>
                      <dd className="font-mono font-bold text-track-700 mt-0.5">{data.active_load?.id ?? "Pending First Collection"}</dd>
                    </div>
                    <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                      <dt className="text-ink-soft">Shift Status</dt>
                      <dd className="font-bold text-ok-700 mt-0.5">{isLoadDeclared || data.trip.status === "COMPLETED" ? "Sealed / Complete" : "In Progress"}</dd>
                    </div>
                  </dl>
                </Card>
              )}

              {/* Integrity KPI Summary */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Kpi label="Total Worker Credits" value={`${integrityLoad.data.total_credits} pts`} tone="ok" />
                <Kpi label="Collections Completed" value={integrityLoad.data.collections_completed} tone="track" />
                <Kpi label="Random Audits Executed" value={integrityLoad.data.random_audits_completed} tone="auth" />
                <Kpi label="Evidence Compliance" value={`${integrityLoad.data.audit_evidence_compliance_pct}%`} tone="ok" />
              </div>

              {/* Explainable Credits Ledger */}
              <Card
                title="Historical Integrity Ledger"
                right={<span className="text-xs text-ink-soft">Persisted tamper-evident event awards</span>}
              >
                <div className="divide-y divide-line/60">
                  {integrityLoad.data.integrity_events.map((evt) => (
                    <div key={evt.id} className="py-3.5 flex items-start justify-between gap-4 first:pt-0 last:pb-0">
                      <div className="flex items-start gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ok-50 text-ok-700 mt-0.5 border border-ok-200">
                          <Sparkles className="h-4 w-4" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-bold text-ink">{evt.title}</p>
                            <span className="font-mono text-xs font-semibold text-ink-soft">({evt.household_label})</span>
                          </div>
                          <p className="text-xs text-ink-soft mt-0.5">{evt.description}</p>
                          <p className="text-[11px] text-ink-faint mt-1">{fmtDate(evt.timestamp)}</p>
                        </div>
                      </div>

                      <div className="shrink-0">
                        <span className="inline-flex items-center rounded-lg bg-ok-100 px-3 py-1 font-mono text-xs font-bold text-ok-800">
                          +{evt.points} pts
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}
        </div>
      )}
    </Shell>
  );
}
