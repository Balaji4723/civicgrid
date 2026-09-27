"use client";
import { Check } from "lucide-react";
import { DISC_STATUSES, type DiscStatus } from "@/lib/types";

const LABEL: Record<DiscStatus, string> = {
  FLAGGED: "Flag", EVIDENCE_PENDING: "Evidence", CORROBORATED: "Corroborate", INVESTIGATING: "Investigate", RESOLVED: "Resolve", CLOSED: "Close",
};

export function Stepper({ status }: { status: DiscStatus }) {
  const cur = DISC_STATUSES.indexOf(status);
  return (
    <ol className="grid grid-cols-6 gap-1" aria-label="Resolution lifecycle">
      {DISC_STATUSES.map((s, i) => {
        const done = i < cur || status === "CLOSED";
        const now = i === cur && status !== "CLOSED";
        return (
          <li key={s} aria-current={now ? "step" : undefined} className="min-w-0">
            <div className={`h-1.5 rounded-full ${done ? "bg-ok-600" : now ? (status === "FLAGGED" ? "bg-flag-600" : "bg-auth-600") : "bg-line"}`} />
            <p className={`mt-1.5 flex items-center gap-1 truncate text-xs ${now ? "font-semibold text-ink" : done ? "text-ok-700" : "text-ink-faint"}`}>
              {done && <Check className="h-3 w-3 shrink-0" aria-hidden />}{LABEL[s]}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
