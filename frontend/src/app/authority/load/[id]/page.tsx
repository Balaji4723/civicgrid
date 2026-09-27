"use client";
import Link from "next/link";
import { useState } from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  Layers,
  Package,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { api, ApiError, session } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import type {
  Discrepancy,
  DispositionType,
  FacilityCollection,
  FinalDisposition,
  Handoff,
  Integrity,
  LoadDetail,
  LoadTimeline,
  ProcessingMethod,
  ProcessingRecord,
  DisposalException,
  WasteStream,
} from "@/lib/types";
import {
  PROCESSING_METHODS,
  WASTE_STREAMS,
  DISPOSITION_TYPES,
} from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Field,
  inputCls,
  LoadBadge,
  Notice,
  Spinner,
  StatusBadge,
  Table,
  type Tone,
} from "@/components/ui";
import { Shell } from "@/components/Shell";
import { ChainTimeline } from "@/components/ChainTimeline";
import { getSubnavForUser, getUserCapability, cleanLabel } from "@/lib/nav";

const procTone: Record<string, Tone> = {
  PENDING: "track",
  IN_PROGRESS: "proc",
  COMPLETED: "ok",
  CANCELLED: "neutral",
};
const handoffTone: Record<string, Tone> = {
  PENDING: "track",
  IN_TRANSIT: "proc",
  COMPLETED: "ok",
  CANCELLED: "neutral",
};
const dispositionTone: Record<string, Tone> = {
  RECORDED: "track",
  VERIFIED: "ok",
  CANCELLED: "neutral",
};
const exceptionTone: Record<string, Tone> = {
  RAISED: "flag",
  PENDING_AUTHORIZATION: "flag",
  AUTHORIZED: "proc",
  REJECTED: "neutral",
  RESOLVED: "ok",
  CANCELLED: "neutral",
};

function facilityOptions(fc: FacilityCollection | null) {
  return fc?.features.map((f) => f.properties) ?? [];
}

