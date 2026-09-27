"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ClipboardCheck,
  FileCheck2,
  Lock,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  User as UserIcon,
} from "lucide-react";
import { api, ApiError, apiUpload, session } from "@/lib/api";
import { fmtDate, short, useLoad } from "@/lib/hooks";
import type { CaseView, Discrepancy, EvidenceConfig, LogEvent } from "@/lib/types";
import type { CaptureResult } from "@/components/CameraCapture";
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
import {
  EvidenceList,
  EvidenceModeBadge,
  EvidenceUploadForm,
} from "@/components/Evidence";
import { IndependencePanel } from "@/components/IndependencePanel";
import { Shell } from "@/components/Shell";
import { Signals } from "@/components/Signals";
import { Stepper } from "@/components/Stepper";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";

type Detail = Discrepancy & CaseView & { trail: LogEvent[] };

const LABEL: Record<string, string> = {
  "add-evidence": "Submit Evidence & Advance",
  corroborate: "Corroborate with Independent Audit",
  investigate: "Start Investigation",
  resolve: "Record Resolution Finding",
  close: "Close Discrepancy Case",
};

export default function DiscrepancyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isVerifier = cap === "INDEPENDENT_VERIFIER";
  const subnav = getSubnavForUser(me);
  const { data: d, error, reload } = useLoad(() => api<Detail>(`/discrepancy/${id}`), [id]);
  const cfg = useLoad(() => api<EvidenceConfig>("/config/evidence"));
  const [tab, setTab] = useState<"workflow" | "evidence">("workflow");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  // Form states with operational defaults
  const [note, setNote] = useState("Weighbridge slip and arrival photo recorded at receiving bay.");
  const [ref, setRef] = useState("");
  const [auditQty, setAuditQty] = useState("");
  const [auditCond, setAuditCond] = useState("UNACCEPTABLE");
  const [auditor, setAuditor] = useState("AUD-01");
  const [invNote, setInvNote] = useState("Review past 5 collections on route for weight variance baseline.");
  const [finding, setFinding] = useState("Weighbridge calibration variance confirmed on secondary scale.");
  const [attr, setAttr] = useState("PROCESS");
  const [closeNote, setCloseNote] = useState("Corrective calibration completed. Load settled.");
  const [pendingCapture, setPendingCapture] = useState<CaptureResult | null>(null);
  const [evidenceCat, setEvidenceCat] = useState<string>("LOAD_PHOTO");
  const [evidenceSide, setEvidenceSide] = useState<string>("");

  useEffect(() => {
    if (d?.details.receiving.quantity && !auditQty) {
      setAuditQty(String(Math.max(1, d.details.receiving.quantity - 5)));
    }
  }, [d?.id, d?.details.receiving.quantity, auditQty]);

  async function runAction(action: string, body: unknown) {
    setBusy(true);
    setErr(null);
    setOkMsg(null);
    try {
      const r = await api<{ message?: string }>(`/discrepancy/${id}/${action}`, { body });
      if (r.message) setOkMsg(r.message);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Action failed to execute.");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function handleAddEvidence() {
    setBusy(true);
    setErr(null);
    setOkMsg(null);
    try {
      if (pendingCapture && d) {
        const f = new FormData();
        f.append("file", pendingCapture.file);
        f.append("description", note.trim() || "Inspection and weighbridge verification photo");
        f.append("category", evidenceCat || "LOAD_PHOTO");
        if (evidenceSide) {
          f.append("side", evidenceSide);
        }
        if (pendingCapture.gps) {
          f.append("latitude", String(pendingCapture.gps.lat));
          f.append("longitude", String(pendingCapture.gps.lng));
          f.append("accuracy_m", String(Math.round(pendingCapture.gps.accuracy)));
        }
        await apiUpload(`/discrepancy/${d.id}/evidence`, f);
        setPendingCapture(null);
      }
      const r = await api<{ message?: string }>(`/discrepancy/${id}/add-evidence`, {
        body: {
          note,
          evidence_ref: ref || null,
        },
      });
      if (r.message) setOkMsg(r.message);
      await reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Action failed to execute.");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  const next = d?.next_action ?? null;
  const strict = d?.require_file_evidence ?? true;
  const files = d?.evidence_summary.files ?? 0;

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="auth"
      title={d ? `Discrepancy Case #${d.id}` : "Discrepancy Case"}
      subtitle={
        d
          ? `${d.type === "QUANTITY" ? "Quantity Mismatch Review" : "Waste Stream Contamination Review"} · Load ${d.load_id}`
          : undefined
      }
      subnav={subnav}
    >
      <div className="mb-4">
        <Link
          href="/authority/discrepancies"
          className="inline-flex items-center gap-1 text-xs font-semibold text-ink-soft hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Discrepancies List
        </Link>
      </div>

      {error && <Notice tone="flag" title="Failed to load discrepancy">{error}</Notice>}
      {!d && !error && <Spinner label="Loading discrepancy case file" />}

      {d && (
        <div className="space-y-6">
          {/* Status & Provenance Badges Header */}
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={d.status} />
            <EvidenceModeBadge mode={d.evidence_mode} />
            {d.corroboration_path && (
              <Badge tone={d.corroboration_evidence_backed ? "ok" : "proc"}>
                {d.corroboration_evidence_backed
                  ? "Corroborated by Independent Audit"
                  : "Corroborated: Manual Entry"}
              </Badge>
            )}
          </div>

          {/* Section Tabs */}
          <div role="tablist" aria-label="Case Sections" className="flex gap-2 border-b border-line">
            {[
              ["workflow", "Resolution Workflow"],
              ["evidence", `Evidence & Independence (${d.evidence.length})`],
            ].map(([k, l]) => (
              <button
                key={k}
                role="tab"
                aria-selected={tab === k}
                onClick={() => setTab(k as "workflow" | "evidence")}
                className={`border-b-2 px-3.5 py-2 text-sm font-semibold transition-colors ${
                  tab === k
                    ? "border-ink text-ink font-bold"
                    : "border-transparent text-ink-soft hover:text-ink"
                }`}
              >
                {l}
              </button>
            ))}
          </div>

          {/* Evidence & Independence Tab */}
          {tab === "evidence" && (
            <div className="space-y-6">
              <IndependencePanel d={d} />
              <Card title="Case File Evidence & Provenance">
                <EvidenceList
                  items={d.evidence}
                  empty="No file evidence attached to this case file yet."
                />
              </Card>
            </div>
          )}

          {/* Workflow Tab */}
          {tab === "workflow" && (
            <div className="grid gap-6 lg:grid-cols-12">
              
              {/* Main Column: Status Stepper, Signals, and Next Step Action */}
              <div className="space-y-6 lg:col-span-8">
                <Card title="Case Resolution Status" right={<StatusBadge status={d.status} />}>
                  <Stepper status={d.status} />
                </Card>

                <Signals d={d} />

                {/* Next Step Action Container */}
                <Card
                  tone={next ? "auth" : "ok"}
                  title={next ? `Next Step: ${LABEL[next]}` : "Case Closed"}
                >
                  <p className="mb-4 text-xs text-ink-soft">
                    {next
                      ? "Only the next valid procedural transition is available. Each action is cryptographically written to the tamper-evident audit trail."
                      : "This case has been formally settled and closed. All findings and evidence are permanently preserved."}
                  </p>

                  {!isVerifier && next && (
                    <Notice tone="neutral" title="Read-Only Oversight">
                      Operational case resolution, evidence submission, corroboration, and closing actions are restricted to Independent Verifiers. Other roles maintain read-only oversight across all cases.
                    </Notice>
                  )}

                  {/* Step 1: Add Evidence */}
                  {isVerifier && next === "add-evidence" && (
                    <div className="space-y-4">
                      {strict ? (
                        <>
                          <p className="text-sm font-medium text-ink">
                            Upload weighbridge slips or inspection photos before advancing.
                          </p>
                          <EvidenceUploadForm
                            path={`/discrepancy/${d.id}/evidence`}
                            config={cfg.data}
                            onDone={() => {
                              setPendingCapture(null);
                              void reload();
                            }}
                            onCaptureChange={(c, meta) => {
                              setPendingCapture(c);
                              if (meta) {
                                setEvidenceCat(meta.category);
                                setEvidenceSide(meta.side);
                              }
                            }}
                            label="Upload Supporting File"
                          />
                          <p className="text-xs text-ink-soft">
                            {files + (pendingCapture ? 1 : 0)} file{(files + (pendingCapture ? 1 : 0)) === 1 ? "" : "s"} attached to this case {pendingCapture ? "(1 captured & ready to submit with note)" : ""}.
                          </p>
                        </>
                      ) : (
                        <Notice tone="proc" title="Legacy Note Mode">
                          Server is operating in legacy notes mode. Uploads are optional.
                        </Notice>
                      )}

                      <Field label="Case Log Note">
                        <textarea
                          className={inputCls}
                          rows={2}
                          value={note}
                          onChange={(e) => setNote(e.target.value)}
                        />
                      </Field>

                      {!strict && (
                        <Field label="Reference ID">
                          <input
                            className={inputCls}
                            value={ref}
                            onChange={(e) => setRef(e.target.value)}
                          />
                        </Field>
                      )}

                      <Btn
                        tone="auth"
                        busy={busy}
                        disabled={note.trim().length < 3 || (strict && files < 1 && !pendingCapture) || busy}
                        onClick={handleAddEvidence}
                      >
                        {LABEL[next]}
                        <ArrowRight className="h-4 w-4" />
                      </Btn>
                    </div>
                  )}

                  {/* Step 2: Corroborate */}
                  {isVerifier && next === "corroborate" &&
                    (strict ? (
                      <div className="space-y-4">
                        <Notice
                          tone="proc"
                          title="Independent Signal Required for Corroboration"
                        >
                          Corroboration requires a completed audit from an independent auditor (not the worker and not from the receiving facility).
                        </Notice>

                        {d.independence.audits.length === 0 && (
                          <p className="text-xs text-ink-soft">
                            No independent audit has been assigned to this load yet.
                          </p>
                        )}

                        <ul className="space-y-2">
                          {d.independence.audits.map((a) => (
                            <li
                              key={a.audit_id}
                              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-paper/50 p-3 text-sm"
                            >
                              <div className="flex items-center gap-2">
                                <Link
                                  href={`/audits/${a.audit_id}`}
                                  className="font-mono font-bold text-track-700 underline"
                                >
                                  AU-{a.audit_id}
                                </Link>
                                <Badge tone={a.status === "COMPLETED" ? "ok" : "track"}>
                                  {a.status.replace("_", " ")}
                                </Badge>
                                <span className="text-xs text-ink-soft">
                                  {a.auditor ?? "Auditor Unassigned"}
                                </span>
                              </div>

                              {a.evaluated ? (
                                <Badge
                                  tone={
                                    a.evaluated.outcome === "ACCEPTED" ? "ok" : "flag"
                                  }
                                >
                                  {a.evaluated.outcome.replaceAll("_", " ").toLowerCase()}
                                </Badge>
                              ) : a.status === "COMPLETED" ? (
                                <Btn
                                  tone="auth"
                                  busy={busy}
                                  className="!py-1 text-xs"
                                  onClick={() =>
                                    runAction("corroborate", { audit_id: a.audit_id })
                                  }
                                >
                                  Submit for Corroboration
                                  <ArrowRight className="h-3.5 w-3.5" />
                                </Btn>
                              ) : (
                                <Link
                                  href={`/audits/${a.audit_id}`}
                                  className="inline-flex items-center gap-1 text-xs font-semibold text-proc-700 underline hover:text-proc-800"
                                >
                                  Conduct Audit &rarr;
                                </Link>
                              )}
                            </li>
                          ))}
                        </ul>

                        <div className="pt-2">
                          <Link
                            href={`/audits?load_id=${d.load_id}&reason=${encodeURIComponent(`Independent physical scale verification for ${d.load_id} discrepancy #${d.id}.`)}`}
                            className="inline-flex items-center gap-1.5 text-xs font-semibold text-proc-700 underline hover:text-proc-800"
                          >
                            <ClipboardCheck className="h-4 w-4" />
                            Assign or Conduct Audit in Verification Center &rarr;
                          </Link>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <div className="grid gap-3 sm:grid-cols-2">
                          {d.type === "QUANTITY" ? (
                            <Field label="Audited Quantity (kg)">
                              <input
                                className={inputCls}
                                inputMode="numeric"
                                value={auditQty}
                                onChange={(e) =>
                                  setAuditQty(e.target.value.replace(/\D/g, ""))
                                }
                              />
                            </Field>
                          ) : (
                            <Field label="Audited Condition">
                              <select
                                className={inputCls}
                                value={auditCond}
                                onChange={(e) => setAuditCond(e.target.value)}
                              >
                                <option value="UNACCEPTABLE">Unacceptable</option>
                                <option value="ACCEPTABLE">Acceptable</option>
                              </select>
                            </Field>
                          )}
                          <Field label="Auditor Identification">
                            <input
                              className={inputCls}
                              value={auditor}
                              onChange={(e) => setAuditor(e.target.value)}
                            />
                          </Field>
                        </div>
                        <Btn
                          tone="auth"
                          busy={busy}
                          onClick={() =>
                            runAction(
                              "corroborate",
                              d.type === "QUANTITY"
                                ? { audit_quantity: Number(auditQty), auditor }
                                : { audit_condition: auditCond, auditor }
                            )
                          }
                        >
                          Record Corroboration
                          <ArrowRight className="h-4 w-4" />
                        </Btn>
                      </div>
                    ))}

                  {/* Step 3: Investigate */}
                  {isVerifier && next === "investigate" && (
                    <div className="space-y-4">
                      <Field label="Investigation Scope & Notes">
                        <textarea
                          className={inputCls}
                          rows={2}
                          value={invNote}
                          onChange={(e) => setInvNote(e.target.value)}
                        />
                      </Field>
                      <Btn
                        tone="auth"
                        busy={busy}
                        onClick={() => runAction("investigate", { note: invNote })}
                      >
                        {LABEL[next]}
                        <ArrowRight className="h-4 w-4" />
                      </Btn>
                    </div>
                  )}

                  {/* Step 4: Resolve */}
                  {isVerifier && next === "resolve" && (
                    <div className="space-y-4">
                      <Field label="Resolution Finding">
                        <textarea
                          className={inputCls}
                          rows={2}
                          value={finding}
                          onChange={(e) => setFinding(e.target.value)}
                        />
                      </Field>
                      <Field
                        label="Attributed Root Cause"
                        hint="Assigned only after independent corroboration and investigation."
                      >
                        <select
                          className={inputCls}
                          value={attr}
                          onChange={(e) => setAttr(e.target.value)}
                        >
                          <option value="NONE">No Attribution (System Error)</option>
                          <option value="PROCESS">Process / Transit Variance</option>
                          <option value="FACILITY">Facility Scale Calibration</option>
                          <option value="WORKER">Worker Collection Discrepancy</option>
                        </select>
                      </Field>
                      <Btn
                        tone="auth"
                        busy={busy}
                        disabled={finding.trim().length < 3 || busy}
                        onClick={() =>
                          runAction("resolve", { finding, attributed_to: attr })
                        }
                      >
                        {LABEL[next]}
                        <ArrowRight className="h-4 w-4" />
                      </Btn>
                    </div>
                  )}

                  {/* Step 5: Close */}
                  {isVerifier && next === "close" && (
                    <div className="space-y-4">
                      <Field label="Closing Settlement Note">
                        <input
                          className={inputCls}
                          value={closeNote}
                          onChange={(e) => setCloseNote(e.target.value)}
                        />
                      </Field>
                      <Btn
                        tone="ok"
                        busy={busy}
                        onClick={() => runAction("close", { note: closeNote })}
                      >
                        {LABEL[next]}
                        <ArrowRight className="h-4 w-4" />
                      </Btn>
                    </div>
                  )}

                  {/* Closed Status */}
                  {!next && (
                    <div className="space-y-3">
                      <Notice tone="ok" title="Case Closed & Permanently Sealed">
                        Every procedural step has been verified and committed to the tamper-evident audit trail.
                      </Notice>
                      <Link
                        href="/municipal"
                        className="inline-flex items-center gap-1 text-xs font-semibold text-auth-700 underline"
                      >
                        <ShieldCheck className="h-4 w-4" />
                        Verify SHA-256 Hash Chain in Municipal Dashboard &rarr;
                      </Link>
                    </div>
                  )}

                  {okMsg && <div className="mt-4"><Notice tone="ok">{okMsg}</Notice></div>}
                  {err && <div className="mt-4"><Notice tone="flag" title="Action Blocked">{err}</Notice></div>}
                </Card>
              </div>

              {/* Side Column: Tamper-Evident Audit Trail Log */}
              <div className="space-y-6 lg:col-span-4">
                <Card
                  title="Tamper-Evident Case Log"
                  right={<Badge tone="neutral">SHA-256 Chained</Badge>}
                >
                  <ol className="space-y-3 max-h-96 overflow-y-auto pr-1">
                    {d.trail.map((e) => (
                      <li key={e.id} className="border-l-2 border-auth-200 pl-3 text-xs">
                        <p className="font-semibold text-ink">
                          {e.event_type.replaceAll("_", " ").toLowerCase()}
                        </p>
                        <p className="text-ink-soft text-[11px] mt-0.5">
                          {fmtDate(e.created_at)} · {String(e.payload.actor ?? "System")}
                        </p>
                        <p className="mt-1 font-mono text-[10px] text-ink-faint">
                          #{e.index} · {short(e.hash, 12)}
                        </p>
                      </li>
                    ))}
                    {d.trail.length === 0 && (
                      <p className="py-3 text-center text-xs text-ink-soft">
                        No audit events recorded yet.
                      </p>
                    )}
                  </ol>
                </Card>
              </div>

            </div>
          )}
        </div>
      )}
    </Shell>
  );
}
