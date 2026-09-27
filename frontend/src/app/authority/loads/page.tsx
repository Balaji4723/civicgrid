"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Package, Truck } from "lucide-react";
import { api, session } from "@/lib/api";
import { useLoad, fmtDate } from "@/lib/hooks";
import { getSubnavForUser, getUserCapability, cleanLabel } from "@/lib/nav";
import type { LoadRow } from "@/lib/types";
import { Card, LoadBadge, Notice, Spinner, Table } from "@/components/ui";
import { Shell } from "@/components/Shell";

const STATUSES = ["ALL", "COLLECTING", "DECLARED", "VERIFIED", "DISPUTED", "SETTLED"] as const;

export default function IncomingLoadsPage() {
  const me = typeof window !== "undefined" ? session.user() : null;
  const cap = getUserCapability(me);
  const subnav = getSubnavForUser(me);

  const loads = useLoad(() => api<LoadRow[]>("/loads"));
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("ALL");

  const rows = (loads.data ?? []).filter((l) => status === "ALL" || l.status === status);

  const title =
    cap === "RECEIVING"
      ? "Incoming Loads & Weighbridge Queue"
      : cap === "PROCESSING"
      ? "Digital Loads & Processing Intake"
      : cap === "INDEPENDENT_VERIFIER"
      ? "Digital Loads Register (Independent Audit View)"
      : "Digital Loads Master Register";

  const subtitle =
    cap === "RECEIVING"
      ? "RECEIVING BAY · Incoming Digital Loads from completed collection trips awaiting weighbridge intake."
      : cap === "PROCESSING"
      ? "FACILITY OPERATIONS · Digital Loads verified by weighbridge intake available for downstream batch processing."
      : cap === "INDEPENDENT_VERIFIER"
      ? "INDEPENDENT VERIFICATION · Digital Loads register for sampling draws, multi-party audits, and discrepancy corroboration."
      : "MUNICIPAL READ-ONLY OVERSIGHT · Master register of all Digital Loads, collection declarations, weighbridge actuals, and journey status.";

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
              {s}
            </button>
          ))}
        </div>
      </Card>

      <Card
        title={`Registered Digital Loads (${rows.length})`}
        right={
          <span className="text-xs text-ink-soft">
            Real-time backend registry
          </span>
        }
      >
        {loads.loading && !loads.data && <Spinner label="Loading digital loads register" />}
        {loads.error && <Notice tone="flag" title="Failed to load">{loads.error}</Notice>}
        {loads.data && (
          <Table
            head={[
              "Digital Load ID",
              "Collection Vehicle",
              "Trip Code",
              "Route / Ward",
              "Status",
              "Discrepancies",
              "Generated",
              "Action",
            ]}
            empty="No loads found matching the selected filter."
            rows={rows.map((l) => [
              <span key="id" className="font-mono font-bold text-ink">
                {l.id}
              </span>,
              <span key="v" className="font-bold text-ink">
                {l.vehicle_registration ?? "Assigned Fleet"}
              </span>,
              <span key="tc" className="font-mono text-xs text-ink-soft">
                {l.trip_code ?? "—"}
              </span>,
              cleanLabel(l.ward),
              <LoadBadge key="s" status={l.status} />,
              l.discrepancy_count > 0 ? (
                <span key="d" className="font-bold text-flag-700">
                  {l.discrepancy_count} open
                </span>
              ) : (
                <span key="d" className="text-xs text-ok-700">
                  0
                </span>
              ),
              fmtDate(l.generated_at),
              <Link
                key="l"
                href={
                  cap === "RECEIVING" && l.status === "DECLARED"
                    ? "/receiving"
                    : `/authority/load/${l.id}`
                }
                className="inline-flex items-center gap-1 text-xs font-semibold text-auth-700 underline hover:text-auth-800"
              >
                {cap === "RECEIVING" && l.status === "DECLARED"
                  ? "Record Receiving Bay \u2192"
                  : "Inspect Journey \u2192"}
              </Link>,
            ])}
          />
        )}
      </Card>
    </Shell>
  );
}