export default function LoadJourneyPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id).toUpperCase();

  const detail = useLoad(() => api<LoadDetail>(`/loads/${id}`), [id]);
  const timeline = useLoad(() => api<LoadTimeline>(`/loads/${id}/timeline`), [id]);
  const integrity = useLoad(() => api<Integrity>(`/loads/${id}/verify-integrity`), [id]);
  const facilities = useLoad(() => api<FacilityCollection>("/facilities"));

  async function reloadAll() {
    await Promise.all([detail.reload(), timeline.reload(), integrity.reload()]);
  }

  const [recGross, setRecGross] = useState("8720");
  const [recTare, setRecTare] = useState("8330");
  const [recNet, setRecNet] = useState("390");
  const [useWeighbridgeCalc, setUseWeighbridgeCalc] = useState(true);
  const [recCond, setRecCond] = useState<"ACCEPTABLE" | "UNACCEPTABLE">("ACCEPTABLE");
  const [recBusy, setRecBusy] = useState(false);
  const [recErr, setRecErr] = useState<string | null>(null);

  const calculatedRecNet = useWeighbridgeCalc && Number(recGross) > Number(recTare)
    ? Number(recGross) - Number(recTare)
    : Number(recNet) || 0;

  async function handleRecordReceiving() {
    if (calculatedRecNet <= 0) {
      setRecErr("Please specify a valid net received quantity greater than 0 kg.");
      return;
    }
    setRecBusy(true);
    setRecErr(null);
    try {
      await api(`/loads/${id}/receiving`, {
        body: { quantity: calculatedRecNet, condition: recCond },
      });
      await reloadAll();
    } catch (e) {
      setRecErr(e instanceof ApiError ? e.message : "Failed to record receiving measurement.");
    } finally {
      setRecBusy(false);
    }
  }

  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isMunicipal = cap === "MUNICIPAL";
  const canOperateReceiving = cap === "RECEIVING";
  const canOperateProcessing = cap === "PROCESSING";
  const canAuthorizeExceptions = cap === "MUNICIPAL";
  const subnav = getSubnavForUser(me);

  const d = detail.data;
  const t = timeline.data;
  const chain = integrity.data;

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="auth"
      title="Digital Load Life Cycle"
      subtitle={`ONE LOAD · ONE DIGITAL TRAIL — Complete chain of custody and verifiable custody transitions for ${id}`}
      subnav={subnav}
    >
      <div className="mb-4">
        <Link
          href="/authority/loads"
          className="inline-flex items-center gap-1 text-xs font-semibold text-ink-soft hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Digital Loads Register
        </Link>
      </div>

      {(detail.error || timeline.error) && (
        <div className="mb-4">
          <Notice tone="flag" title="Unable to retrieve journey records">
            {detail.error ?? timeline.error}
          </Notice>
        </div>
      )}

      {(!d || !t) && (detail.loading || timeline.loading) && (
        <Spinner label="Loading complete load life cycle" />
      )}

      {d && t && (
        <div className="space-y-6">
          {/* Header Card: ID, Status, and Cryptographic Integrity Badge */}
          <Card>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink p-2 text-white shadow-xs">
                  <Package className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="font-mono text-2xl font-bold tracking-tight text-ink">{d.id}</h2>
                  <p className="text-xs text-ink-soft">Registered Digital Load Record</p>
                </div>
                <LoadBadge status={d.status} />
              </div>
              <ChainVerifiedBadge
                integrity={chain}
                loading={integrity.loading}
                onVerify={() => integrity.reload()}
              />
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 text-sm">
              <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Ward Jurisdiction</dt>
                <dd className="font-bold text-ink mt-0.5">{cleanLabel(d.ward)}</dd>
              </div>
              <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Collection Vehicle</dt>
                <dd className="font-bold text-ink mt-0.5">{d.vehicle ? `${d.vehicle.registration_number}` : "Assigned Fleet"}</dd>
                <span className="text-[10px] text-ink-soft">{d.vehicle?.vehicle_type ?? "Compactor"}</span>
              </div>
              <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Collection Trip</dt>
                <dd className="font-mono font-bold text-ink mt-0.5">{d.trip?.trip_code ?? d.trip_code ?? "—"}</dd>
                <span className="text-[10px] text-ink-soft">Trip Code</span>
              </div>
              <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Assigned Crew</dt>
                <dd className="font-medium text-ink mt-0.5 truncate">{d.crew && d.crew.length > 0 ? d.crew.map(c => c.name).join(", ") : (d.worker ?? "Crew")}</dd>
                <span className="text-[10px] text-ink-soft">Field Crew</span>
              </div>
              <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Declared / Est. Load</dt>
                <dd className="font-bold text-track-700 mt-0.5">
                  {d.declaration.quantity != null ? `${d.declaration.quantity} kg` : "—"}
                </dd>
                <span className="text-[10px] text-ink-soft">Field Declaration</span>
              </div>
              <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Facility Receiving Weighed</dt>
                <dd className="font-bold text-auth-700 mt-0.5">
                  {d.receiving?.quantity != null ? `${d.receiving.quantity} kg` : "Pending Arrival"}
                </dd>
                <span className="text-[10px] text-ink-soft">Weighbridge Actual</span>
              </div>
            </dl>
          </Card>

          {/* Connected Waste Journey Stage Progress Strip */}
          <JourneyStrip detail={d} timeline={t} />

          {/* Mass Balance & Custody Accounting */}
          <MassBalanceSummary detail={d} timeline={t} />

          {/* Intake Weighbridge & Receiving Measurement Workflow */}
          {d.status === "DECLARED" && (
            canOperateReceiving ? (
              <Card tone="auth" title="Receiving Bay Weighbridge & Cross-Check">
                <div className="space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <p className="text-xs text-ink-soft">
                      Vehicle <strong className="text-ink">{d.vehicle ? d.vehicle.registration_number : "Assigned Fleet"}</strong> has arrived from collection trip <strong className="text-ink">{d.trip?.trip_code ?? d.trip_code ?? "—"}</strong>. Record intake measurement to run automated Cross-Check.
                    </p>
                    <button
                      type="button"
                      onClick={() => setUseWeighbridgeCalc(!useWeighbridgeCalc)}
                      className="text-xs font-semibold text-auth-700 hover:underline shrink-0"
                    >
                      {useWeighbridgeCalc ? "Direct Net Input" : "Gross / Tare Calculator"}
                    </button>
                  </div>

                  {useWeighbridgeCalc ? (
                    <div className="rounded-xl border border-line/60 bg-paper/50 p-3.5 space-y-3">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="Loaded Vehicle Gross Weight (kg)">
                          <input
                            className={inputCls}
                            inputMode="numeric"
                            value={recGross}
                            onChange={(e) => setRecGross(e.target.value.replace(/\D/g, ""))}
                            placeholder="e.g. 8720"
                          />
                        </Field>
                        <Field label="Empty Vehicle Tare Weight (kg)">
                          <input
                            className={inputCls}
                            inputMode="numeric"
                            value={recTare}
                            onChange={(e) => setRecTare(e.target.value.replace(/\D/g, ""))}
                            placeholder="e.g. 8330"
                          />
                        </Field>
                      </div>
                      <div className="flex items-center justify-between rounded-lg bg-auth-50/80 px-3 py-2 text-xs">
                        <span className="font-semibold text-auth-800">Net Received Waste Quantity:</span>
                        <span className="font-mono text-sm font-bold text-auth-900">
                          {calculatedRecNet} kg
                        </span>
                      </div>
                    </div>
                  ) : (
                    <Field label="Net Receiving Measurement (kg)">
                      <input
                        className={inputCls}
                        inputMode="numeric"
                        value={recNet}
                        onChange={(e) => setRecNet(e.target.value.replace(/\D/g, ""))}
                        placeholder="e.g. 390"
                      />
                    </Field>
                  )}

                  <Field label="Waste Stream Condition on Arrival">
                    <select
                      className={inputCls}
                      value={recCond}
                      onChange={(e) => setRecCond(e.target.value as typeof recCond)}
                    >
                      <option value="ACCEPTABLE">Acceptable (Meets Segregation Standard)</option>
                      <option value="UNACCEPTABLE">Unacceptable (Severe Contamination / Mixed)</option>
                    </select>
                  </Field>

                  <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2">
                    <Btn
                      tone="auth"
                      busy={recBusy}
                      disabled={calculatedRecNet <= 0 || recBusy}
                      onClick={handleRecordReceiving}
                    >
                      <Scale className="h-4 w-4" />
                      Record Receiving Measurement & Execute Cross-Check
                    </Btn>
                    <span className="text-xs text-ink-soft">
                      CivicGrid cross-checks the chain rather than trusting a single record.
                    </span>
                  </div>

                  {recErr && <Notice tone="flag">{recErr}</Notice>}
                </div>
              </Card>
            ) : (
              <Card tone="auth" title="Receiving Bay Weighbridge & Cross-Check (Read-Only Status)">
                <p className="text-xs text-ink-soft">
                  Vehicle <strong className="text-ink">{d.vehicle ? d.vehicle.registration_number : "Assigned Fleet"}</strong> has arrived from collection trip <strong className="text-ink">{d.trip?.trip_code ?? d.trip_code ?? "—"}</strong>. Awaiting weighbridge intake measurement and automated cross-check by the assigned Receiving Operator.
                </p>
              </Card>
            )
          )}

          {/* Discrepancies on this Load */}
          {d.discrepancies.length > 0 && (
            <Card tone="flag" title="Associated Discrepancies">
              <Table
                head={["Discrepancy #", "Type", "Current Status", "Action"]}
                rows={d.discrepancies.map((x: Discrepancy) => [
                  `#${x.id}`,
                  <Badge key="t">{x.type}</Badge>,
                  <StatusBadge key="s" status={x.status} />,
                  <Link
                    key="l"
                    className="text-xs font-semibold text-auth-700 underline"
                    href={`/authority/discrepancy/${x.id}`}
                  >
                    Open Resolution Workflow &rarr;
                  </Link>,
                ])}
              />
            </Card>
          )}

          {/* Phase 3 Operations Sections */}
          <ProcessingSection
            loadId={id}
            loadStatus={d.status}
            records={t.processing_records}
            facilities={facilities.data}
            onChanged={reloadAll}
            canOperate={canOperateProcessing}
          />
          <HandoffSection
            loadId={id}
            records={t.processing_records}
            handoffs={t.handoffs}
            facilities={facilities.data}
            onChanged={reloadAll}
            canOperate={canOperateProcessing}
          />
          <DispositionSection
            loadId={id}
            handoffs={t.handoffs}
            records={t.processing_records}
            dispositions={t.final_dispositions}
            facilities={facilities.data}
            onChanged={reloadAll}
            canOperate={canOperateProcessing}
          />
          <ExceptionSection
            loadId={id}
            records={t.processing_records}
            handoffs={t.handoffs}
            exceptions={t.disposal_exceptions}
            facilities={facilities.data}
            onChanged={reloadAll}
            canRaise={canOperateProcessing}
            canAuthorize={canAuthorizeExceptions}
          />

          {/* Complete SHA-256 Hash Chain Timeline */}
          <Card
            title="Cryptographic Hash Chain Timeline"
            right={
              <span className="text-xs font-semibold text-ink-soft">
                {t.events.length} Tamper-Evident Events
              </span>
            }
          >
            <ChainTimeline events={t.events} result={chain} />
          </Card>
        </div>
      )}
    </Shell>
  );
}

