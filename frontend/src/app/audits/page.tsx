"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import {
  ClipboardCheck,
  Dices,
  FileCheck2,
  FlaskConical,
  Gauge,
  Play,
  Plus,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { api, ApiError, session } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";
import type {
  AuditConfig,
  AuditMethod,
  AuditRow,
  AuditStatus,
  SelectionResult,
} from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Field,
  inputCls,
  Kpi,
  Notice,
  Spinner,
  StatusBadge,
} from "@/components/ui";
import { AuditStatusBadge, MethodBadge } from "@/components/AuditBadges";
import { Shell } from "@/components/Shell";

const STATUSES: AuditStatus[] = ["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"];
const METHODS: AuditMethod[] = ["RANDOM", "RISK_BASED", "MANUAL"];
const TARGET_TYPES = [
  { id: "ALL", label: "All Audit Targets" },
  { id: "DIGITAL_LOAD", label: "Digital Load Verifications" },
  { id: "COLLECTION_EVENT", label: "Collection Event Audits" },
] as const;

function AuditCenterContent() {
  const searchParams = useSearchParams();
  const qLoad = searchParams.get("load_id") ?? "";
  const qReason = searchParams.get("reason") ?? "";

  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isAdmin = me?.role === "MUNICIPAL_ADMIN";
  const isVerifier = cap === "INDEPENDENT_VERIFIER";
  const isReceiving = cap === "RECEIVING";
  const isProcessing = cap === "PROCESSING";

  const [status, setStatus] = useState<AuditStatus | "ALL">("ALL");
  const [method, setMethod] = useState<AuditMethod | "ALL">("ALL");
  const [targetType, setTargetType] = useState<"ALL" | "DIGITAL_LOAD" | "COLLECTION_EVENT">("ALL");
  const qs = [
    status !== "ALL" ? `status=${status}` : "",
    method !== "ALL" ? `method=${method}` : "",
    targetType !== "ALL" ? `target_type=${targetType}` : "",
  ]
    .filter(Boolean)
    .join("&");
  const audits = useLoad(
    () => api<AuditRow[]>(`/audit-center/audits${qs ? `?${qs}` : ""}`),
    [qs]
  );
  const all = useLoad(() => api<AuditRow[]>("/audit-center/audits"));
  const config = useLoad(() => api<AuditConfig>("/audit-center/config"));

  const [mode, setMode] = useState<"RANDOM" | "RISK_BASED" | "MANUAL">(qLoad ? "MANUAL" : "RISK_BASED");
  const [pct, setPct] = useState("");
  const [seed, setSeed] = useState("");
  const [thr, setThr] = useState("");
  const [max, setMax] = useState("");
  const [loadId, setLoadId] = useState(qLoad);
  const [reason, setReason] = useState(qReason || (qLoad ? `Independent physical inspection for ${qLoad} discrepancy.` : ""));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<SelectionResult | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const rows = all.data ?? [];
  const count = (f: (a: AuditRow) => boolean) => rows.filter(f).length;

  async function runSelection(dry: boolean) {
    setBusy(true);
    setErr(null);
    setCreated(null);
    try {
      const body: Record<string, unknown> = { method: mode, dry_run: dry };
      if (mode === "RANDOM") {
        if (pct) body.random_sample_pct = Number(pct);
        if (seed) body.seed = Number(seed);
      } else {
        if (thr) body.risk_threshold = Number(thr);
        if (max) body.risk_max_selected = Number(max);
      }
      const r = await api<SelectionResult>("/audit-center/selection-runs", { body });
      if (dry) {
        setPreview(r);
      } else {
        setPreview(null);
        setCreated(
          `Selection Run #${r.run_id} executed: ${r.selected_count} of ${r.eligible_count} eligible loads selected${
            r.seed != null ? ` (PRNG seed: ${r.seed})` : ""
          }.`
        );
        await Promise.all([audits.reload(), all.reload()]);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Selection run execution failed.");
    } finally {
      setBusy(false);
    }
  }

  async function createManualAudit() {
    setBusy(true);
    setErr(null);
    setCreated(null);
    try {
      const a = await api<AuditRow>("/audit-center/audits", {
        body: { load_id: loadId, reason },
      });
      setCreated(`Manual audit AU-${a.id} initiated for Digital Load ${a.load_id}.`);
      setReason("");
      await Promise.all([audits.reload(), all.reload()]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not create manual audit.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      allow={["MUNICIPAL_ADMIN", "FACILITY"]}
      accent="proc"
      title={isVerifier ? "Independent Verification Center" : "Audit Trail & Verification Oversight"}
      subtitle={
        isVerifier
          ? "INDEPENDENT VERIFICATION · Evidence • Corroboration • Investigation · Cross-facility statistical sampling, risk-based draws, and multi-party load verification."
          : "MUNICIPAL READ-ONLY OVERSIGHT · System-wide statistical sampling, risk-based draws, and cryptographic audit record oversight."
      }
      subnav={getSubnavForUser(me)}
    >
      {isReceiving && (
        <div className="mb-6">
          <Notice tone="auth" title="Operational Role Boundary">
            You are logged in as a <strong>Receiving Operator</strong>. Independent verification and audit selection are conducted exclusively by designated Independent Verifiers (Facility 2) and monitored by Municipal Administration.{" "}
            <Link href="/receiving" className="underline font-bold text-auth-800">
              Return to Receiving Bay &rarr;
            </Link>
          </Notice>
        </div>
      )}

      {isProcessing && (
        <div className="mb-6">
          <Notice tone="auth" title="Operational Role Boundary">
            You are logged in as <strong>Facility Processing Operations</strong>. Audit execution and selection are reserved for Independent Verifiers.{" "}
            <Link href="/authority/processing" className="underline font-bold text-auth-800">
              Return to Processing Operations &rarr;
            </Link>
          </Notice>
        </div>
      )}

      {isVerifier && (
        <div className="mb-6">
          <Notice tone="proc" title="Independence & Recusal Rules Enforced">
            Audits of loads received by your facility are restricted from your execution to prevent conflicts of interest. The system strictly enforces cross-facility auditor independence.
          </Notice>
        </div>
      )}

      {/* KPI Metrics */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Pending Audits" value={count((a) => a.status === "PENDING")} tone="proc" />
        <Kpi label="In Progress" value={count((a) => a.status === "IN_PROGRESS")} tone="track" />
        <Kpi label="Completed" value={count((a) => a.status === "COMPLETED")} tone="ok" />
        <Kpi label="Random Draws" value={count((a) => a.method === "RANDOM")} tone="track" />
        <Kpi label="Risk-Scored" value={count((a) => a.method === "RISK_BASED")} tone="proc" />
        <Kpi label="Manual Assigned" value={count((a) => a.method === "MANUAL")} tone="auth" />
      </div>

      {/* Municipal Admin View-Only Oversight Notice */}
      {isAdmin && (
        <Card
          tone="neutral"
          title="Audit Selection Engine Oversight"
          className="mb-6"
          right={
            <span className="text-xs text-ink-soft">
              View-Only Municipal Oversight · Cryptographically Verified
            </span>
          }
        >
          <p className="text-xs text-ink-soft mb-3">
            Statistical sampling, risk-based draws, and audit actions are conducted by independent facility verifiers to ensure strict conflict-of-interest separation. Municipal administration maintains read-only oversight across all selection runs and audit files.
          </p>
          {config.data && (
            <div className="grid gap-1.5 rounded-xl border border-line bg-paper/60 p-3 sm:grid-cols-2 text-xs">
              <div className="sm:col-span-2 font-semibold text-ink mb-1">Active Sampling & Risk Parameters</div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Random Sample Default:</span>
                <span className="font-mono font-semibold">{config.data.random_sample_pct}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Risk Score Threshold:</span>
                <span className="font-mono font-semibold">{config.data.risk_threshold}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Cooldown Period:</span>
                <span className="font-mono font-semibold">{config.data.cooldown_days} days</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">History Lookback:</span>
                <span className="font-mono font-semibold">{config.data.lookback_days} days</span>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Facility / Independent Verifier Audit Selection Console */}
      {isVerifier && (
        <Card
          tone="proc"
          title="Select Audits (Statistical & Risk-Based Engine)"
          className="mb-6"
          right={
            <span className="text-xs text-ink-soft">
              Tamper-evident rationale committed to load chain
            </span>
          }
        >
          <div
            className="mb-4 flex flex-wrap gap-2"
            role="tablist"
            aria-label="Selection method"
          >
            {([
              ["RISK_BASED", "Risk-Based Scoring", Gauge],
              ["RANDOM", "Random Statistical Draw", Dices],
              ["MANUAL", "Direct Manual Assignment", Plus],
            ] as const).map(([m, l, Icon]) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => {
                  setMode(m as "RANDOM" | "RISK_BASED" | "MANUAL");
                  setPreview(null);
                  setErr(null);
                }}
                className={`flex items-center gap-2 rounded-lg border px-3.5 py-1.5 text-xs font-semibold transition-all ${
                  mode === m
                    ? "border-ink bg-ink text-white shadow-xs"
                    : "border-line bg-white text-ink-soft hover:bg-paper"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {l}
              </button>
            ))}
          </div>

          {mode === "RANDOM" && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field
                label="Sample Percentage (%)"
                hint={`System default: ${config.data?.random_sample_pct ?? 10}%.`}
              >
                <input
                  className={inputCls}
                  inputMode="decimal"
                  value={pct}
                  onChange={(e) => setPct(e.target.value)}
                  placeholder={String(config.data?.random_sample_pct ?? "10")}
                />
              </Field>
              <Field
                label="PRNG Sampling Seed (Optional)"
                hint="Store a numeric seed to reproduce deterministic draws."
              >
                <input
                  className={inputCls}
                  inputMode="numeric"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))}
                  placeholder="e.g. 42"
                />
              </Field>
              <p className="self-end pb-2 text-xs text-ink-soft">
                Executes uniform pseudorandom selection across eligible received loads without bias.
              </p>
            </div>
          )}

          {mode === "RISK_BASED" && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field
                label="Score Threshold"
                hint={`Threshold (0.00 to 1.00). Default: ${config.data?.risk_threshold ?? 0.4}.`}
              >
                <input
                  className={inputCls}
                  inputMode="decimal"
                  value={thr}
                  onChange={(e) => setThr(e.target.value)}
                  placeholder={String(config.data?.risk_threshold ?? "0.4")}
                />
              </Field>
              <Field
                label="Max Audits Selected"
                hint={`Maximum cap. Default: ${config.data?.risk_max_selected ?? 5}.`}
              >
                <input
                  className={inputCls}
                  inputMode="numeric"
                  value={max}
                  onChange={(e) => setMax(e.target.value.replace(/\D/g, ""))}
                  placeholder={String(config.data?.risk_max_selected ?? "5")}
                />
              </Field>
              <p className="self-end pb-2 text-xs text-ink-soft">
                Ranks loads using weighted risk factors (variance, route history, discrepancy ratios).
              </p>
            </div>
          )}

          {mode === "MANUAL" && (
            <div className="grid gap-3 sm:grid-cols-[180px_1fr]">
              <Field label="Digital Load ID" hint="Specify active load to verify.">
                <input
                  className={`${inputCls} font-mono uppercase`}
                  value={loadId}
                  onChange={(e) => setLoadId(e.target.value.toUpperCase())}
                  placeholder="e.g. DL-1017"
                />
              </Field>
              <Field
                label="Audit Selection Justification"
                hint="Minimum 10 characters. Committed to the tamper-evident audit trail."
              >
                <input
                  className={inputCls}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Routine spot-check requested by municipal ward officer"
                />
              </Field>
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2.5">
            {mode !== "MANUAL" && (
              <Btn
                type="button"
                tone="neutral"
                variant="outline"
                busy={busy}
                onClick={() => runSelection(true)}
              >
                <FlaskConical className="h-4 w-4" />
                Dry-Run Preview
              </Btn>
            )}
            {mode !== "MANUAL" && (
              <Btn type="button" tone="proc" busy={busy} onClick={() => runSelection(false)}>
                <Play className="h-4 w-4" />
                Execute Selection Draw
              </Btn>
            )}
            {mode === "MANUAL" && (
              <Btn
                type="button"
                tone="auth"
                busy={busy}
                disabled={reason.trim().length < 10 || !loadId || busy}
                onClick={createManualAudit}
              >
                <Plus className="h-4 w-4" />
                Create Manual Audit
              </Btn>
            )}
          </div>

          {err && <div className="mt-3"><Notice tone="flag">{err}</Notice></div>}
          {created && <div className="mt-3"><Notice tone="ok">{created}</Notice></div>}

          {/* Dry Run Preview Box */}
          {preview && (
            <div className="mt-4 rounded-xl border border-line bg-paper/50 overflow-hidden">
              <div className="border-b border-line bg-white px-4 py-2.5 text-xs font-semibold text-ink">
                Preview: {preview.selected_count} of {preview.eligible_count} eligible loads matched
                {preview.seed != null ? ` · Sampling Seed: ${preview.seed}` : ""}. (No database state changed).
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <tbody>
                    {preview.candidates.map((c) => (
                      <tr key={c.load_id} className="border-b border-line/60 last:border-0 bg-white">
                        <td className="px-4 py-2 font-mono font-bold">{c.load_id}</td>
                        <td className="px-4 py-2">
                          {c.selected ? (
                            <Badge tone="ok">Selected</Badge>
                          ) : (
                            <Badge tone="neutral">Not Selected</Badge>
                          )}
                        </td>
                        <td className="px-4 py-2 font-mono">
                          {c.risk_score != null
                            ? `Risk Score: ${c.risk_score.toFixed(3)}`
                            : "Random Sampling"}
                        </td>
                        <td className="px-4 py-2 text-ink-soft">
                          {c.top_factors?.join(" · ") ?? "—"}
                        </td>
                      </tr>
                    ))}
                    {preview.candidates.length === 0 && (
                      <tr>
                        <td className="px-4 py-4 text-center text-ink-soft">
                          No eligible loads available for draw (loads must be received without active audits).
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {config.data && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer font-semibold text-ink-soft hover:text-ink">
                View Active Risk Factor Weights & Threshold Configuration
              </summary>
              <div className="mt-2 grid gap-1.5 rounded-xl border border-line bg-paper/60 p-3 sm:grid-cols-2">
                {Object.entries(config.data.weights).map(([k, w]) => (
                  <div key={k} className="flex justify-between">
                    <span className="text-ink-soft">{k.replaceAll("_", " ")}:</span>
                    <span className="font-mono font-semibold">{w}</span>
                  </div>
                ))}
                <div className="sm:col-span-2 mt-1 text-[11px] text-ink-faint border-t border-line pt-1.5">
                  Cooldown period: {config.data.cooldown_days} days · History window: {config.data.lookback_days} days.
                </div>
              </div>
            </details>
          )}
        </Card>
      )}

      {/* Audits Register */}
      <Card
        title="Audit Registry"
        right={
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="flex items-center gap-1.5 font-medium text-ink-soft">
              Target:
              <select
                className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-medium"
                value={targetType}
                onChange={(e) => setTargetType(e.target.value as "ALL" | "DIGITAL_LOAD" | "COLLECTION_EVENT")}
              >
                {TARGET_TYPES.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 font-medium text-ink-soft">
              Status:
              <select
                className="rounded-lg border border-line bg-white px-2 py-1 text-xs"
                value={status}
                onChange={(e) => setStatus(e.target.value as AuditStatus | "ALL")}
              >
                <option value="ALL">All Statuses</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 font-medium text-ink-soft">
              Method:
              <select
                className="rounded-lg border border-line bg-white px-2 py-1 text-xs"
                value={method}
                onChange={(e) => setMethod(e.target.value as AuditMethod | "ALL")}
              >
                <option value="ALL">All Methods</option>
                {METHODS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          </div>
        }
      >
        {!audits.data ? (
          <Spinner label="Loading audits register" />
        ) : audits.data.length === 0 ? (
          <div className="py-10 text-center text-xs text-ink-soft">
            <ShieldAlert className="mx-auto mb-2 h-6 w-6 text-ink-faint" />
            No audits found matching the selected filter criteria.
          </div>
        ) : (
          <div className="-mx-4 sm:mx-0 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-paper/50 text-xs text-ink-soft">
                  {[
                    "Audit ID",
                    "Audit Type",
                    "Target Entity",
                    "Actor",
                    "Independent Verifier",
                    "Selection Justification",
                    "Evidence",
                    "Status",
                  ].map((h) => (
                    <th key={h} className="px-3.5 py-2.5 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {audits.data.map((a) => {
                  const isColAudit = a.target_type === "COLLECTION_EVENT";
                  return (
                    <tr
                      key={a.id}
                      className="border-b border-line/60 align-top last:border-0 hover:bg-paper/40 transition-colors"
                    >
                      <td className="px-3.5 py-3">
                        <Link
                          href={`/audits/${a.id}`}
                          className="font-mono font-bold text-track-700 underline hover:text-track-800"
                        >
                          AU-{a.id}
                        </Link>
                        <p className="text-[11px] text-ink-faint">{fmtDate(a.selected_at)}</p>
                      </td>
                      <td className="px-3.5 py-3">
                        {isColAudit ? (
                          <Badge tone="ok">COLLECTION EVENT AUDIT</Badge>
                        ) : (
                          <Badge tone="proc">DIGITAL LOAD VERIFICATION</Badge>
                        )}
                        <div className="mt-1 flex items-center gap-1.5">
                          <MethodBadge m={a.method} />
                          {a.risk_score != null && (
                            <span className="font-mono text-[10px] text-ink-soft">
                              Risk: {a.risk_score.toFixed(2)}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3.5 py-3">
                        {isColAudit ? (
                          <div>
                            <span className="font-mono font-bold text-ink">
                              {a.household_id ? `HH-${a.household_id}` : "Collection Event"}
                            </span>
                            <p className="text-[11px] text-ink-soft">
                              Load: <span className="font-mono font-semibold">{a.load_id}</span>
                            </p>
                          </div>
                        ) : (
                          <div>
                            <span className="font-mono font-bold text-ink">{a.load_id}</span>
                            <p className="text-[11px] text-ink-soft">
                              {a.ward ? `Ward: ${a.ward}` : "Route"}
                            </p>
                          </div>
                        )}
                      </td>
                      <td className="px-3.5 py-3 text-xs">
                        {isColAudit ? (
                          <div>
                            <span className="font-semibold text-ink">Worker: {a.worker ?? a.actor?.name ?? "—"}</span>
                            <p className="text-[11px] text-ink-soft">Collection Point Actor</p>
                          </div>
                        ) : (
                          <div>
                            <span className="font-semibold text-ink">{a.facility ?? "Intake Facility"}</span>
                            <p className="text-[11px] text-ink-soft">Receiving Facility</p>
                          </div>
                        )}
                      </td>
                      <td className="px-3.5 py-3 text-xs">
                        {isColAudit ? (
                          <div>
                            <span className="font-medium text-ok-800">System Random Gate</span>
                            <p className="text-[11px] text-ink-soft">Point-of-Collection</p>
                          </div>
                        ) : a.auditor ? (
                          <div>
                            <span className="font-semibold text-proc-800">{a.auditor.name}</span>
                            <p className="text-[11px] text-ink-soft">Independent Verifier</p>
                          </div>
                        ) : (
                          <span className="text-ink-faint">Unassigned Verifier</span>
                        )}
                      </td>
                      <td
                        className="max-w-[200px] px-3.5 py-3 text-xs text-ink-soft truncate"
                        title={a.selection_reason}
                      >
                        {a.selection_reason}
                      </td>
                      <td className="px-3.5 py-3 text-xs">
                        {a.evidence_status.files === 0 ? (
                          <span className="text-ink-faint">0 files</span>
                        ) : (
                          `${a.evidence_status.files} file${a.evidence_status.files > 1 ? "s" : ""} (${a.evidence_status.independent_files} indep.)`
                        )}
                        {a.evidence_status.has_result && (
                          <span className="block font-semibold text-ok-700">Result Filed</span>
                        )}
                      </td>
                      <td className="px-3.5 py-3">
                        <AuditStatusBadge s={a.status} />
                        {a.result_overall && (
                          <p className="mt-1 text-[11px] text-ink-soft capitalize">
                            {a.result_overall.replaceAll("_", " ").toLowerCase()}
                          </p>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Shell>
  );
}

export default function AuditCenterPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[400px] items-center justify-center">
          <Spinner />
        </div>
      }
    >
      <AuditCenterContent />
    </Suspense>
  );
}
