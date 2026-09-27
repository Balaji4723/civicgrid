"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { api, session } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability } from "@/lib/nav";
import type { DispositionStatus, FinalDisposition } from "@/lib/types";
import { Badge, Card, Notice, Spinner, Table, type Tone } from "@/components/ui";
import { Shell } from "@/components/Shell";

const STATUSES = ["ALL", "RECORDED", "VERIFIED", "CANCELLED"] as const;
const tone: Record<DispositionStatus, Tone> = {
  RECORDED: "track",
  VERIFIED: "ok",
  CANCELLED: "neutral",
};

export default function FinalDispositionWorkspace() {
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const isProc = cap === "PROCESSING";
  const subnav = getSubnavForUser(me);

  const dispositions = useLoad(() => api<FinalDisposition[]>("/final-dispositions"));
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("ALL");
  const rows = (dispositions.data ?? []).filter((f) => status === "ALL" || f.status === status);

  // Group by load to make split dispositions (recovered recycling vs residual landfill) visually evident
  const byLoad = rows.reduce<Record<string, FinalDisposition[]>>((acc, f) => {
    (acc[f.digital_load_id] ??= []).push(f);
    return acc;
  }, {});

  const title = isProc
    ? "Final Dispositions & Diversion Certificates"
    : "Final Dispositions Oversight";

  const subtitle = isProc
    ? "FACILITY OPERATIONS · Certified endpoints for processed load streams — recovered material recycling, co-processing, and certified landfill containment."
    : "MUNICIPAL READ-ONLY OVERSIGHT · Read-only oversight of terminal disposition certificates, recovery rates, and landfill diversion records.";

  return (
    <Shell
      allow={["FACILITY", "MUNICIPAL_ADMIN"]}
      accent="ok"
      title={title}
      subtitle={subtitle}
      subnav={subnav}
    >
      <div className="mb-6">
        <Notice tone="neutral" title="Disposition Certification">
          To record or verify a final disposition, open the associated Digital Load&apos;s journey page.
        </Notice>
      </div>

      <Card title="Filter by Disposition Status" className="mb-6">
        <div className="flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                status === s
                  ? "border-ok-600 bg-ok-50 text-ok-700 shadow-xs"
                  : "border-line text-ink-soft hover:bg-paper hover:text-ink"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </Card>

      <Card
        title={`Final Dispositions (${rows.length})`}
        right={
          <span className="text-xs text-ink-soft">
            Certified terminal endpoints
          </span>
        }
      >
        {dispositions.loading && !dispositions.data && (
          <Spinner label="Loading final dispositions" />
        )}
        {dispositions.error && (
          <Notice tone="flag" title="Failed to load">{dispositions.error}</Notice>
        )}
        {dispositions.data && (
          <Table
            head={[
              "Disposition #",
              "Digital Load ID",
              "Destination Facility",
              "Material Type",
              "Quantity",
              "Status",
              "Certified At",
              "Action",
            ]}
            empty="No final disposition records match the selected status filter."
            rows={rows.map((f) => [
              `#${f.id}`,
              <span key="l" className="font-mono font-bold text-ink">
                {f.digital_load_id}
              </span>,
              f.destination_facility ?? `Facility ${f.destination_facility_id}`,
              f.disposition_type.replaceAll("_", " ").toLowerCase(),
              `${f.quantity_kg} kg`,
              <Badge key="s" tone={tone[f.status]}>
                {f.status}
              </Badge>,
              fmtDate(f.timestamp),
              <Link
                key="link"
                href={`/authority/load/${f.digital_load_id}`}
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