function ChainVerifiedBadge({
  integrity,
  loading,
  onVerify,
}: {
  integrity: Integrity | null;
  loading: boolean;
  onVerify: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      {integrity == null ? (
        <Badge tone="neutral">{loading ? "Validating SHA-256 chain…" : "Chain unverified"}</Badge>
      ) : integrity.valid ? (
        <Badge tone="ok">
          <ShieldCheck className="h-3.5 w-3.5" />
          SHA-256 Intact ({integrity.total_events} events verified)
        </Badge>
      ) : (
        <Badge tone="flag">
          <ShieldAlert className="h-3.5 w-3.5" />
          Tampering detected at event #{integrity.broken_event_id}
        </Badge>
      )}
      <Btn
        tone="neutral"
        variant="outline"
        busy={loading}
        onClick={onVerify}
        className="!px-2.5 !py-1 text-xs"
      >
        Re-verify Integrity
      </Btn>
    </div>
  );
}

function MassBalanceSummary({ detail, timeline }: { detail: LoadDetail; timeline: LoadTimeline }) {
  const processedTotal = timeline.processing_records
    .filter((p) => p.status === "COMPLETED")
    .reduce((sum, p) => sum + (p.processed_quantity_kg || 0), 0);
  const recoveredTotal = timeline.processing_records
    .filter((p) => p.status === "COMPLETED")
    .reduce((sum, p) => sum + (p.recovered_quantity_kg || 0), 0);
  const residualTotal = timeline.processing_records
    .filter((p) => p.status === "COMPLETED")
    .reduce((sum, p) => sum + (p.residual_quantity_kg || 0), 0);
  const transferredTotal = timeline.handoffs
    .filter((h) => h.status === "COMPLETED")
    .reduce((sum, h) => sum + (h.quantity_kg || 0), 0);
  const dispositionTotal = timeline.final_dispositions
    .filter((f) => f.status === "VERIFIED")
    .reduce((sum, f) => sum + (f.quantity_kg || 0), 0);

  return (
    <Card tone="neutral" title="Mass Balance & Custody Accounting">
      <p className="text-xs text-ink-soft mb-3">
        Every kilogram is traceable across collection declaration, weighbridge actuals, material recovery yield, residual fractions, and terminal disposal.
      </p>
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7 text-xs">
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">1 · Worker Declared</span>
          <span className="font-bold text-track-800 text-sm mt-1 block">
            {detail.declaration.quantity != null ? `${detail.declaration.quantity} kg` : "—"}
          </span>
          <span className="text-[10px] text-ink-faint">Field Declaration</span>
        </div>
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">2 · Facility Received</span>
          <span className="font-bold text-auth-800 text-sm mt-1 block">
            {detail.receiving?.quantity != null ? `${detail.receiving.quantity} kg` : "Pending Arrival"}
          </span>
          <span className="text-[10px] text-ink-faint">Weighbridge Intake</span>
        </div>
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">3 · Processed</span>
          <span className="font-bold text-proc-800 text-sm mt-1 block">
            {processedTotal > 0 ? `${processedTotal} kg` : "Pending Batch"}
          </span>
          <span className="text-[10px] text-ink-faint">MRF / Composting</span>
        </div>
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">4 · Recovered</span>
          <span className="font-bold text-ok-700 text-sm mt-1 block">
            {recoveredTotal > 0 ? `${recoveredTotal} kg` : "0 kg"}
          </span>
          <span className="text-[10px] text-ink-faint">Recyclable / Compost</span>
        </div>
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">5 · Residual</span>
          <span className="font-bold text-flag-700 text-sm mt-1 block">
            {residualTotal > 0 ? `${residualTotal} kg` : "0 kg"}
          </span>
          <span className="text-[10px] text-ink-faint">Reject / Inert</span>
        </div>
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">6 · Transferred</span>
          <span className="font-bold text-track-700 text-sm mt-1 block">
            {transferredTotal > 0 ? `${transferredTotal} kg` : "0 kg"}
          </span>
          <span className="text-[10px] text-ink-faint">Inter-Facility Transit</span>
        </div>
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <span className="text-ink-soft block font-medium">7 · Final Disposition</span>
          <span className="font-bold text-ok-800 text-sm mt-1 block">
            {dispositionTotal > 0 ? `${dispositionTotal} kg` : "Pending"}
          </span>
          <span className="text-[10px] text-ink-faint">Certified Terminal</span>
        </div>
      </div>
    </Card>
  );
}

