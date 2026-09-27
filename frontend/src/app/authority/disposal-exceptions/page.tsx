"use client";
import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { api, session } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";
import type { DisposalException, DisposalExceptionStatus } from "@/lib/types";
import { Badge, Card, Notice, Spinner, type Tone } from "@/components/ui";
import { Shell } from "@/components/Shell";

const STATUSES = [
  "ALL",
  "RAISED",
  "PENDING_AUTHORIZATION",
  "AUTHORIZED",
  "REJECTED",
  "RESOLVED",
  "CANCELLED",
] as const;

const tone: Record<DisposalExceptionStatus, Tone> = {
  RAISED: "flag",
  PENDING_AUTHORIZATION: "flag",
  AUTHORIZED: "proc",
  REJECTED: "neutral",
  RESOLVED: "ok",
  CANCELLED: "neutral",
};

export default function DisposalExceptionsWorkspace() {
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isProc = cap === "PROCESSING";
  const subnav = getSubnavForUser(me);

  const exceptions = useLoad(() => api<DisposalException[]>("/disposal-exceptions"));
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("ALL");
  const rows = (exceptions.data ?? []).filter((e) => status === "ALL" || e.status === status);

  const title = isProc
    ? "Disposal Exceptions & Diversions"
    : "Disposal Exceptions Oversight";

  const subtitle = isProc
    ? "FACILITY OPERATIONS · Raised when designated facilities experience shutdowns, capacity limits, or off-spec material rejections. Request and execute alternate destination rerouting."
    : "MUNICIPAL READ-ONLY OVERSIGHT · Municipal authorization and oversight of material diversion requests, facility capacity exceptions, and alternate routings.";

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="flag"
      title={title}
      subtitle={subtitle}
      subnav={subnav}
    >
      <div className="mb-6">
        <Notice tone="neutral" title="Exception Handling">
          To raise a new exception or authorize alternate destination handoffs, open the specific Digital Load&apos;s journey page.
        </Notice>
      </div>

      <Card title="Filter by Exception Status" className="mb-6">
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                status === s
                  ? "border-flag-600 bg-flag-50 text-flag-700 shadow-xs"
                  : "border-line text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      </Card>

      <div className="space-y-3">
        {exceptions.loading && !exceptions.data && (
          <Spinner label="Loading disposal exceptions" />
        )}
        {exceptions.error && (
          <Notice tone="flag" title="Failed to load exceptions">
            {exceptions.error}
          </Notice>
        )}
        {rows.map((e) => (
          <Card key={e.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-ink text-sm">
                  Exception #{e.id}
                </span>
                <span className="font-mono text-xs font-bold text-track-700">
                  {e.digital_load_id}
                </span>
              </div>
              <Badge tone={tone[e.status]}>{e.status.replace("_", " ")}</Badge>
            </div>
            <p className="mt-2 text-xs text-ink-soft">{e.reason}</p>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line/60 pt-3 text-xs">
              <div className="text-ink">
                <span className="text-ink-soft">Original Facility:</span>{" "}
                <span className="font-medium">
                  {e.original_destination_facility ?? `Facility ${e.original_destination_facility_id}`}
                </span>
                {e.alternative_destination_facility && (
                  <>
                    {" "}
                    &rarr; <span className="text-ink-soft">Alternative Routing:</span>{" "}
                    <span className="font-bold text-proc-700">
                      {e.alternative_destination_facility}
                    </span>
                  </>
                )}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-ink-soft">{fmtDate(e.created_at)}</span>
                <Link
                  href={`/authority/load/${e.digital_load_id}`}
                  className="font-semibold text-auth-700 underline hover:text-auth-800"
                >
                  Inspect Load &rarr;
                </Link>
              </div>
            </div>
          </Card>
        ))}
        {rows.length === 0 && !exceptions.loading && (
          <p className="text-center py-6 text-xs text-ink-soft">
            No disposal exceptions match the selected filter.
          </p>
        )}
      </div>
    </Shell>
  );
}
