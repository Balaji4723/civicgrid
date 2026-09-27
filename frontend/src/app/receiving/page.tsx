"use client";
import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  Package,
  RotateCcw,
  Scale,
  ShieldCheck,
  Truck,
  Users,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { cleanLabel } from "@/lib/nav";
import type { Discrepancy, LoadDetail, LoadRow } from "@/lib/types";
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
  Table,
} from "@/components/ui";
import { Shell } from "@/components/Shell";

interface ReceiveResult {
  cross_check_result: "MATCH" | "FLAGGED";
  note: string;
  discrepancies: Discrepancy[];
}

export default function ReceivingOperationsPage() {
  const loads = useLoad(() => api<LoadRow[]>("/loads"));
  const [selectedLoadId, setSelectedLoadId] = useState<string | null>(null);
  const detail = useLoad(() => api<LoadDetail>(`/loads/${selectedLoadId}`), [selectedLoadId], !!selectedLoadId);

  // Weighbridge inputs (Gross - Tare = Net)
  const [grossWeight, setGrossWeight] = useState("8720");
  const [tareWeight, setTareWeight] = useState("8330");
  const [useWeighbridgeCalc, setUseWeighbridgeCalc] = useState(true);
  const [netQty, setNetQty] = useState("390");
  const [cond, setCond] = useState<"ACCEPTABLE" | "UNACCEPTABLE">("ACCEPTABLE");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ReceiveResult | null>(null);

  const calculatedNet = useWeighbridgeCalc && Number(grossWeight) > Number(tareWeight)
    ? Number(grossWeight) - Number(tareWeight)
    : Number(netQty) || 0;

  // Filter loads
  const incomingLoads = (loads.data ?? []).filter((l) => l.status === "DECLARED");
  const receivedLoads = (loads.data ?? []).filter((l) => l.status !== "COLLECTING" && l.status !== "DECLARED");

  // Auto-select first incoming load if none selected
  const activeLoad = detail.data ?? (incomingLoads.length > 0 ? null : null);
  const activeLoadId = selectedLoadId || (incomingLoads.length > 0 ? incomingLoads[0].id : null);

  function selectLoad(id: string) {
    setSelectedLoadId(id);
    setResult(null);
    setErr(null);
  }

  async function handleRecordReceiving() {
    const targetId = activeLoadId;
    if (!targetId) {
      setErr("Please select an incoming Digital Load for weighbridge intake.");
      return;
    }
    if (calculatedNet <= 0) {
      setErr("Please specify a valid net received quantity greater than 0 kg.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await api<ReceiveResult>(`/loads/${targetId}/receiving`, {
        body: { quantity: calculatedNet, condition: cond },
      });
      setResult(res);
      await Promise.all([detail.reload(), loads.reload()]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to record receiving measurement.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="track"
      title="RECEIVING & WEIGHBRIDGE"
      subtitle="Physical intake, weighbridge measurement, stream condition and automated cross-checks."
    >
      {/* Operational KPIs */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Awaiting Intake" value={incomingLoads.length} tone={incomingLoads.length > 0 ? "track" : "neutral"} />
        <Kpi label="Weighbridge Active" value={detail.data ? "Connected" : "Standby"} tone="ok" />
        <Kpi label="Received Loads" value={receivedLoads.length} tone="auth" />
        <Kpi label="Total Registered Loads" value={loads.data?.length ?? 0} tone="proc" />
      </div>

      {err && (
        <div className="mb-4">
          <Notice tone="flag" title="Intake Error">
            {err}
          </Notice>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Left Column: Weighbridge Intake Terminal */}
        <div className="space-y-6 lg:col-span-7">
          <Card tone="track" title="Weighbridge Intake Terminal">
            {/* Arriving Vehicle & Load Identification */}
            <div className="space-y-4">
              <div className="rounded-xl border border-line bg-paper/60 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-track-600 text-white shadow-xs">
                      <Truck className="h-6 w-6" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold text-ink-soft">Selected Load for Intake</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="font-mono text-lg font-bold text-ink">
                          {activeLoadId ?? "No load selected"}
                        </span>
                        {detail.data && <LoadBadge status={detail.data.status} />}
                      </div>
                    </div>
                  </div>

                  {incomingLoads.length > 0 && (
                    <div className="text-right">
                      <label className="text-[11px] font-semibold text-ink-soft block mb-1">Select Incoming Load</label>
                      <select
                        aria-label="Select incoming load for receiving"
                        className="rounded-lg border border-line bg-white px-2.5 py-1 text-xs font-mono font-semibold text-ink"
                        value={activeLoadId ?? ""}
                        onChange={(e) => selectLoad(e.target.value)}
                      >
                        {incomingLoads.map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.id} ({l.vehicle_registration ?? "Fleet"} • {l.trip_code ?? "CT"})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                {detail.data && (
                  <div className="mt-4 pt-4 border-t border-line/60 grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
                    <div>
                      <span className="text-ink-soft block">Arriving Vehicle</span>
                      <span className="font-bold text-ink mt-0.5 block">{detail.data.vehicle_registration ?? "MH-01-AB-1234"}</span>
                    </div>
                    <div>
                      <span className="text-ink-soft block">Collection Trip</span>
                      <span className="font-mono font-bold text-ink mt-0.5 block">{detail.data.trip_code ?? "—"}</span>
                    </div>
                    <div>
                      <span className="text-ink-soft block">Route / Ward</span>
                      <span className="font-bold text-ink mt-0.5 block">{cleanLabel(detail.data.ward)}</span>
                    </div>
                    <div>
                      <span className="text-ink-soft block">Collection Crew</span>
                      <span className="font-semibold text-ink mt-0.5 block">
                        {detail.data.crew && detail.data.crew.length > 0
                          ? detail.data.crew.map((c) => c.name).join(", ")
                          : detail.data.worker ?? "Field Crew"}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* Weighbridge Measurement Inputs */}
              <div className="rounded-xl border border-line bg-paper/40 p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Scale className="h-4 w-4 text-track-600" />
                    <span className="text-xs font-bold uppercase tracking-wider text-ink">
                      Intake Weight Measurement
                    </span>
                  </div>
                  <label className="flex items-center gap-2 text-xs font-medium text-ink-soft cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useWeighbridgeCalc}
                      onChange={(e) => setUseWeighbridgeCalc(e.target.checked)}
                      className="rounded border-line text-track-600 focus:ring-track-500"
                    />
                    Use Gross / Tare Calculator
                  </label>
                </div>

                {useWeighbridgeCalc ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Field label="Gross Weight (kg)">
                      <input
                        aria-label="Gross weight in kilograms"
                        type="number"
                        className={inputCls}
                        value={grossWeight}
                        onChange={(e) => setGrossWeight(e.target.value)}
                        placeholder="8720"
                      />
                    </Field>
                    <Field label="Tare Weight (kg)">
                      <input
                        aria-label="Tare weight in kilograms"
                        type="number"
                        className={inputCls}
                        value={tareWeight}
                        onChange={(e) => setTareWeight(e.target.value)}
                        placeholder="8330"
                      />
                    </Field>
                    <Field label="Net Weight (Calculated)">
                      <div className="flex h-10 items-center rounded-xl bg-track-50 px-3.5 font-mono text-base font-bold text-track-800 border border-track-200">
                        {calculatedNet.toLocaleString()} kg
                      </div>
                    </Field>
                  </div>
                ) : (
                  <Field label="Direct Net Weight (kg)">
                    <input
                      aria-label="Direct net weight in kilograms"
                      type="number"
                      className={inputCls}
                      value={netQty}
                      onChange={(e) => setNetQty(e.target.value)}
                      placeholder="390"
                    />
                  </Field>
                )}

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-2 border-t border-line/40">
                  <Field label="Observed Waste Stream">
                    <select
                      aria-label="Observed waste stream"
                      className={inputCls}
                      defaultValue="WET_ORGANIC"
                    >
                      <option value="WET_ORGANIC">Wet Organic / Biodegradable</option>
                      <option value="DRY_RECYCLABLE">Dry Recyclable</option>
                      <option value="DOMESTIC_HAZARDOUS">Domestic Hazardous</option>
                      <option value="MIXED_SOLID_WASTE">Mixed Solid Waste</option>
                    </select>
                  </Field>
                  <Field label="Physical Condition">
                    <select
                      aria-label="Physical condition"
                      className={inputCls}
                      value={cond}
                      onChange={(e) => setCond(e.target.value as "ACCEPTABLE" | "UNACCEPTABLE")}
                    >
                      <option value="ACCEPTABLE">ACCEPTABLE — Segregated standard met</option>
                      <option value="UNACCEPTABLE">UNACCEPTABLE — Contamination / Waterlogged</option>
                    </select>
                  </Field>
                </div>

                <div className="pt-2">
                  <Btn
                    className="w-full justify-center !py-3 text-sm font-bold"
                    tone="track"
                    busy={busy}
                    disabled={!activeLoadId || detail.data?.status !== "DECLARED"}
                    onClick={handleRecordReceiving}
                  >
                    <Scale className="mr-2 h-4 w-4" />
                    Record Weighbridge Intake & Execute Cross-Check ({calculatedNet} kg)
                  </Btn>
                  {detail.data && detail.data.status !== "DECLARED" && (
                    <p className="mt-2 text-center text-xs text-ink-soft">
                      This load is currently <strong className="font-semibold">{detail.data.status}</strong>. Only loads in AWAITING RECEIVING (DECLARED) can be received.
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Cross-Check Engine Execution Result */}
            {result && (
              <div className="mt-6 rounded-2xl border-2 border-auth-300 bg-auth-50/80 p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-auth-600 text-white">
                      <FileCheck2 className="h-5 w-5" />
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-ink">Automated Cross-Check Execution</h4>
                      <p className="text-xs text-ink-soft">Comparison of collection declaration vs weighbridge measurement</p>
                    </div>
                  </div>
                  <Badge tone={result.cross_check_result === "MATCH" ? "ok" : "flag"}>
                    {result.cross_check_result === "MATCH" ? "MATCH" : "FLAGGED"}
                  </Badge>
                </div>

                <p className="text-xs text-ink leading-relaxed">
                  {result.note}
                </p>

                {result.discrepancies.length > 0 && (
                  <div className="rounded-xl bg-white p-3 border border-line space-y-2">
                    <p className="text-xs font-bold text-flag-700">Flagged Discrepancy Records:</p>
                    {result.discrepancies.map((d) => (
                      <div key={d.id} className="flex items-center justify-between text-xs">
                        <span className="font-mono font-semibold text-ink">Discrepancy #{d.id} ({d.type})</span>
                        <Link
                          href={`/authority/discrepancy/${d.id}`}
                          className="font-semibold text-auth-700 underline hover:text-auth-800"
                        >
                          View in Authority Center \u2192
                        </Link>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Right Column: Incoming Loads Queue */}
        <div className="space-y-6 lg:col-span-5">
          <Card
            title={`Incoming Loads Queue (${incomingLoads.length})`}
            right={<span className="text-xs text-ink-soft">Awaiting Weighbridge Intake</span>}
          >
            {loads.loading && !loads.data && <Spinner label="Loading incoming loads queue" />}
            {incomingLoads.length === 0 && !loads.loading && (
              <div className="py-8 text-center text-xs text-ink-soft">
                <CheckCircle2 className="mx-auto h-8 w-8 text-ok-600 mb-2" />
                <p className="font-semibold text-ink">No loads currently awaiting receiving intake.</p>
                <p className="mt-1">Completed collection trips from field workers appear here automatically.</p>
              </div>
            )}
            {incomingLoads.length > 0 && (
              <div className="divide-y divide-line/60">
                {incomingLoads.map((l) => {
                  const isSelected = l.id === activeLoadId;
                  return (
                    <div
                      key={l.id}
                      onClick={() => selectLoad(l.id)}
                      className={`p-3.5 rounded-xl cursor-pointer transition-colors ${
                        isSelected ? "bg-track-50/80 border border-track-300" : "hover:bg-paper-subtle"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-bold text-ink">{l.id}</span>
                            <LoadBadge status={l.status} />
                          </div>
                          <p className="text-xs font-semibold text-ink mt-1">
                            {l.vehicle_registration ?? "MH-01-AB-1234"} • <span className="font-mono text-ink-soft">{l.trip_code ?? "—"}</span>
                          </p>
                          <p className="text-[11px] text-ink-soft mt-0.5">
                            Route: {cleanLabel(l.ward)} • Operator: {l.worker ?? "Crew"}
                          </p>
                        </div>
                        <Btn
                          className="!px-2.5 !py-1 text-xs"
                          tone={isSelected ? "track" : "neutral"}
                          onClick={() => selectLoad(l.id)}
                        >
                          {isSelected ? "Active Intake" : "Select"}
                        </Btn>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Receiving History */}
          <Card
            title="Recent Receiving Records"
            right={
              <Link href="/authority/loads" className="text-xs font-semibold text-auth-700 underline hover:text-auth-800">
                View All Loads \u2192
              </Link>
            }
          >
            {receivedLoads.length === 0 ? (
              <p className="text-xs text-ink-soft py-4 text-center">No completed receiving records yet.</p>
            ) : (
              <div className="divide-y divide-line/60 text-xs">
                {receivedLoads.slice(0, 5).map((l) => (
                  <div key={l.id} className="py-2.5 flex items-center justify-between">
                    <div>
                      <span className="font-mono font-bold text-ink">{l.id}</span>
                      <span className="text-ink-soft ml-2">{l.vehicle_registration ?? "Fleet"}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <LoadBadge status={l.status} />
                      <Link
                        href={`/authority/load/${l.id}`}
                        className="text-auth-700 underline hover:text-auth-800"
                      >
                        Details
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </Shell>
  );
}