function JourneyStrip({ detail, timeline }: { detail: LoadDetail; timeline: LoadTimeline }) {
  const hasDiscrepancy = detail.discrepancies.length > 0;
  const isSettled = detail.status === "SETTLED" || detail.status === "VERIFIED";

  const stages: { label: string; done: boolean; note?: string }[] = [
    {
      label: "1. Collection",
      done: true,
      note: `${detail.declaration.households_collected} households`,
    },
    {
      label: "2. Digital Load",
      done: !!detail.declaration.quantity,
      note: detail.declaration.quantity ? `${detail.declaration.quantity} kg` : "Declared",
    },
    {
      label: "3. Receiving",
      done: !!detail.receiving,
      note: detail.receiving ? `${detail.receiving.quantity} kg` : "Awaiting arrival",
    },
    {
      label: "4. Cross-Check",
      done: detail.status !== "DECLARED" && detail.status !== "COLLECTING",
      note:
        detail.status === "DECLARED"
          ? "Pending intake"
          : hasDiscrepancy
            ? `${detail.discrepancies.length} flagged`
            : "Matched",
    },
    {
      label: "5. Independent Verification",
      done: !hasDiscrepancy ? (detail.status !== "DECLARED" && detail.status !== "COLLECTING") : isSettled,
      note: !hasDiscrepancy
        ? "Not Required (Matched)"
        : isSettled
          ? "Resolved & Settled"
          : "Audit In Progress",
    },
    {
      label: "6. Processing",
      done: timeline.processing_records.some((p) => p.status === "COMPLETED"),
      note: timeline.processing_records.length > 0
        ? `${timeline.processing_records.length} batch(es)`
        : "Pending",
    },
    {
      label: "7. Transfer Handoff",
      done: timeline.handoffs.some((h) => h.status === "COMPLETED"),
      note: timeline.handoffs.length > 0
        ? `${timeline.handoffs.length} transit(s)`
        : "Pending",
    },
    {
      label: "8. Final Disposition",
      done: timeline.final_dispositions.some((f) => f.status === "VERIFIED"),
      note: timeline.final_dispositions.length > 0
        ? `${timeline.final_dispositions.length} verified`
        : "Pending",
    },
  ];

  return (
    <Card title="Connected Custody Progression (One Load · One Digital Trail)">
      <div className="overflow-x-auto pb-1">
        <ol className="flex items-center gap-2 min-w-max">
          {stages.map((s, i) => (
            <li key={s.label} className="flex items-center gap-2">
              <div
                className={`rounded-xl border p-3 min-w-[135px] transition-all ${
                  s.done
                    ? "border-ok-200 bg-ok-50/70 text-ok-800 shadow-xs"
                    : "border-line bg-paper text-ink-soft opacity-75"
                }`}
              >
                <div className="flex items-center justify-between gap-1">
                  <p className="text-xs font-bold text-ink">{s.label}</p>
                  {s.done && <CheckCircle2 className="h-3.5 w-3.5 text-ok-600 shrink-0" />}
                </div>
                {s.note && <p className="mt-1 text-[11px] text-ink-soft truncate">{s.note}</p>}
              </div>
              {i < stages.length - 1 && (
                <ArrowRight className="h-4 w-4 text-ink-faint shrink-0" />
              )}
            </li>
          ))}
        </ol>
      </div>

      {timeline.disposal_exceptions.length > 0 && (
        <div className="mt-4 flex items-center gap-2 rounded-lg bg-flag-50 p-2.5 text-xs text-flag-700 border border-flag-100">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            {timeline.disposal_exceptions.some(
              (e) => e.status === "RAISED" || e.status === "PENDING_AUTHORIZATION"
            )
              ? "This load has an open disposal exception requiring municipal authorization below."
              : "Disposal exception was raised and authorized for alternate facility routing."}
          </span>
        </div>
      )}
    </Card>
  );
}

