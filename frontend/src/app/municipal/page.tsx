"use client";
import Link from "next/link";
import { useState } from "react";
import {
  Building2,
  CheckCircle2,
  FileCheck2,
  MapPin,
  Package,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Truck,
  Users,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import {
  DISC_STATUSES,
  type DiscStatus,
  type Discrepancy,
  type Integrity,
  type LoadRow,
  type LogEvent,
} from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Kpi,
  LoadBadge,
  Notice,
  Spinner,
  StatusBadge,
  Table,
} from "@/components/ui";
import { Shell } from "@/components/Shell";
import { MUNICIPAL_SUBNAV, cleanLabel } from "@/lib/nav";
import { ChainTimeline } from "@/components/ChainTimeline";

interface Stats {
  households: number;
  workers: number;
  loads: number;
  open_discrepancies: number;
  closed_discrepancies: number;
}
interface HH {
  id: number;
  ward: string;
  address: string;
  owner_name: string;
  civic_credits: number;
}
interface Wk {
  id: number;
  name: string;
  route_id: number;
  ward: string;
}

const ageOf = (iso: string) => {
  const h = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3.6e6));
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
};

export default function MunicipalDashboard() {
  const stats = useLoad(() => api<Stats>("/stats"));
  const loads = useLoad(() => api<LoadRow[]>("/loads"));
  const [tab, setTab] = useState<"loads" | "households" | "workers">("loads");
  const hh = useLoad(() => api<HH[]>("/households"), [], tab === "households");
  const wk = useLoad(() => api<Wk[]>("/workers"), [], tab === "workers");

  const [filter, setFilter] = useState<DiscStatus | "ALL">("ALL");
  const discs = useLoad(
    () => api<Discrepancy[]>(`/discrepancy${filter === "ALL" ? "" : `?status=${filter}`}`),
    [filter]
  );

  const [loadId, setLoadId] = useState("DL-1002");
  const [events, setEvents] = useState<LogEvent[] | null>(null);
  const [result, setResult] = useState<Integrity | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const chainEvents = useLoad(() => api<LogEvent[]>(`/loads/${loadId}/events`), [loadId]);

  // Phase 3 counts for city-wide operational oversight
  const processing = useLoad(() => api<{ status: string }[]>("/processing"));
  const handoffs = useLoad(() => api<{ status: string }[]>("/handoffs"));
  const exceptions = useLoad(() => api<{ status: string }[]>("/disposal-exceptions"));

  async function verifyChain() {
    setVerifying(true);
    setErr(null);
    try {
      const [r, ev] = await Promise.all([
        api<Integrity>(`/loads/${loadId}/verify-integrity`),
        api<LogEvent[]>(`/loads/${loadId}/events`),
      ]);
      setResult(r);
      setEvents(ev);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Cryptographic verification check failed.");
    } finally {
      setVerifying(false);
    }
  }

  function pickLoad(id: string) {
    setLoadId(id);
    setResult(null);
    setEvents(null);
    setErr(null);
  }

  const shownEvents = events ?? chainEvents.data;

  return (
    <Shell
      allow={["MUNICIPAL_ADMIN"]}
      accent="proc"
      title="MUNICIPAL AUTHORITY — City-Wide Read-Only Governance"
      subtitle="Municipal waste metrics, stream integrity governance, discrepancy oversight, and SHA-256 tamper-evident trail verification."
      subnav={MUNICIPAL_SUBNAV}
    >
      {/* Three Connected Accountability Dimensions */}
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-ok-200 bg-ok-50/70 p-4">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-ok-600 font-mono text-xs font-bold text-white">A</span>
            <h3 className="text-xs font-bold tracking-tight text-ok-950 uppercase">Household Compliance</h3>
          </div>
          <p className="text-xs text-ok-800 leading-relaxed">
            Source segregation at citizen doorstep. Tracked via household collections and incentivized through Civic Credits.
          </p>
          <div className="mt-3 flex items-center justify-between text-[11px] font-semibold text-ok-900 border-t border-ok-200/60 pt-2">
            <span>City Segregation Rate</span>
            <span className="font-mono">83.3% Segregated</span>
          </div>
        </div>

        <div className="rounded-xl border border-track-200 bg-track-50/70 p-4">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-track-600 font-mono text-xs font-bold text-white">B</span>
            <h3 className="text-xs font-bold tracking-tight text-track-950 uppercase">Collection Accountability</h3>
          </div>
          <p className="text-xs text-track-800 leading-relaxed">
            Trustworthy collection logs. Enforced via secret Random Audits, camera evidence gating, and tamper-evident event hashing.
          </p>
          <div className="mt-3 flex items-center justify-between text-[11px] font-semibold text-track-900 border-t border-track-200/60 pt-2">
            <span>Random Audit Coverage</span>
            <span className="font-mono">1 Target / Active Beat</span>
          </div>
        </div>

        <div className="rounded-xl border border-proc-200 bg-proc-50/70 p-4">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-proc-600 font-mono text-xs font-bold text-white">C</span>
            <h3 className="text-xs font-bold tracking-tight text-proc-950 uppercase">Stream Integrity</h3>
          </div>
          <p className="text-xs text-proc-800 leading-relaxed">
            Segregation preserved downstream. Verified by weighbridge cross-check, independent audit corroboration, and custody logs.
          </p>
          <div className="mt-3 flex items-center justify-between text-[11px] font-semibold text-proc-900 border-t border-proc-200/60 pt-2">
            <span>Cross-Check Verification</span>
            <span className="font-mono">Automated Cross-Check</span>
          </div>
        </div>
      </div>

      {/* Top Oversight Metrics */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Registered Households" value={stats.data?.households ?? "—"} tone="ok" />
        <Kpi label="Active Field Workers" value={stats.data?.workers ?? "—"} tone="track" />
        <Kpi label="Digital Loads Logged" value={stats.data?.loads ?? "—"} tone="auth" />
        <Kpi
          label="Open Discrepancies"
          value={stats.data?.open_discrepancies ?? "—"}
          tone="flag"
        />
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Kpi
          label="Active Processing Batches"
          value={processing.data?.filter((p) => p.status === "IN_PROGRESS").length ?? "—"}
          tone="proc"
        />
        <Kpi
          label="In-Transit Handoffs"
          value={
            handoffs.data?.filter((h) => h.status === "PENDING" || h.status === "IN_TRANSIT")
              .length ?? "—"
          }
          tone="track"
        />
        <Kpi
          label="Open Disposal Exceptions"
          value={
            exceptions.data?.filter(
              (e) =>
                e.status === "RAISED" ||
                e.status === "PENDING_AUTHORIZATION" ||
                e.status === "AUTHORIZED"
            ).length ?? "—"
          }
          tone="flag"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        
        {/* Main Column: Cryptographic Audit Trail Verification Tool */}
        <div className="space-y-6 lg:col-span-7">
          <Card
            tone="proc"
            title="SHA-256 Audit Trail Cryptographic Verifier"
            right={<Badge tone="neutral">SHA-256 Hash Chain</Badge>}
          >
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-ink-soft mr-1">Select Load:</span>
              {loads.data?.slice(0, 6).map((l) => (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => pickLoad(l.id)}
                  aria-pressed={loadId === l.id}
                  className={`rounded-lg border px-2.5 py-1 font-mono text-xs font-bold transition-all ${
                    loadId === l.id
                      ? "border-proc-600 bg-proc-50 text-proc-800 shadow-xs"
                      : "border-line bg-white hover:bg-paper text-ink"
                  }`}
                >
                  {l.id}
                </button>
              ))}
              <Btn tone="proc" busy={verifying} onClick={verifyChain} className="!py-1 text-xs">
                <ShieldCheck className="h-3.5 w-3.5" />
                Verify SHA-256 Chain
              </Btn>
              <Link
                href={`/authority/load/${loadId}`}
                className="ml-auto text-xs font-semibold text-auth-700 underline"
              >
                Open Full Journey &rarr;
              </Link>
            </div>

            {err && <div className="mb-4"><Notice tone="flag">{err}</Notice></div>}

            {result && (
              <div className="mb-4">
                {result.valid ? (
                  <Notice
                    tone="ok"
                    title={`Chain Integrity Confirmed: ${result.total_events} Events Verified`}
                  >
                    Every state transition hash links back to the genesis event with zero discrepancies. Head Hash: <span className="font-mono text-xs">{result.head_hash.slice(0, 20)}…</span>
                  </Notice>
                ) : (
                  <Notice
                    tone="flag"
                    title={`Cryptographic Anomaly at Event #${result.broken_event_id} (Index ${result.broken_at_index})`}
                  >
                    {result.reason}
                  </Notice>
                )}
              </div>
            )}

            {!shownEvents ? (
              <Spinner label="Retrieving chain events" />
            ) : (
              <ChainTimeline events={shownEvents} result={result} />
            )}
          </Card>
        </div>

        {/* Side Column: Discrepancies Oversight */}
        <div className="space-y-6 lg:col-span-5">
          <Card
            title="Cross-Check Discrepancies"
            right={
              <Link
                href="/authority/discrepancies"
                className="text-xs font-semibold text-auth-700 hover:underline"
              >
                All Cases &rarr;
              </Link>
            }
          >
            <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter status">
              {(["ALL", ...DISC_STATUSES] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setFilter(s)}
                  aria-pressed={filter === s}
                  className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                    filter === s
                      ? "border-ink bg-ink text-white"
                      : "border-line bg-white text-ink-soft hover:bg-paper"
                  }`}
                >
                  {s === "ALL" ? "All" : s.replace("_", " ").toLowerCase()}
                </button>
              ))}
            </div>

            <Table
              empty="No discrepancies match this status filter."
              head={["Case #", "Load ID", "Type", "Status", "Age"]}
              rows={(discs.data ?? []).map((d) => [
                <Link
                  key="i"
                  href={`/authority/discrepancy/${d.id}`}
                  className="font-bold text-auth-700 underline"
                >
                  #{d.id}
                </Link>,
                <span key="l" className="font-mono text-xs font-medium">
                  {d.load_id}
                </span>,
                d.type,
                <StatusBadge key="s" status={d.status} />,
                <span key="a" className="text-xs text-ink-soft">
                  {ageOf(d.created_at)}
                </span>,
              ])}
            />
          </Card>
        </div>

      </div>

      {/* Bottom Card: Municipal Master Records */}
      <Card
        className="mt-6"
        title="Municipal Operational Records"
        right={
          <div className="flex gap-1" role="tablist">
            {(["loads", "households", "workers"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`rounded-lg px-3 py-1 text-xs font-semibold capitalize transition-colors ${
                  tab === t
                    ? "bg-ink text-white shadow-xs"
                    : "text-ink-soft hover:bg-paper hover:text-ink"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        }
      >
        {tab === "loads" && (
          <Table
            head={[
              "Digital Load ID",
              "Ward",
              "Assigned Worker",
              "Declared Weight",
              "Status",
              "Generated",
              "Journey",
            ]}
            rows={(loads.data ?? []).map((l) => [
              <span key="i" className="font-mono font-bold text-ink">
                {l.id}
              </span>,
              cleanLabel(l.ward),
              l.worker ?? "Unassigned",
              l.declared_quantity_kg ? `${l.declared_quantity_kg} kg` : "—",
              <LoadBadge key="s" status={l.status} />,
              fmtDate(l.generated_at),
              <Link
                key="j"
                href={`/authority/load/${l.id}`}
                className="text-xs font-semibold text-auth-700 underline"
              >
                View Journey &rarr;
              </Link>,
            ])}
          />
        )}

        {tab === "households" &&
          (hh.data ? (
            <Table
              head={["Household ID", "Resident / Owner", "Address", "Ward", "Civic Credits"]}
              rows={hh.data.map((h) => [
                `HH-${h.id}`,
                h.owner_name,
                h.address,
                cleanLabel(h.ward),
                <Badge key="c" tone="ok">
                  {h.civic_credits} Credits
                </Badge>,
              ])}
            />
          ) : (
            <Spinner label="Loading household directory" />
          ))}

        {tab === "workers" &&
          (wk.data ? (
            <Table
              head={["Worker ID", "Operator Name", "Assigned Route", "Jurisdiction Ward"]}
              rows={wk.data.map((w) => [
                `WK-${w.id}`,
                w.name,
                `Route ${w.route_id}`,
                cleanLabel(w.ward),
              ])}
            />
          ) : (
            <Spinner label="Loading field worker directory" />
          ))}
      </Card>
    </Shell>
  );
}
