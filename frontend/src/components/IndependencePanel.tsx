"use client";
import { Ban, Lock, ScanEye, ShieldCheck, ShieldX } from "lucide-react";
import type { CaseView, Discrepancy } from "@/lib/types";
import { Badge, Card } from "./ui";

const outcomeText: Record<string, string> = {
  ACCEPTED: "Accepted: corroborated", REJECTED_SUPPORTS_WORKER: "Rejected: supports the worker", REJECTED_INCONCLUSIVE: "Rejected: inconclusive",
  REJECTED_NOT_INDEPENDENT: "Rejected: not independent", REJECTED_NO_EVIDENCE: "Rejected: no independent file evidence",
};

/** Makes the rule visible: two signals exist, neither can confirm itself, and a third independent one is required. */
export function IndependencePanel({ d }: { d: Discrepancy & CaseView }) {
  const { declaration, receiving } = d.details;
  const ind = d.independence;
  const isQty = d.type === "QUANTITY";
  const dv = isQty ? `${declaration.quantity} kg` : (declaration.stream === "SEGREGATED" ? "Segregated" : "Mixed");
  const rv = isQty ? `${receiving.quantity} kg` : (receiving.condition === "UNACCEPTABLE" ? "Unacceptable" : "Acceptable");
  return (
    <Card tone="auth" title="Independence check" right={<Badge tone="auth">Automated cross-checks flag discrepancies; independent evidence corroborates.</Badge>}>
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_1.2fr]">
        <div className="rounded-lg border border-track-100 bg-track-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-track-700">
            {isQty ? "Signal 1 · Worker Declared Quantity" : "Signal 1 · Collection-Side Stream Condition"}
          </p>
          <p className="mt-1 text-xl font-semibold">{dv}</p>
          <p className="text-xs text-ink-soft">{ind.parties.worker.name ?? "Worker"}</p>
          <p className="mt-2 flex items-center gap-1 text-xs font-medium text-track-700"><Lock className="h-3 w-3" aria-hidden />Cannot confirm itself</p>
        </div>
        <div className="rounded-lg border border-auth-100 bg-auth-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-auth-700">
            {isQty ? "Signal 2 · Facility Recorded Quantity" : "Signal 2 · Facility Receiving Condition"}
          </p>
          <p className="mt-1 text-xl font-semibold">{rv}</p>
          <p className="text-xs text-ink-soft">{ind.parties.facility_recorder.name ?? "recorder unknown"} · {ind.parties.receiving_facility.name}</p>
          <p className="mt-2 flex items-center gap-1 text-xs font-medium text-auth-700"><Lock className="h-3 w-3" aria-hidden />Cannot confirm itself</p>
        </div>
        <div className={`rounded-lg border p-3 ${d.status === "EVIDENCE_PENDING" || d.status === "FLAGGED" ? "border-dashed border-proc-500 bg-proc-50" : "border-ok-100 bg-ok-50"}`}>
          <p className="text-xs font-semibold uppercase tracking-wide text-proc-700">
            {isQty ? "Signal 3 · Independent Audit Quantity" : "Signal 3 · Independent Audit Finding"}
          </p>
          <p className="mt-1 text-sm">Must be done by someone who is <strong>not</strong> the worker, <strong>not</strong> the person who recorded Signal 2, and <strong>not</strong> from the receiving facility.</p>
          {d.corroboration_path && (
            <p className={`mt-2 flex items-center gap-1 text-xs font-medium ${d.corroboration_evidence_backed ? "text-ok-700" : "text-proc-700"}`}>
              {d.corroboration_evidence_backed ? <ShieldCheck className="h-3 w-3" aria-hidden /> : <Ban className="h-3 w-3" aria-hidden />}
              {d.corroboration_evidence_backed ? "Corroborated by an independent, evidence-backed audit" : "Legacy manual entry: no independence check, no files"}
            </p>)}
        </div>
      </div>

      <h3 className="mb-1 mt-4 flex items-center gap-1.5 text-sm font-semibold"><ScanEye className="h-4 w-4" aria-hidden />Audits on this load</h3>
      {ind.audits.length === 0
        ? <p className="text-sm text-ink-soft">No audit has been selected for this load yet.</p>
        : (
          <ul className="space-y-2">
            {ind.audits.map((a) => (
              <li key={a.audit_id} className="flex flex-wrap items-center gap-2 rounded-md border border-line px-3 py-2 text-sm">
                <span className="font-mono font-semibold">AU-{a.audit_id}</span><Badge>{a.method.replace("_", " ").toLowerCase()}</Badge><Badge tone={a.status === "COMPLETED" ? "ok" : "track"}>{a.status.replace("_", " ")}</Badge>
                <span className="text-ink-soft">{a.auditor ? `${a.auditor} (${a.auditor_role?.toLowerCase().replace("_", " ")})` : "no auditor yet"}</span>
                {a.independent === true && <Badge tone="ok"><ShieldCheck className="h-3 w-3" aria-hidden />Independent</Badge>}
                {a.independent === false && <Badge tone="flag"><ShieldX className="h-3 w-3" aria-hidden />Not independent</Badge>}
                {a.overall && <Badge tone="neutral">audit {a.overall.replaceAll("_", " ").toLowerCase()}</Badge>}
                {a.evaluated && <Badge tone={a.evaluated.outcome === "ACCEPTED" ? "ok" : "flag"}>{outcomeText[a.evaluated.outcome] ?? a.evaluated.outcome}</Badge>}
                {a.violations.length > 0 && <span className="w-full text-xs text-flag-700">{a.violations.map((v) => v.message).join(" ")}</span>}
              </li>))}
          </ul>)}
    </Card>
  );
}