// Processing Section
function ProcessingSection({
  loadId,
  loadStatus,
  records,
  facilities,
  onChanged,
  canOperate = false,
}: {
  loadId: string;
  loadStatus: string;
  records: ProcessingRecord[];
  facilities: FacilityCollection | null;
  onChanged: () => void;
  canOperate?: boolean;
}) {
  const eligible = loadStatus === "VERIFIED" || loadStatus === "SETTLED";
  const hasOpen = records.some((r) => r.status === "PENDING" || r.status === "IN_PROGRESS");
  const [open, setOpen] = useState(false);
  const [facilityId, setFacilityId] = useState("");
  const [stream, setStream] = useState<WasteStream>("MIXED");
  const [method, setMethod] = useState<ProcessingMethod>("MATERIAL_RECOVERY");
  const [qty, setQty] = useState("");
  const [rec, setRec] = useState("");
  const [res, setRes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function startProcessing() {
    setBusy(true);
    setErr(null);
    try {
      await api<ProcessingRecord>("/processing", {
        body: {
          load_id: loadId,
          facility_id: Number(facilityId),
          waste_stream: stream,
          processing_method: method,
          processed_quantity_kg: Number(qty),
          recovered_quantity_kg: Number(rec || 0),
          residual_quantity_kg: Number(res || 0),
        },
      });
      setOpen(false);
      setQty("");
      setRec("");
      setRes("");
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start processing.");
    } finally {
      setBusy(false);
    }
  }

  async function act(recId: number, action: "complete" | "cancel") {
    setBusy(true);
    setErr(null);
    try {
      if (action === "complete") {
        await api(`/processing/${recId}/complete`, { method: "POST" });
      } else {
        await api(`/processing/${recId}/cancel`, {
          body: { reason: "Cancelled from Digital Load journey screen" },
        });
      }
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not update processing status.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      tone="proc"
      title="Downstream Processing (MRF / Composting / Recycling)"
      right={
        canOperate && eligible && !hasOpen ? (
          <Btn tone="proc" variant="outline" onClick={() => setOpen((v) => !v)}>
            {open ? "Close Form" : "Start Processing Batch"}
          </Btn>
        ) : undefined
      }
    >
      {!eligible && (
        <p className="text-xs text-ink-soft">
          Processing can begin once receiving cross-check is verified with no unresolved discrepancies (VERIFIED or SETTLED).
        </p>
      )}
      {eligible && hasOpen && (
        <p className="text-xs text-ink-soft">
          A processing batch is actively running for this load. Complete or cancel it before initiating another.
        </p>
      )}

      {open && (
        <div className="mb-4 grid gap-3 rounded-xl border border-line bg-paper/60 p-4 sm:grid-cols-3">
          <Field label="Facility">
            <select
              className={inputCls}
              value={facilityId}
              onChange={(e) => setFacilityId(e.target.value)}
            >
              <option value="">Select facility…</option>
              {facilityOptions(facilities).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Waste Stream">
            <select
              className={inputCls}
              value={stream}
              onChange={(e) => setStream(e.target.value as WasteStream)}
            >
              {WASTE_STREAMS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Processing Method">
            <select
              className={inputCls}
              value={method}
              onChange={(e) => setMethod(e.target.value as ProcessingMethod)}
            >
              {PROCESSING_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m.replaceAll("_", " ").toLowerCase()}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Processed Quantity (kg)">
            <input
              className={inputCls}
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 485"
            />
          </Field>
          <Field label="Recovered Quantity (kg)" hint="optional">
            <input
              className={inputCls}
              inputMode="numeric"
              value={rec}
              onChange={(e) => setRec(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 350"
            />
          </Field>
          <Field label="Residual Quantity (kg)" hint="optional">
            <input
              className={inputCls}
              inputMode="numeric"
              value={res}
              onChange={(e) => setRes(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 135"
            />
          </Field>
          <div className="sm:col-span-3 pt-2">
            <Btn
              tone="proc"
              busy={busy}
              disabled={!facilityId || !qty || busy}
              onClick={startProcessing}
            >
              Start Processing Batch
            </Btn>
          </div>
        </div>
      )}

      {err && <div className="mb-4"><Notice tone="flag">{err}</Notice></div>}

      <Table
        head={
          canOperate
            ? [
                "Batch #",
                "Facility",
                "Stream",
                "Method",
                "Processed",
                "Recovered",
                "Residual",
                "Status",
                "Actions",
              ]
            : [
                "Batch #",
                "Facility",
                "Stream",
                "Method",
                "Processed",
                "Recovered",
                "Residual",
                "Status",
              ]
        }
        empty="No processing records logged for this load."
        rows={records.map((r) => {
          const row: React.ReactNode[] = [
            `#${r.id}`,
            r.facility ?? `Facility ${r.facility_id}`,
            r.waste_stream,
            r.processing_method.replaceAll("_", " ").toLowerCase(),
            `${r.processed_quantity_kg} kg`,
            `${r.recovered_quantity_kg} kg`,
            `${r.residual_quantity_kg} kg`,
            <Badge key="b" tone={procTone[r.status]}>
              {r.status}
            </Badge>,
          ];
          if (canOperate) {
            row.push(
              r.status === "PENDING" || r.status === "IN_PROGRESS" ? (
                <div key="a" className="flex items-center gap-2">
                  <Btn
                    tone="ok"
                    busy={busy}
                    onClick={() => act(r.id, "complete")}
                    className="!px-2.5 !py-1 text-xs"
                  >
                    Complete
                  </Btn>
                  <Btn
                    tone="neutral"
                    variant="outline"
                    busy={busy}
                    onClick={() => act(r.id, "cancel")}
                    className="!px-2.5 !py-1 text-xs"
                  >
                    Cancel
                  </Btn>
                </div>
              ) : null
            );
          }
          return row;
        })}
      />
    </Card>
  );
}

// Handoff Section
function HandoffSection({
  loadId,
  records,
  handoffs,
  facilities,
  onChanged,
  canOperate = false,
}: {
  loadId: string;
  records: ProcessingRecord[];
  handoffs: Handoff[];
  facilities: FacilityCollection | null;
  onChanged: () => void;
  canOperate?: boolean;
}) {
  const completedRecords = records.filter((r) => r.status === "COMPLETED");
  const hasOpen = handoffs.some((h) => h.status === "PENDING" || h.status === "IN_TRANSIT");
  const [open, setOpen] = useState(false);
  const [recordId, setRecordId] = useState("");
  const [source, setSource] = useState("");
  const [dest, setDest] = useState("");
  const [stream, setStream] = useState<WasteStream>("RECOVERED");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function createHandoff() {
    setBusy(true);
    setErr(null);
    try {
      await api<Handoff>("/handoffs", {
        body: {
          load_id: loadId,
          processing_record_id: Number(recordId),
          source_facility_id: Number(source),
          destination_facility_id: Number(dest),
          waste_stream: stream,
          quantity_kg: Number(qty),
        },
      });
      setOpen(false);
      setQty("");
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not record inter-facility handoff.");
    } finally {
      setBusy(false);
    }
  }

  async function act(id: number, action: "complete" | "cancel") {
    setBusy(true);
    setErr(null);
    try {
      if (action === "complete") {
        await api(`/handoffs/${id}/complete`, { method: "POST" });
      } else {
        await api(`/handoffs/${id}/cancel`, {
          body: { reason: "Cancelled from Digital Load journey screen" },
        });
      }
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not update handoff status.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      tone="track"
      title="Inter-Facility Handoffs (Transfer & Transit)"
      right={
        canOperate && completedRecords.length > 0 && !hasOpen ? (
          <Btn tone="track" variant="outline" onClick={() => setOpen((v) => !v)}>
            {open ? "Close Form" : "Create Transfer Handoff"}
          </Btn>
        ) : undefined
      }
    >
      {completedRecords.length === 0 && (
        <p className="text-xs text-ink-soft">
          A transfer handoff requires at least one completed processing record to source material from.
        </p>
      )}
      {hasOpen && (
        <p className="text-xs text-ink-soft">
          A transfer handoff is currently in transit for this load.
        </p>
      )}

      {open && (
        <div className="mb-4 grid gap-3 rounded-xl border border-line bg-paper/60 p-4 sm:grid-cols-3">
          <Field label="Processing Record Source">
            <select
              className={inputCls}
              value={recordId}
              onChange={(e) => setRecordId(e.target.value)}
            >
              <option value="">Select source batch…</option>
              {completedRecords.map((r) => (
                <option key={r.id} value={r.id}>
                  Batch #{r.id} · Recovered: {r.recovered_quantity_kg}kg / Residual: {r.residual_quantity_kg}kg
                </option>
              ))}
            </select>
          </Field>
          <Field label="Waste Stream">
            <select
              className={inputCls}
              value={stream}
              onChange={(e) => setStream(e.target.value as WasteStream)}
            >
              <option value="RECOVERED">RECOVERED</option>
              <option value="RESIDUAL">RESIDUAL</option>
            </select>
          </Field>
          <Field label="Quantity (kg)">
            <input
              className={inputCls}
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 350"
            />
          </Field>
          <Field label="Originating Facility">
            <select
              className={inputCls}
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="">Select origin…</option>
              {facilityOptions(facilities).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Destination Facility">
            <select
              className={inputCls}
              value={dest}
              onChange={(e) => setDest(e.target.value)}
            >
              <option value="">Select destination…</option>
              {facilityOptions(facilities).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="flex items-end pt-2">
            <Btn
              tone="track"
              busy={busy}
              disabled={!recordId || !source || !dest || !qty || busy}
              onClick={createHandoff}
            >
              Create Handoff
            </Btn>
          </div>
        </div>
      )}

      {err && <div className="mb-4"><Notice tone="flag">{err}</Notice></div>}

      <Table
        head={
          canOperate
            ? [
                "Handoff #",
                "Origin Facility",
                "Destination",
                "Stream",
                "Quantity",
                "Status",
                "Timestamp",
                "Actions",
              ]
            : [
                "Handoff #",
                "Origin Facility",
                "Destination",
                "Stream",
                "Quantity",
                "Status",
                "Timestamp",
              ]
        }
        empty="No inter-facility handoffs recorded for this load."
        rows={handoffs.map((h) => {
          const row: React.ReactNode[] = [
            `#${h.id}`,
            h.source_facility ?? `Facility ${h.source_facility_id}`,
            h.destination_facility ?? `Facility ${h.destination_facility_id}`,
            h.waste_stream,
            `${h.quantity_kg} kg`,
            <Badge key="b" tone={handoffTone[h.status]}>
              {h.status.replace("_", " ")}
            </Badge>,
            fmtDate(h.timestamp),
          ];
          if (canOperate) {
            row.push(
              h.status === "PENDING" || h.status === "IN_TRANSIT" ? (
                <div key="a" className="flex items-center gap-2">
                  <Btn
                    tone="ok"
                    busy={busy}
                    onClick={() => act(h.id, "complete")}
                    className="!px-2.5 !py-1 text-xs"
                  >
                    Complete Handoff
                  </Btn>
                  <Btn
                    tone="neutral"
                    variant="outline"
                    busy={busy}
                    onClick={() => act(h.id, "cancel")}
                    className="!px-2.5 !py-1 text-xs"
                  >
                    Cancel
                  </Btn>
                </div>
              ) : null
            );
          }
          return row;
        })}
      />
    </Card>
  );
}

// Disposition Section
function DispositionSection({
  loadId,
  handoffs,
  records,
  dispositions,
  facilities,
  onChanged,
  canOperate = false,
}: {
  loadId: string;
  handoffs: Handoff[];
  records: ProcessingRecord[];
  dispositions: FinalDisposition[];
  facilities: FacilityCollection | null;
  onChanged: () => void;
  canOperate?: boolean;
}) {
  const completedHandoffs = handoffs.filter((h) => h.status === "COMPLETED");
  const completedRecords = records.filter((r) => r.status === "COMPLETED");
  const [open, setOpen] = useState(false);
  const [sourceKind, setSourceKind] = useState<"handoff" | "processing">("handoff");
  const [sourceId, setSourceId] = useState("");
  const [type, setType] = useState<DispositionType>("RECYCLING");
  const [dest, setDest] = useState("");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function recordDisposition() {
    setBusy(true);
    setErr(null);
    try {
      await api<FinalDisposition>("/final-dispositions", {
        body: {
          load_id: loadId,
          disposition_type: type,
          destination_facility_id: Number(dest),
          quantity_kg: Number(qty),
          ...(sourceKind === "handoff"
            ? { handoff_id: Number(sourceId) }
            : { processing_record_id: Number(sourceId) }),
        },
      });
      setOpen(false);
      setQty("");
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not record final disposition.");
    } finally {
      setBusy(false);
    }
  }

  async function act(id: number, action: "verify" | "cancel") {
    setBusy(true);
    setErr(null);
    try {
      if (action === "verify") {
        await api(`/final-dispositions/${id}/verify`, { method: "POST" });
      } else {
        await api(`/final-dispositions/${id}/cancel`, {
          body: { reason: "Cancelled from Digital Load journey screen" },
        });
      }
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not update disposition status.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      tone="ok"
      title="Final Disposition (Recovery, Recycling & Certified Landfill)"
      right={
        canOperate && (completedHandoffs.length > 0 || completedRecords.length > 0) ? (
          <Btn tone="ok" variant="outline" onClick={() => setOpen((v) => !v)}>
            {open ? "Close Form" : "Record Final Disposition"}
          </Btn>
        ) : undefined
      }
    >
      <p className="mb-3 text-xs text-ink-soft">
        A single load can legitimately produce multiple disposition records (e.g. recovered recyclables diverted to recycling facilities and residual fraction routed to engineered landfill).
      </p>

      {open && (
        <div className="mb-4 grid gap-3 rounded-xl border border-line bg-paper/60 p-4 sm:grid-cols-3">
          <Field label="Originating Source">
            <select
              className={inputCls}
              value={sourceKind}
              onChange={(e) => {
                setSourceKind(e.target.value as "handoff" | "processing");
                setSourceId("");
              }}
            >
              <option value="handoff">Completed Transfer Handoff</option>
              <option value="processing">Completed Processing Record (Direct)</option>
            </select>
          </Field>
          <Field label={sourceKind === "handoff" ? "Handoff Reference" : "Processing Batch Reference"}>
            <select
              className={inputCls}
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
            >
              <option value="">Select reference…</option>
              {sourceKind === "handoff"
                ? completedHandoffs.map((h) => (
                    <option key={h.id} value={h.id}>
                      Handoff #{h.id} · {h.waste_stream} · {h.quantity_kg} kg
                    </option>
                  ))
                : completedRecords.map((r) => (
                    <option key={r.id} value={r.id}>
                      Batch #{r.id} · Recovered: {r.recovered_quantity_kg}kg / Residual: {r.residual_quantity_kg}kg
                    </option>
                  ))}
            </select>
          </Field>
          <Field label="Disposition Type">
            <select
              className={inputCls}
              value={type}
              onChange={(e) => setType(e.target.value as DispositionType)}
            >
              {DISPOSITION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replaceAll("_", " ").toLowerCase()}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Destination Facility">
            <select
              className={inputCls}
              value={dest}
              onChange={(e) => setDest(e.target.value)}
            >
              <option value="">Select destination…</option>
              {facilityOptions(facilities).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Quantity (kg)">
            <input
              className={inputCls}
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 350"
            />
          </Field>
          <div className="flex items-end pt-2">
            <Btn
              tone="ok"
              busy={busy}
              disabled={!sourceId || !dest || !qty || busy}
              onClick={recordDisposition}
            >
              Record Disposition
            </Btn>
          </div>
        </div>
      )}

      {err && <div className="mb-4"><Notice tone="flag">{err}</Notice></div>}

      <Table
        head={[
          "Disposition #",
          "Disposition Type",
          "Destination",
          "Quantity",
          "Status",
          "Timestamp",
          "Verification",
        ]}
        empty="No final disposition records confirmed for this load."
        rows={dispositions.map((f) => [
          `#${f.id}`,
          f.disposition_type.replaceAll("_", " ").toLowerCase(),
          f.destination_facility ?? `Facility ${f.destination_facility_id}`,
          `${f.quantity_kg} kg`,
          <Badge key="b" tone={dispositionTone[f.status]}>
            {f.status}
          </Badge>,
          fmtDate(f.timestamp),
          f.status === "RECORDED" ? (
            !canOperate ? (
              <span key="v" className="text-xs font-semibold text-ink-soft">
                Pending Verification
              </span>
            ) : (
              <div key="a" className="flex items-center gap-2">
                <Btn
                  tone="ok"
                  busy={busy}
                  onClick={() => act(f.id, "verify")}
                  className="!px-2.5 !py-1 text-xs"
                >
                  Verify Disposition
                </Btn>
                <Btn
                  tone="neutral"
                  variant="outline"
                  busy={busy}
                  onClick={() => act(f.id, "cancel")}
                  className="!px-2.5 !py-1 text-xs"
                >
                  Cancel
                </Btn>
              </div>
            )
          ) : (
            <span key="v" className="text-xs font-semibold text-ok-700">
              Verified
            </span>
          ),
        ])}
      />
    </Card>
  );
}

// Exception Section
function ExceptionSection({
  loadId,
  records,
  handoffs,
  exceptions,
  facilities,
  onChanged,
  canRaise = false,
  canAuthorize = false,
}: {
  loadId: string;
  records: ProcessingRecord[];
  handoffs: Handoff[];
  exceptions: DisposalException[];
  facilities: FacilityCollection | null;
  onChanged: () => void;
  canRaise?: boolean;
  canAuthorize?: boolean;
}) {
  const completedRecords = records.filter((r) => r.status === "COMPLETED");
  const completedHandoffs = handoffs.filter((h) => h.status === "COMPLETED");
  const hasOpen = exceptions.some(
    (e) => e.status === "RAISED" || e.status === "PENDING_AUTHORIZATION"
  );
  const [open, setOpen] = useState(false);
  const [triggerKind, setTriggerKind] = useState<"processing" | "handoff">("processing");
  const [triggerId, setTriggerId] = useState("");
  const [origDest, setOrigDest] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function createException() {
    setBusy(true);
    setErr(null);
    try {
      await api<DisposalException>("/disposal-exceptions", {
        body: {
          load_id: loadId,
          original_destination_facility_id: Number(origDest),
          reason,
          ...(triggerKind === "processing"
            ? { source_processing_record_id: Number(triggerId) }
            : { source_handoff_id: Number(triggerId) }),
        },
      });
      setOpen(false);
      setReason("");
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not raise disposal exception.");
    } finally {
      setBusy(false);
    }
  }

  async function resolve(id: number) {
    setBusy(true);
    setErr(null);
    try {
      await api(`/disposal-exceptions/${id}/resolve`, { method: "POST" });
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not resolve disposal exception.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      tone="flag"
      title="Disposal Exceptions & Diversions"
      right={
        canRaise && (completedRecords.length > 0 || completedHandoffs.length > 0) && !hasOpen ? (
          <Btn tone="flag" variant="outline" onClick={() => setOpen((v) => !v)}>
            {open ? "Close Form" : "Raise Disposal Exception"}
          </Btn>
        ) : undefined
      }
    >
      <p className="mb-3 text-xs text-ink-soft">
        When a designated facility rejects material or exceeds capacity, an exception is formally raised. Once authorized by municipal administration, the material continues via an alternate destination handoff.
      </p>

      {hasOpen && (
        <p className="mb-3 text-xs text-flag-700 font-medium">
          An exception is currently open for this load awaiting authorization or alternate routing.
        </p>
      )}

      {open && (
        <div className="mb-4 grid gap-3 rounded-xl border border-line bg-paper/60 p-4 sm:grid-cols-3">
          <Field label="Triggered Event Type">
            <select
              className={inputCls}
              value={triggerKind}
              onChange={(e) => {
                setTriggerKind(e.target.value as "processing" | "handoff");
                setTriggerId("");
              }}
            >
              <option value="processing">Completed Processing Batch</option>
              <option value="handoff">Completed Transfer Handoff</option>
            </select>
          </Field>
          <Field label={triggerKind === "processing" ? "Processing Record" : "Handoff Reference"}>
            <select
              className={inputCls}
              value={triggerId}
              onChange={(e) => setTriggerId(e.target.value)}
            >
              <option value="">Select record…</option>
              {triggerKind === "processing"
                ? completedRecords.map((r) => (
                    <option key={r.id} value={r.id}>
                      Batch #{r.id}
                    </option>
                  ))
                : completedHandoffs.map((h) => (
                    <option key={h.id} value={h.id}>
                      Handoff #{h.id} · {h.waste_stream} · {h.quantity_kg} kg
                    </option>
                  ))}
            </select>
          </Field>
          <Field label="Original (Rejected) Destination">
            <select
              className={inputCls}
              value={origDest}
              onChange={(e) => setOrigDest(e.target.value)}
            >
              <option value="">Select facility…</option>
              {facilityOptions(facilities).map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="sm:col-span-3">
            <Field label="Justification / Exception Reason" hint="Minimum 10 characters required">
              <textarea
                className={inputCls}
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Detail reason for refusal or breakdown (e.g. Composting bay maintenance shutdown)"
              />
            </Field>
          </div>
          <div className="pt-2">
            <Btn
              tone="flag"
              busy={busy}
              disabled={!triggerId || !origDest || reason.trim().length < 10 || busy}
              onClick={createException}
            >
              Raise Exception
            </Btn>
          </div>
        </div>
      )}

      {err && <div className="mb-4"><Notice tone="flag">{err}</Notice></div>}

      <ul className="space-y-3">
        {exceptions.map((e) => (
          <li key={e.id} className="rounded-xl border border-line bg-paper/40 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-semibold text-ink text-sm">Exception #{e.id}</span>
              <Badge tone={exceptionTone[e.status]}>{e.status.replace("_", " ")}</Badge>
            </div>
            <p className="mt-1.5 text-xs text-ink-soft">{e.reason}</p>
            <div className="mt-2 text-xs text-ink">
              <span className="text-ink-soft">Original Destination:</span>{" "}
              <span className="font-medium">
                {e.original_destination_facility ?? `Facility ${e.original_destination_facility_id}`}
              </span>
              {e.alternative_destination_facility && (
                <>
                  {" "}
                  &rarr; <span className="text-ink-soft">Alternative Routing:</span>{" "}
                  <span className="font-bold text-proc-700">{e.alternative_destination_facility}</span>
                </>
              )}
            </div>
            {canAuthorize && e.status === "RAISED" && (
              <AuthorizeForm
                exceptionId={e.id}
                facilities={facilities}
                busy={busy}
                setBusy={setBusy}
                setErr={setErr}
                onChanged={onChanged}
              />
            )}
            {e.resulting_handoff_id && (
              <p className="mt-2 text-xs text-ink-soft">
                Resulting Alternate Handoff: <span className="font-mono font-semibold">#{e.resulting_handoff_id}</span>
              </p>
            )}
            {canRaise && e.status === "AUTHORIZED" && (
              <div className="mt-3">
                <Btn
                  tone="ok"
                  busy={busy}
                  onClick={() => resolve(e.id)}
                  className="!px-3 !py-1.5 text-xs"
                >
                  Mark Exception Resolved (Transfer Complete)
                </Btn>
              </div>
            )}
          </li>
        ))}
        {exceptions.length === 0 && (
          <p className="py-2 text-xs text-ink-soft">No disposal exceptions logged on this load.</p>
        )}
      </ul>
    </Card>
  );
}

function AuthorizeForm({
  exceptionId,
  facilities,
  busy,
  setBusy,
  setErr,
  onChanged,
}: {
  exceptionId: number;
  facilities: FacilityCollection | null;
  busy: boolean;
  setBusy: (b: boolean) => void;
  setErr: (e: string | null) => void;
  onChanged: () => void;
}) {
  const [alt, setAlt] = useState("");
  const [source, setSource] = useState("");
  const [stream, setStream] = useState<WasteStream>("RECOVERED");
  const [qty, setQty] = useState("");

  async function authorize() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/disposal-exceptions/${exceptionId}/authorize`, {
        body: {
          alternative_destination_facility_id: Number(alt),
          source_facility_id: Number(source),
          waste_stream: stream,
          quantity_kg: Number(qty),
        },
      });
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not authorize alternative routing.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 grid gap-2.5 rounded-xl border border-line bg-white p-3 sm:grid-cols-4">
      <select
        className={inputCls}
        value={alt}
        onChange={(e) => setAlt(e.target.value)}
      >
        <option value="">Alternative destination…</option>
        {facilityOptions(facilities).map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
      <select
        className={inputCls}
        value={source}
        onChange={(e) => setSource(e.target.value)}
      >
        <option value="">Current location…</option>
        {facilityOptions(facilities).map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
      <select
        className={inputCls}
        value={stream}
        onChange={(e) => setStream(e.target.value as WasteStream)}
      >
        <option value="RECOVERED">RECOVERED</option>
        <option value="RESIDUAL">RESIDUAL</option>
      </select>
      <div className="flex gap-2">
        <input
          className={inputCls}
          inputMode="numeric"
          placeholder="kg"
          value={qty}
          onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))}
        />
        <Btn
          tone="proc"
          busy={busy}
          disabled={!alt || !source || !qty || busy}
          onClick={authorize}
          className="!px-3 text-xs"
        >
          Authorize
        </Btn>
      </div>
    </div>
  );
}
