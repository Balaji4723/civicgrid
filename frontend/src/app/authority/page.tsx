"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  FileCheck2,
  Package,
  RotateCcw,
  Scale,
  ScanSearch,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { api, ApiError, session } from "@/lib/api";
import { useLoad } from "@/lib/hooks";
import { cleanLabel, getSubnavForUser, getUserCapability } from "@/lib/nav";
import type {
  Discrepancy,
  DisposalException,
  FinalDisposition,
  Handoff,
  LoadDetail,
  LoadRow,
  ProcessingRecord,
} from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Field,
  inputCls,
  Kpi,
  LoadBadge,
  Notice,
  Spinner,
  StatusBadge,
} from "@/components/ui";
import { Shell } from "@/components/Shell";

interface ReceiveResult {
  cross_check_result: "MATCH" | "FLAGGED";
  note: string;
  discrepancies: Discrepancy[];
}

export default function AuthorityOverview() {
  const router = useRouter();
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);

  useEffect(() => {
    if (cap === "RECEIVING") {
      router.replace("/receiving");
    } else if (cap === "PROCESSING") {
      router.replace("/authority/processing");
    } else if (cap === "INDEPENDENT_VERIFIER") {
      router.replace("/audits");
    }
  }, [cap, router]);

  const [input, setInput] = useState("");
  const [loadId, setLoadId] = useState<string | null>(null);

  const detail = useLoad(() => api<LoadDetail>(`/loads/${loadId}`), [loadId], !!loadId);

  // Real operational counts from verified backend records
  const loads = useLoad(() => api<LoadRow[]>("/loads"));
  const discs = useLoad(() => api<Discrepancy[]>("/discrepancy"));
  const processing = useLoad(() => api<ProcessingRecord[]>("/processing"));
  const handoffs = useLoad(() => api<Handoff[]>("/handoffs"));
  const exceptions = useLoad(() => api<DisposalException[]>("/disposal-exceptions"));
  const dispositions = useLoad(() => api<FinalDisposition[]>("/final-dispositions"));

  // Weighbridge inputs (Gross - Tare = Net, or direct Net)
  const [grossWeight, setGrossWeight] = useState("8720");
  const [tareWeight, setTareWeight] = useState("8330");
  const [useWeighbridgeCalculator, setUseWeighbridgeCalculator] = useState(true);
  const [netQty, setNetQty] = useState("390");
  const [cond, setCond] = useState<"ACCEPTABLE" | "UNACCEPTABLE">("ACCEPTABLE");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ReceiveResult | null>(null);

  const calculatedNet = useWeighbridgeCalculator && Number(grossWeight) > Number(tareWeight)
    ? Number(grossWeight) - Number(tareWeight)
    : Number(netQty) || 0;

  function lookup(id: string) {
    const clean = id.trim().toUpperCase();
    setLoadId(clean);
    setResult(null);
    setErr(null);
  }

  async function submitReceiving() {
    if (!loadId) return;
    const effectiveQty = calculatedNet;
    if (effectiveQty <= 0) {
      setErr("Please specify a valid net received quantity greater than 0 kg.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await api<ReceiveResult>(`/loads/${loadId}/receiving`, {
        body: { quantity: effectiveQty, condition: cond },
      });
      setResult(res);
      await Promise.all([detail.reload(), loads.reload(), discs.reload()]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to record receiving measurement.");
    } finally {
      setBusy(false);
    }
  }

  const d = detail.data;
  const incoming = loads.data?.filter((l) => l.status === "DECLARED").length ?? "-";
  const openDiscs = discs.data?.filter((x) => x.status !== "CLOSED").length ?? "-";
  const activeProcessing = processing.data?.filter((p) => p.status === "IN_PROGRESS").length ?? "-";
  const openHandoffs = handoffs.data?.filter((h) => h.status === "PENDING" || h.status === "IN_TRANSIT").length ?? "-";
  const openExceptions = exceptions.data?.filter((e) => e.status === "RAISED" || e.status === "PENDING_AUTHORIZATION" || e.status === "AUTHORIZED").length ?? "-";
  const verifiedDispositions = dispositions.data?.filter((f) => f.status === "VERIFIED").length ?? "-";

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="auth"
      title="Receiving & Verification Operations"
      subtitle="Intake incoming collection loads, record weighbridge receiving measurements, execute automated cross-checks, and manage downstream processing."
      subnav={getSubnavForUser(me)}
    >
      {/* Real Operational Metrics */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Incoming Loads" value={incoming} tone="track" />
        <Kpi label="Open Discrepancies" value={openDiscs} tone="flag" />
        <Kpi label="Processing Active" value={activeProcessing} tone="proc" />
        <Kpi label="Open Handoffs" value={openHandoffs} tone="track" />
        <Kpi label="Disposal Exceptions" value={openExceptions} tone="flag" />
        <Kpi label="Dispositions Verified" value={verifiedDispositions} tone="ok" />
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Main Column: Load Lookup & Receiving Cross-Check */}
        <div className="space-y-6 lg:col-span-7">
          <Card tone="auth" title="Receiving Bay & Intake Verification">
            <form
              className="flex flex-col sm:flex-row gap-2.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (input.trim()) lookup(input);
              }}
            >
              <div className="relative flex-1">
                <input
                  aria-label="Digital Load ID"
                  className={`${inputCls} font-mono uppercase`}
                  placeholder="Enter Digital Load ID (e.g. DL-1002)"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                />
              </div>
              <Btn tone="auth" type="submit" className="shrink-0">
                <ScanSearch className="h-4 w-4" />
                Find Digital Load
              </Btn>
            </form>
          </Card>

          {detail.error && <Notice tone="flag" title="Lookup Failed">{detail.error}</Notice>}
          {loadId && detail.loading && !d && <Spinner label="Retrieving Digital Load details" />}

          {d && (
            <>
              {/* Load Overview Summary */}
              <Card
                title={
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-lg font-bold">{d.id}</span>
                  </div>
                }
                right={
                  <div className="flex items-center gap-3">
                    <LoadBadge status={d.status} />
                    <Link
                      href={`/authority/load/${d.id}`}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-auth-700 hover:underline"
                    >
                      Full Life Cycle &rarr;
                    </Link>
                  </div>
                }
              >
                <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3 lg:grid-cols-5">
                  <div className="rounded-lg bg-paper/60 p-2.5 border border-line/60">
                    <dt className="text-xs text-ink-soft">Ward Jurisdiction</dt>
                    <dd className="font-semibold text-ink mt-0.5">{cleanLabel(d.ward)}</dd>
                  </div>
                  <div className="rounded-lg bg-paper/60 p-2.5 border border-line/60">
                    <dt className="text-xs text-ink-soft">Collection Vehicle</dt>
                    <dd className="font-bold text-ink mt-0.5">{d.vehicle_registration ?? "Assigned Fleet"}</dd>
                  </div>
                  <div className="rounded-lg bg-paper/60 p-2.5 border border-line/60">
                    <dt className="text-xs text-ink-soft">Collection Trip</dt>
                    <dd className="font-mono font-semibold text-ink mt-0.5">{d.trip_code ?? "—"}</dd>
                  </div>
                  <div className="rounded-lg bg-paper/60 p-2.5 border border-line/60">
                    <dt className="text-xs text-ink-soft">Households Serviced</dt>
                    <dd className="font-semibold text-ink mt-0.5">
                      {d.declaration.households_collected} ({d.declaration.segregated} seg.)
                    </dd>
                  </div>
                  <div className="rounded-lg bg-paper/60 p-2.5 border border-line/60">
                    <dt className="text-xs text-ink-soft">Receiving Status</dt>
                    <dd className="font-semibold text-track-700 mt-0.5">
                      {d.receiving?.quantity != null ? `${d.receiving.quantity} kg (Weighed)` : "Pending Intake"}
                    </dd>
                  </div>
                </dl>
              </Card>

              {/* Receiving Verification Action Card */}
              {d.status === "DECLARED" && (
                <Card tone="auth" title="Weighbridge / Receiving Measurement">
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-ink-soft">
                        Record authoritative intake measurement at receiving facility weighbridge.
                      </p>
                      <button
                        type="button"
                        onClick={() => setUseWeighbridgeCalculator(!useWeighbridgeCalculator)}
                        className="text-xs font-semibold text-auth-700 hover:underline"
                      >
                        {useWeighbridgeCalculator ? "Switch to Direct Net Weight" : "Use Gross / Tare Weighbridge"}
                      </button>
                    </div>

                    {useWeighbridgeCalculator ? (
                      <div className="rounded-xl border border-line/60 bg-paper/50 p-3.5 space-y-3">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <Field label="Loaded Vehicle Gross Weight (kg)">
                            <input
                              className={inputCls}
                              inputMode="numeric"
                              value={grossWeight}
                              onChange={(e) => setGrossWeight(e.target.value.replace(/\D/g, ""))}
                              placeholder="e.g. 8720"
                            />
                          </Field>
                          <Field label="Empty Vehicle Tare Weight (kg)">
                            <input
                              className={inputCls}
                              inputMode="numeric"
                              value={tareWeight}
                              onChange={(e) => setTareWeight(e.target.value.replace(/\D/g, ""))}
                              placeholder="e.g. 8330"
                            />
                          </Field>
                        </div>
                        <div className="flex items-center justify-between rounded-lg bg-auth-50/80 px-3 py-2 text-xs">
                          <span className="font-semibold text-auth-800">Net Received Waste Quantity:</span>
                          <span className="font-mono text-sm font-bold text-auth-900">
                            {calculatedNet} kg
                          </span>
                        </div>
                      </div>
                    ) : (
                      <Field label="Net Receiving Measurement (kg)">
                        <input
                          className={inputCls}
                          inputMode="numeric"
                          value={netQty}
                          onChange={(e) => setNetQty(e.target.value.replace(/\D/g, ""))}
                          placeholder="e.g. 390"
                        />
                      </Field>
                    )}

                    <Field label="Waste Stream Condition on Arrival">
                      <select
                        className={inputCls}
                        value={cond}
                        onChange={(e) => setCond(e.target.value as typeof cond)}
                      >
                        <option value="ACCEPTABLE">Acceptable (Meets Segregation Standard)</option>
                        <option value="UNACCEPTABLE">Unacceptable (Severe Contamination / Mixed)</option>
                      </select>
                    </Field>

                    <div className="flex flex-col sm:flex-row sm:items-center gap-3 pt-2">
                      <Btn
                        tone="auth"
                        busy={busy}
                        disabled={calculatedNet <= 0 || busy}
                        onClick={submitReceiving}
                      >
                        <Scale className="h-4 w-4" />
                        Record Receiving Measurement & Run Cross-Check
                      </Btn>
                      <span className="text-xs text-ink-soft">
                        CivicGrid cross-checks the chain rather than trusting a single record.
                      </span>
                    </div>

                    {err && <Notice tone="flag">{err}</Notice>}
                  </div>
                </Card>
              )}

              {/* Cross-Check Engine Result Notice */}
              {result && (
                <Notice
                  tone={result.cross_check_result === "MATCH" ? "ok" : "flag"}
                  title={
                    result.cross_check_result === "MATCH"
                      ? "Cross-Check Matched: Verified"
                      : "Quantity Discrepancy Detected — Flagged for Independent Verification"
                  }
                >
                  <p className="text-xs">
                    {result.cross_check_result === "MATCH"
                      ? "Receiving weighbridge measurement is consistent with collection parameters. Status updated to VERIFIED."
                      : "Quantity discrepancy detected between collection trail records and facility receiving measurement. Flagged for review; awaiting independent verification."}
                  </p>
                  {result.discrepancies.length > 0 && (
                    <div className="mt-3">
                      <Link
                        href={`/authority/discrepancy/${result.discrepancies[0].id}`}
                        className="inline-flex items-center gap-1 text-xs font-bold text-auth-700 underline"
                      >
                        Open Independent Verification Workflow #{result.discrepancies[0].id} &rarr;
                      </Link>
                    </div>
                  )}
                </Notice>
              )}
            </>
          )}

          {/* Quick Jump: Incoming Loads Table */}
          <Card
            title="Awaiting Receiving / In-Transit"
            right={
              <Link href="/authority/loads" className="text-xs font-semibold text-auth-700 hover:underline">
                View All Loads &rarr;
              </Link>
            }
          >
            {loads.data && (
              <div className="space-y-2">
                {loads.data
                  .filter((l) => l.status === "DECLARED")
                  .slice(0, 5)
                  .map((l) => (
                    <div
                      key={l.id}
                      className="flex items-center justify-between rounded-xl bg-paper/60 p-3 border border-line/60 hover:bg-paper cursor-pointer transition-colors"
                      onClick={() => lookup(l.id)}
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-auth-50 text-auth-700">
                          <Truck className="h-4 w-4" />
                        </div>
                        <div>
                          <p className="font-mono text-xs font-bold text-ink">{l.id}</p>
                          <p className="text-[11px] text-ink-soft">
                            {l.vehicle_registration ?? "Assigned Vehicle"} • {cleanLabel(l.ward)}
                          </p>
                        </div>
                      </div>
                      <Btn tone="auth" className="!px-2.5 !py-1 text-xs" onClick={() => lookup(l.id)}>
                        Select for Intake &rarr;
                      </Btn>
                    </div>
                  ))}
                {loads.data.filter((l) => l.status === "DECLARED").length === 0 && (
                  <p className="py-4 text-center text-xs text-ink-soft">No loads currently awaiting receiving intake.</p>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Right Column: Operational Workflows */}
        <div className="space-y-6 lg:col-span-5">
          <Card title="Receiving & Facility Workflows">
            <div className="divide-y divide-line/60">
              <Link
                href="/authority/loads"
                className="flex items-center justify-between py-3 hover:bg-paper/50 rounded-lg px-2 -mx-2 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <Package className="h-4 w-4 text-track-600" />
                  <div>
                    <p className="text-xs font-semibold text-ink">Incoming Loads Register</p>
                    <p className="text-[11px] text-ink-soft">Review collection trips and vehicle batches</p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-ink-soft" />
              </Link>

              <Link
                href="/audits"
                className="flex items-center justify-between py-3 hover:bg-paper/50 rounded-lg px-2 -mx-2 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <ShieldCheck className="h-4 w-4 text-ok-600" />
                  <div>
                    <p className="text-xs font-semibold text-ink">Independent Verification Center</p>
                    <p className="text-[11px] text-ink-soft">Execute and review independent verification runs</p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-ink-soft" />
              </Link>

              <Link
                href="/authority/discrepancies"
                className="flex items-center justify-between py-3 hover:bg-paper/50 rounded-lg px-2 -mx-2 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <AlertTriangle className="h-4 w-4 text-flag-600" />
                  <div>
                    <p className="text-xs font-semibold text-ink">Discrepancy Investigation</p>
                    <p className="text-[11px] text-ink-soft">Corroborate, investigate, and resolve quantity flags</p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-ink-soft" />
              </Link>

              <Link
                href="/authority/processing"
                className="flex items-center justify-between py-3 hover:bg-paper/50 rounded-lg px-2 -mx-2 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <RotateCcw className="h-4 w-4 text-proc-600" />
                  <div>
                    <p className="text-xs font-semibold text-ink">Material Processing Operations</p>
                    <p className="text-[11px] text-ink-soft">Composting, recycling, and material recovery</p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-ink-soft" />
              </Link>

              <Link
                href="/authority/handoffs"
                className="flex items-center justify-between py-3 hover:bg-paper/50 rounded-lg px-2 -mx-2 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <Truck className="h-4 w-4 text-track-600" />
                  <div>
                    <p className="text-xs font-semibold text-ink">Inter-Facility Handoffs</p>
                    <p className="text-[11px] text-ink-soft">Track chain of custody transfers</p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-ink-soft" />
              </Link>

              <Link
                href="/authority/final-dispositions"
                className="flex items-center justify-between py-3 hover:bg-paper/50 rounded-lg px-2 -mx-2 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <CheckCircle2 className="h-4 w-4 text-ok-600" />
                  <div>
                    <p className="text-xs font-semibold text-ink">Final Disposition Records</p>
                    <p className="text-[11px] text-ink-soft">Verifiable end-state landfill and recovery logs</p>
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-ink-soft" />
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </Shell>
  );
}
