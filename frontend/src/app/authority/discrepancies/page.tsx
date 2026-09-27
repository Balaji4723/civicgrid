"use client";
import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { api, session } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";
import type { Discrepancy } from "@/lib/types";
import { Badge, Card, Notice, Spinner, StatusBadge, Table } from "@/components/ui";
import { Shell } from "@/components/Shell";

const STATUSES = [
  "ALL",
  "FLAGGED",
  "EVIDENCE_PENDING",
  "CORROBORATED",
  "INVESTIGATING",
  "RESOLVED",
  "CLOSED",
] as const;

export default function DiscrepanciesPage() {
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isVerifier = cap === "INDEPENDENT_VERIFIER";
  const subnav = getSubnavForUser(me);

  const discs = useLoad(() => api<Discrepancy[]>("/discrepancy"));
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("ALL");
  const rows = (discs.data ?? []).filter((x) => status === "ALL" || x.status === status);

  const title = isVerifier
    ? "Discrepancy Investigation Center"
    : "Discrepancy Case Oversight";

  const subtitle = isVerifier
    ? "INDEPENDENT VERIFICATION · FLAGGED ≠ GUILTY · Multi-point corroboration, root-cause investigation, and formal settlement of cross-check variances."
    : "MUNICIPAL READ-ONLY OVERSIGHT · City-wide oversight of automated cross-check discrepancy flags, evidence status, and resolution states.";

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="auth"
      title={title}
      subtitle={subtitle}
      subnav={subnav}
    >
      <Card title="Filter by Status" className="mb-6">
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                status === s
                  ? "border-auth-600 bg-auth-50 text-auth-700 shadow-xs"
                  : "border-line text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      </Card>

      <Card
        title={`Discrepancy Cases (${rows.length})`}
        right={
          <span className="text-xs text-ink-soft">
            {isVerifier ? "Independent Resolution Queue" : "Oversight Queue"}
          </span>
        }
      >
        {discs.loading && !discs.data && <Spinner label="Loading discrepancy cases" />}
        {discs.error && <Notice tone="flag" title="Failed to load">{discs.error}</Notice>}
        {discs.data && (
          <Table
            head={[
              "Case #",
              "Digital Load ID",
              "Check Type",
              "Status",
              "Raised At",
              "Resolved At",
              "Action",
            ]}
            empty="No discrepancies match the selected status filter."
            rows={rows.map((x) => [
              `#${x.id}`,
              <span key="l" className="font-mono font-bold text-ink">
                {x.load_id}
              </span>,
              <Badge key="t">{x.type}</Badge>,
              <StatusBadge key="s" status={x.status} />,
              fmtDate(x.created_at),
              x.resolved_at ? fmtDate(x.resolved_at) : "—",
              <Link
                key="link"
                href={`/authority/discrepancy/${x.id}`}
                className="inline-flex items-center gap-1 text-xs font-semibold text-auth-700 underline hover:text-auth-800"
              >
                {isVerifier ? "Investigate Case \u2192" : "View Case (Read-Only) \u2192"}
              </Link>,
            ])}
          />
        )}
      </Card>
    </Shell>
  );
}
