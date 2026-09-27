"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import {
  ArrowLeft,
  Ban,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  Play,
  ScanEye,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import { api, ApiError, session } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import type { AuditDetail, EvidenceConfig, EvidenceItem } from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Field,
  inputCls,
  Notice,
  Spinner,
  StatusBadge,
} from "@/components/ui";
import { AuditStatusBadge, MethodBadge, VERDICT_TEXT } from "@/components/AuditBadges";
import { EvidenceList, EvidenceUploadForm } from "@/components/Evidence";
import { RiskBreakdown } from "@/components/RiskBreakdown";
import { Shell } from "@/components/Shell";
import { cleanLabel, getSubnavForUser, getUserCapability } from "@/lib/nav";

export default function AuditDetailPage() {
  const { id } = useParams<{ id: string }>();
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isAdmin = me?.role === "MUNICIPAL_ADMIN";
  const { data: a, error, reload } = useLoad(() => api<AuditDetail>(`/audit-center/audits/${id}`), [id]);
  const caseEv = useLoad(
    () => api<EvidenceItem[]>(`/audit-center/audits/${id}/evidence`),
    [id, a?.status]
  );
  const cfg = useLoad(() => api<EvidenceConfig>("/config/evidence"));

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [qty, setQty] = useState("");
  const [cond, setCond] = useState("ACCEPTABLE");
  const [obs, setObs] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  async function act(path: string, body?: unknown) {
    setBusy(true);
    setErr(null);
    try {
      await api(`/audit-center/audits/${id}/${path}`, { body: body ?? {} });
      await Promise.all([reload(), caseEv.reload()]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  const mine = !!a?.auditor && a.auditor.id === me?.id;
  const evidenceFiles = a?.evidence_status.files ?? 0;

  return (
    <Shell
      allow={["MUNICIPAL_ADMIN", "FACILITY"]}
      accent="proc"
      title={
        a
          ? a.target_type === "COLLECTION_EVENT"
            ? `Collection Event Audit AU-${a.id}`
            : `Digital Load Verification AU-${a.id}`
          : "Audit"
      }
      subtitle={
        a
          ? a.target_type === "COLLECTION_EVENT"
            ? `Point-of-collection random audit for Household ${a.household_id ? `HH-${a.household_id}` : "Event"} on ${a.load_id}`
            : `Load-level multi-party verification for ${a.load_id} · Ward ${cleanLabel(a.ward)}`
          : undefined
      }
      subnav={getSubnavForUser(me)}
    >
      <div className="mb-4">
        <Link
          href="/audits"
          className="inline-flex items-center gap-1 text-xs font-semibold text-ink-soft hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Audit Center
        </Link>
      </div>

      {error && <Notice tone="flag" title="Failed to load audit">{error}</Notice>}
      {!a && !error && <Spinner label="Loading audit case file" />}

      {a && (
        <div className="grid gap-6 lg:grid-cols-12">
          
          {/* Main Column: Selection Rationale, Comparative Signals, Results */}
          <div className="space-y-6 lg:col-span-7">
            {/* Selection Justification Card */}
            <Card
              title="Audit Selection Rationale"
              right={
                <div className="flex items-center gap-2">
                  {a.target_type === "COLLECTION_EVENT" ? (
                    <Badge tone="ok">COLLECTION EVENT AUDIT</Badge>
                  ) : (
                    <Badge tone="proc">DIGITAL LOAD VERIFICATION</Badge>
                  )}
                  <MethodBadge m={a.method} />
                  <AuditStatusBadge s={a.status} />
                </div>
              }
            >
              <p className="text-sm font-medium text-ink leading-relaxed">{a.selection_reason}</p>
              <p className="mt-1.5 text-xs text-ink-soft">
                Selected {fmtDate(a.selected_at)} by {a.selected_by}
                {a.run ? ` · Selection Run #${a.run.id}` : ""}
              </p>

              {a.method === "RANDOM" && a.run && (
                <p className="mt-3 rounded-xl bg-paper p-3 text-xs text-ink-soft border border-line">
                  <strong>Statistical Draw:</strong> {a.run.selected_count} of {a.run.eligible_count} eligible loads selected at {a.run.config.random_sample_pct}%, PRNG seed: <span className="font-mono font-bold text-ink">{a.run.seed}</span>. Draw is fully deterministic and reproducible.
                </p>
              )}

              {a.risk_factors.length > 0 && (
                <div className="mt-4 border-t border-line/60 pt-3">
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-ink-faint">
                    {a.method === "MANUAL"
                      ? "Risk Factor Profile (Informational Only)"
                      : "Risk Breakdown & Scoring Model"}
                  </h3>
                  <RiskBreakdown factors={a.risk_factors} score={a.risk_score} />
                </div>
              )}
            </Card>

            {/* Comparative Signals on Load Under Audit */}
            <Card
              title="Comparative Load Records"
              right={<span className="font-mono text-sm font-bold text-ink">{a.load_id}</span>}
            >
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-track-100 bg-track-50/70 p-3">
                  <p className="text-xs font-semibold text-track-700">1 · Worker Declared</p>
                  <p className="mt-1 text-xl font-bold text-ink">{a.declaration.quantity} kg</p>
                  <p className="text-[11px] text-ink-soft mt-0.5">
                    {a.worker} · {a.declaration.segregated}/{a.declaration.households_collected} segregated
                  </p>
                </div>
                <div className="rounded-xl border border-auth-100 bg-auth-50/70 p-3">
                  <p className="text-xs font-semibold text-auth-700">2 · Facility Weighed</p>
                  <p className="mt-1 text-xl font-bold text-ink">{a.receiving?.quantity} kg</p>
                  <p className="text-[11px] text-ink-soft mt-0.5">
                    {a.facility} · {a.receiving?.condition.toLowerCase()}
                  </p>
                </div>
                <div className="rounded-xl border border-proc-100 bg-proc-50/70 p-3">
                  <p className="text-xs font-semibold text-proc-700">3 · Audit Finding</p>
                  <p className="mt-1 text-xl font-bold text-ink">
                    {a.result ? `${a.result.quantity} kg` : "Pending"}
                  </p>
                  <p className="text-[11px] text-ink-soft mt-0.5">
                    {a.result ? a.result.condition.toLowerCase() : "Awaiting execution"}
                  </p>
                </div>
              </div>

              {a.discrepancies.length > 0 && (
                <ul className="mt-4 space-y-2 border-t border-line/60 pt-3">
                  {a.discrepancies.map((d) => (
                    <li
                      key={d.id}
                      className="flex items-center justify-between rounded-xl border border-line bg-paper/50 p-2.5 text-xs"
                    >
                      <span className="font-medium text-ink">
                        Discrepancy #{d.id} ({d.type.toLowerCase()})
                      </span>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={d.status} />
                        <Link
                          className="font-semibold text-auth-700 underline"
                          href={`/authority/discrepancy/${d.id}`}
                        >
                          View Case &rarr;
                        </Link>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {/* Audit Finding Result Card */}
            {a.result && (
              <Card tone="ok" title="Formal Audit Finding">
                <ul className="space-y-2 text-xs">
                  {Object.entries(a.result.verdicts).map(([dim, v]) => (
                    <li
                      key={dim}
                      className="flex items-center justify-between rounded-xl border border-line bg-paper/40 p-2.5"
                    >
                      <span className="font-bold uppercase text-ink">{dim} Check</span>
                      <Badge
                        tone={
                          v === "SUPPORTS_FACILITY"
                            ? "auth"
                            : v === "SUPPORTS_WORKER"
                              ? "track"
                              : v === "INCONCLUSIVE"
                                ? "proc"
                                : "neutral"
                        }
                      >
                        {VERDICT_TEXT[v] ?? v}
                      </Badge>
                    </li>
                  ))}
                </ul>
                <div className="mt-3 rounded-xl bg-paper/60 p-3 border border-line">
                  <p className="text-xs font-semibold text-ink">Auditor Observations:</p>
                  <p className="mt-1 text-xs text-ink-soft leading-relaxed">{a.result.observations}</p>
                </div>

                {a.result.requires_followup && (
                  <div className="mt-3">
                    <Notice tone="proc" title="Follow-up Required">
                      The audit finding diverges from both initial worker and facility signals. Administrative review is required.
                    </Notice>
                  </div>
                )}

                {a.corroborations.length > 0 && (
                  <div className="mt-4 border-t border-line pt-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-ink-faint mb-2">
                      Cross-Check Corroboration Outcomes
                    </h4>
                    <ul className="space-y-1.5">
                      {a.corroborations.map((c) => (
                        <li
                          key={c.discrepancy_id}
                          className="flex items-center gap-2 text-xs text-ink"
                        >
                          <Badge tone={c.outcome === "ACCEPTED" ? "ok" : "flag"}>
                            {c.outcome.replaceAll("_", " ").toLowerCase()}
                          </Badge>
                          <span>for Discrepancy #{c.discrepancy_id}</span>
                          <span className="font-mono text-[10px] text-ink-faint">
                            ({c.reason_code})
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
            )}

            {/* Evidence Attached to Load */}
            <Card
              title="Attached Case Evidence"
              right={<ScanEye className="h-4 w-4 text-ink-faint" />}
            >
              <p className="mb-3 text-xs text-ink-soft">
                All physical files, weighbridge slips, and photos linked with cryptographic hashes to this load.
              </p>
              {caseEv.error ? (
                <p className="py-2 text-xs text-ink-soft">
                  {a.can_conduct
                    ? "Start the audit to inspect the full case file."
                    : "Access restricted by independence rules."}
                </p>
              ) : caseEv.data ? (
                <EvidenceList items={caseEv.data} empty="No evidence attached yet." />
              ) : (
                <Spinner label="Loading case evidence" />
              )}
            </Card>
          </div>

          {/* Side Column: Independence Check & Auditor Console */}
          <div className="space-y-6 lg:col-span-5">
            {/* Recusal & Independence Verification */}
            <Card
              tone={a.can_conduct ? "ok" : "flag"}
              title="Auditor Independence Verification"
            >
              {a.can_conduct ? (
                <div className="flex items-start gap-2 text-xs text-ok-700 bg-ok-50 p-3 rounded-xl border border-ok-100">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok-600" />
                  <div>
                    <p className="font-bold">Independence Verified</p>
                    <p className="mt-0.5 text-[11px] text-ok-800">
                      You are not the collection worker, not the receiving recorder, and not affiliated with the receiving facility.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-2 text-xs text-flag-700 bg-flag-50 p-3 rounded-xl border border-flag-100">
                  <p className="flex items-center gap-1.5 font-bold">
                    <ShieldX className="h-4 w-4 text-flag-600" />
                    Conflict of Interest / Not Independent
                  </p>
                  {a.independence_violations?.map((v) => (
                    <p key={v.code} className="text-[11px] text-flag-800">
                      • {v.message}
                    </p>
                  ))}
                </div>
              )}
            </Card>

            {/* Execution Console */}
            <Card
              tone="proc"
              title="Auditor Execution Console"
              right={<ClipboardCheck className="h-4 w-4 text-ink-faint" />}
            >
              {err && <div className="mb-3"><Notice tone="flag" title="Action Refused">{err}</Notice></div>}

              {a.status === "PENDING" &&
                (a.can_conduct ? (
                  <Btn tone="track" busy={busy} onClick={() => act("start")} className="w-full">
                    <Play className="h-4 w-4" />
                    Start Independent Audit
                  </Btn>
                ) : (
                  <p className="py-2 text-center text-xs text-ink-soft">
                    An independent auditor from an alternate facility or municipal team must start this audit.
                  </p>
                ))}

              {a.status === "IN_PROGRESS" && !mine && (
                <p className="py-2 text-xs text-ink-soft">
                  Audit is actively in progress by {a.auditor?.name}. Only the assigned auditor may submit findings.
                </p>
              )}

              {a.status === "IN_PROGRESS" && mine && (
                <div className="space-y-4">
                  <div>
                    <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-ink-faint">
                      1 · Attach Independent Evidence ({evidenceFiles} file{evidenceFiles === 1 ? "" : "s"})
                    </p>
                    <EvidenceUploadForm
                      path={`/audit-center/audits/${a.id}/evidence`}
                      config={cfg.data}
                      defaultCategory="AUDIT_OBSERVATION"
                      label="Attach to Audit"
                      onDone={() => {
                        void reload();
                        void caseEv.reload();
                      }}
                    />
                  </div>

                  <div className="space-y-3 border-t border-line pt-3">
                    <p className="text-xs font-bold uppercase tracking-wider text-ink-faint">
                      2 · Record Verified Measurements
                    </p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <Field label="Weighed Quantity (kg)">
                        <input
                          className={inputCls}
                          inputMode="numeric"
                          value={qty}
                          onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))}
                          placeholder="e.g. 480"
                        />
                      </Field>
                      <Field label="Stream Condition">
                        <select
                          className={inputCls}
                          value={cond}
                          onChange={(e) => setCond(e.target.value)}
                        >
                          <option value="ACCEPTABLE">Acceptable</option>
                          <option value="UNACCEPTABLE">Unacceptable</option>
                        </select>
                      </Field>
                    </div>
                    <Field label="Auditor Observations">
                      <textarea
                        className={inputCls}
                        rows={2}
                        value={obs}
                        onChange={(e) => setObs(e.target.value)}
                        placeholder="Detailed observations and scale calibration checks"
                      />
                    </Field>
                    <Btn
                      tone="ok"
                      busy={busy}
                      disabled={
                        !qty ||
                        obs.trim().length < 5 ||
                        (cfg.data?.require_file_evidence && evidenceFiles === 0) ||
                        busy
                      }
                      onClick={() =>
                        act("complete", {
                          quantity: Number(qty),
                          condition: cond,
                          observations: obs,
                        })
                      }
                      className="w-full"
                    >
                      Submit Audit Finding
                    </Btn>
                    {cfg.data?.require_file_evidence && evidenceFiles === 0 && (
                      <p className="text-xs text-proc-700">
                        Attach at least one photo or weighbridge file before submitting.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {a.status === "COMPLETED" && (
                <div className="rounded-xl bg-ok-50 p-3 text-xs text-ok-800 border border-ok-100 space-y-1">
                  <p className="font-bold flex items-center gap-1.5 text-ok-700">
                    <CheckCircle2 className="h-4 w-4" />
                    Audit Successfully Completed
                  </p>
                  <p>
                    Completed {fmtDate(a.completed_at)} by {a.auditor?.name}.
                  </p>
                  <p className="text-[11px] text-ok-900 mt-1">
                    To use this finding for corroboration, open the corresponding discrepancy case page.
                  </p>
                </div>
              )}

              {a.status === "CANCELLED" && (
                <div className="rounded-xl bg-paper p-3 text-xs text-ink-soft border border-line">
                  <span className="font-bold text-ink">Cancelled:</span> {a.cancel_reason}
                </div>
              )}

              {isAdmin && (a.status === "PENDING" || a.status === "IN_PROGRESS") && (
                <details className="mt-4 rounded-xl border border-line bg-paper/40 p-3">
                  <summary className="cursor-pointer text-xs font-semibold text-flag-700 flex items-center gap-1">
                    <Ban className="h-3.5 w-3.5" />
                    Cancel Audit (Admin Override)
                  </summary>
                  <div className="mt-3 space-y-2">
                    <Field label="Cancellation Reason">
                      <input
                        className={inputCls}
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="Minimum 10 characters required"
                      />
                    </Field>
                    <Btn
                      tone="flag"
                      variant="outline"
                      busy={busy}
                      disabled={cancelReason.trim().length < 10 || busy}
                      onClick={() => act("cancel", { reason: cancelReason })}
                      className="!py-1 text-xs"
                    >
                      Confirm Cancellation
                    </Btn>
                  </div>
                </details>
              )}
            </Card>
          </div>

        </div>
      )}
    </Shell>
  );
}
