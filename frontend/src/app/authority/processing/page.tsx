"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, RotateCcw } from "lucide-react";
import { api, session } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";
import type { ProcessingRecord, ProcessingStatus } from "@/lib/types";
import { Badge, Card, Notice, Spinner, Table, type Tone } from "@/components/ui";
import { Shell } from "@/components/Shell";

const STATUSES = ["ALL", "PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"] as const;
const tone: Record<ProcessingStatus, Tone> = {
  PENDING: "track",
  IN_PROGRESS: "proc",
  COMPLETED: "ok",
  CANCELLED: "neutral",
};

export default function ProcessingWorkspace() {
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isProc = cap === "PROCESSING";
  const subnav = getSubnavForUser(me);

  const records = useLoad(() => api<ProcessingRecord[]>("/processing"));
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("ALL");
  const rows = (records.data ?? []).filter((r) => status === "ALL" || r.status === status);

  const title = isProc
    ? "FACILITY OPERATIONS"
    : "Material Processing Oversight";

  const subtitle = isProc
    ? "Downstream Processing & Material Recovery · Secondary segregation, MRF sorting, RDF bail processing, and organic composting."
    : "MUNICIPAL READ-ONLY OVERSIGHT · City-wide inspection of facility processing batches, recovery yields, and residual stream tracking.";


  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="proc"
      title={title}
      subtitle={subtitle}
      subnav={subnav}
    >
      <div className="mb-6">
        <Notice tone="neutral" title="Process Initialization">
          To initiate a new processing batch or update batch status, open the specific Digital Load&apos;s journey page.
        </Notice>
      </div>

      <Card title="Filter by Status" className="mb-6">
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                status === s
                  ? "border-proc-600 bg-proc-50 text-proc-700 shadow-xs"
                  : "border-line text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      </Card>

      <Card
        title={`Processing Batches (${rows.length})`}
        right={
          <span className="text-xs text-ink-soft">
            City-wide facility processing
          </span>
        }
      >
        {records.loading && !records.data && <Spinner label="Loading processing batches" />}
        {records.error && <Notice tone="flag" title="Failed to load">{records.error}</Notice>}
        {records.data && (
          <Table
            head={[
              "Batch #",
              "Digital Load ID",
              "Facility",
              "Stream",
              "Method",
              "Processed",
              "Recovered",
              "Residual",
              "Status",
              "Started At",
              "Action",
            ]}
            empty="No processing batches match the selected status filter."
            rows={rows.map((r) => [
              `#${r.id}`,
              <span key="l" className="font-mono font-bold text-ink">
                {r.digital_load_id}
              </span>,
              r.facility ?? `Facility ${r.facility_id}`,
              r.waste_stream,
              r.processing_method.replaceAll("_", " ").toLowerCase(),
              `${r.processed_quantity_kg} kg`,
              `${r.recovered_quantity_kg} kg`,
              `${r.residual_quantity_kg} kg`,
              <Badge key="s" tone={tone[r.status]}>
                {r.status.replace("_", " ")}
              </Badge>,
              fmtDate(r.started_at),
              <Link
                key="link"
                href={`/authority/load/${r.digital_load_id}`}
                className="inline-flex items-center gap-1 text-xs font-semibold text-auth-700 underline hover:text-auth-800"
              >
                Inspect Load &rarr;
              </Link>,
            ])}
          />
        )}
      </Card>
    </Shell>
  );
}
