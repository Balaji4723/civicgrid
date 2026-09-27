"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Truck } from "lucide-react";
import { api, session } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";
import type { Handoff, HandoffStatus } from "@/lib/types";
import { Badge, Card, Notice, Spinner, Table, type Tone } from "@/components/ui";
import { Shell } from "@/components/Shell";

const STATUSES = ["ALL", "PENDING", "IN_TRANSIT", "COMPLETED", "CANCELLED"] as const;
const tone: Record<HandoffStatus, Tone> = {
  PENDING: "track",
  IN_TRANSIT: "proc",
  COMPLETED: "ok",
  CANCELLED: "neutral",
};

export default function HandoffsWorkspace() {
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isProc = cap === "PROCESSING";
  const subnav = getSubnavForUser(me);

  const handoffs = useLoad(() => api<Handoff[]>("/handoffs"));
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("ALL");
  const rows = (handoffs.data ?? []).filter((h) => status === "ALL" || h.status === status);

  const title = isProc
    ? "Inter-Facility Transfer Handoffs"
    : "Transfer Handoffs Oversight";

  const subtitle = isProc
    ? "FACILITY OPERATIONS · Custody transit records for material moved between processing plants, MRFs, and specialized disposition sites."
    : "MUNICIPAL READ-ONLY OVERSIGHT · City-wide oversight of material transfers and chain-of-custody in transit between facilities.";

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="track"
      title={title}
      subtitle={subtitle}
      subnav={subnav}
    >
      <div className="mb-6">
        <Notice tone="neutral" title="Handoff Generation">
          This workspace displays transfer handoffs city-wide. To generate a new handoff or complete transit verification, open the associated Digital Load&apos;s journey page.
        </Notice>
      </div>

      <Card title="Filter by Transit Status" className="mb-6">
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                status === s
                  ? "border-track-600 bg-track-50 text-track-700 shadow-xs"
                  : "border-line text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      </Card>

      <Card
        title={`Inter-Facility Handoffs (${rows.length})`}
        right={
          <span className="text-xs text-ink-soft">
            Custody transfer events
          </span>
        }
      >
        {handoffs.loading && !handoffs.data && <Spinner label="Loading inter-facility handoffs" />}
        {handoffs.error && <Notice tone="flag" title="Failed to load">{handoffs.error}</Notice>}
        {handoffs.data && (
          <Table
            head={[
              "Handoff #",
              "Digital Load ID",
              "Origin Facility",
              "Destination Facility",
              "Stream",
              "Quantity",
              "Status",
              "Timestamp",
              "Action",
            ]}
            empty="No inter-facility handoffs match the selected status filter."
            rows={rows.map((h) => [
              `#${h.id}`,
              <span key="l" className="font-mono font-bold text-ink">
                {h.digital_load_id}
              </span>,
              h.source_facility ?? `Facility ${h.source_facility_id}`,
              h.destination_facility ?? `Facility ${h.destination_facility_id}`,
              h.waste_stream,
              `${h.quantity_kg} kg`,
              <Badge key="s" tone={tone[h.status]}>
                {h.status.replace("_", " ")}
              </Badge>,
              fmtDate(h.timestamp),
              <Link
                key="link"
                href={`/authority/load/${h.digital_load_id}`}
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
