"use client";
import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCheck,
  CheckCircle2,
  LocateFixed,
  MapPin,
  Play,
  RefreshCw,
  Route as RouteIcon,
  ShieldCheck,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import {
  ISSUE_LABEL,
  type FacilityCollection,
  type Integrity,
  type LogEvent,
  type QueueSummary,
  type Ticket,
  type TicketStatus,
  type WardCollection,
} from "@/lib/types";
import {
  Badge,
  Btn,
  Card,
  Field,
  inputCls,
  Notice,
  Spinner,
  Table,
} from "@/components/ui";
import { Shell } from "@/components/Shell";
import { MUNICIPAL_SUBNAV, cleanLabel } from "@/lib/nav";
import { MapLegend, SanitationMap } from "@/components/SanitationMap";
import { ChainTimeline } from "@/components/ChainTimeline";
import { TicketBadge, ticketTone } from "@/components/TicketBadge";

const STATUSES: TicketStatus[] = ["ROUTED", "IN_PROGRESS", "RESOLVED", "UNROUTABLE"];
const tone = ticketTone;

export default function SanitationMapPage() {
  const [filter, setFilter] = useState<TicketStatus | "ALL">("ALL");
  const wards = useLoad(() => api<WardCollection>("/geo/wards"));
  const facilities = useLoad(() => api<FacilityCollection>("/geo/facilities"));
  const tickets = useLoad(
    () => api<Ticket[]>(`/sanitation/tickets${filter === "ALL" ? "" : `?status=${filter}`}`),
    [filter]
  );
  const queues = useLoad(() => api<QueueSummary[]>("/sanitation/queues"));

  const [sel, setSel] = useState<number | null>(null);
  const detail = useLoad(() => api<Ticket>(`/sanitation/tickets/${sel}`), [sel], sel !== null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [wardId, setWardId] = useState("");
  const [reason, setReason] = useState("");
  const [events, setEvents] = useState<LogEvent[] | null>(null);
  const [integrity, setIntegrity] = useState<Integrity | null>(null);

  useEffect(() => {
    setEvents(null);
    setIntegrity(null);
    setErr(null);
    setNote("");
    setReason("");
    setWardId("");
  }, [sel]);

  async function act(path: string, body: unknown) {
    setBusy(true);
    setErr(null);
    try {
      await api(`/sanitation/tickets/${sel}/${path}`, { body });
      await Promise.all([detail.reload(), tickets.reload(), queues.reload()]);
      setEvents(null);
      setIntegrity(null);
      setNote("");
      setReason("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true);
    setErr(null);
    try {
      const [ev, v] = await Promise.all([
        api<LogEvent[]>(`/sanitation/tickets/${sel}/events`),
        api<Integrity>(`/sanitation/tickets/${sel}/verify-integrity`),
      ]);
      setEvents(ev);
      setIntegrity(v);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Verification failed.");
    } finally {
      setBusy(false);
    }
  }

  const t = detail.data;
  const rows = tickets.data ?? [];

  return (
    <Shell
      allow={["MUNICIPAL_ADMIN"]}
      accent="proc"
      title="Sanitation & Grievance Operations"
      subtitle="Geolocated citizen reports automatically matched with territorial ward queues, tracked through resolution and audit trails."
      subnav={MUNICIPAL_SUBNAV}
    >
      {(wards.error || tickets.error) && (
        <div className="mb-4">
          <Notice tone="flag" title="Map Data Notice">
            {wards.error ?? tickets.error}
          </Notice>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        
        {/* Main Column: Interactive Map & Legend */}
        <div className="space-y-4 lg:col-span-7">
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter tickets">
            {(["ALL", ...STATUSES] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setFilter(s)}
                aria-pressed={filter === s}
                className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                  filter === s
                    ? "border-ink bg-ink text-white shadow-xs"
                    : "border-line bg-white text-ink-soft hover:bg-paper"
                }`}
              >
                {s === "ALL"
                  ? "All Tickets"
                  : s === "UNROUTABLE"
                    ? "Manual Triage"
                    : s.replace("_", " ").toLowerCase()}
              </button>
            ))}
          </div>

          <SanitationMap
            wards={wards.data}
            facilities={facilities.data}
            tickets={rows}
            height={460}
            selectedId={sel}
            onSelect={setSel}
          />

          <div className="rounded-xl border border-line bg-white p-3 shadow-xs">
            <MapLegend />
            <p className="mt-2 text-[11px] text-ink-soft">
              Report positions are recorded by citizen devices. Territorial boundaries reflect registered municipal ward polygons. Map functions offline without third-party tile dependencies.
            </p>
          </div>
        </div>

        {/* Side Column: Ward Queues & Selected Ticket Detail */}
        <div className="space-y-6 lg:col-span-5">
          {/* Ward Queues Summary Card */}
          <Card title="Ward Resolution Queues">
            {!queues.data ? (
              <Spinner label="Loading queues" />
            ) : (
              <ul className="space-y-2 max-h-52 overflow-y-auto pr-1">
                {queues.data.map((q) => (
                  <li key={q.code} className="rounded-xl border border-line bg-paper/50 p-2.5">
                    <p className="text-xs font-bold text-ink">{q.name}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {STATUSES.filter((s) => (q.counts[s] ?? 0) > 0 || q.id !== null).map((s) =>
                        q.id === null && s !== "UNROUTABLE" ? null : (
                          <Badge key={s} tone={tone[s]}>
                            {q.counts[s] ?? 0} {s === "UNROUTABLE" ? "unrouted" : s.replace("_", " ").toLowerCase()}
                          </Badge>
                        )
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Selected Ticket Action Panel */}
          <Card
            tone="proc"
            title={t ? `Sanitation Ticket #${t.id}` : "Ticket Details"}
            right={t && <TicketBadge s={t.status} />}
          >
            {!sel && (
              <p className="py-4 text-center text-xs text-ink-soft">
                Select a marker on the map or choose a ticket from the table below to inspect details.
              </p>
            )}

            {sel && !t && !detail.error && <Spinner label="Loading ticket details" />}
            {detail.error && <Notice tone="flag">{detail.error}</Notice>}

            {t && (
              <div className="space-y-4 text-sm">
                <div className="rounded-xl bg-paper/60 p-3 border border-line/60">
                  <p className="font-bold text-ink">{ISSUE_LABEL[t.issue_type]}</p>
                  <p className="mt-1 text-xs text-ink-soft leading-relaxed">{t.description}</p>
                </div>

                <dl className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg bg-white p-2 border border-line">
                    <dt className="text-ink-soft">Jurisdiction Ward</dt>
                    <dd className="font-semibold text-ink mt-0.5">{cleanLabel(t.ward?.name) || "Unassigned"}</dd>
                  </div>
                  <div className="rounded-lg bg-white p-2 border border-line">
                    <dt className="text-ink-soft">Assigned Queue</dt>
                    <dd className="font-semibold text-ink mt-0.5">{cleanLabel(t.queue?.name) || "Central Triage"}</dd>
                  </div>
                  <div className="rounded-lg bg-white p-2 border border-line">
                    <dt className="text-ink-soft">Reported Timestamp</dt>
                    <dd className="font-medium text-ink mt-0.5">{fmtDate(t.created_at)}</dd>
                  </div>
                  <div className="rounded-lg bg-white p-2 border border-line">
                    <dt className="text-ink-soft">Coordinates</dt>
                    <dd className="font-mono font-medium text-ink mt-0.5">
                      {t.location
                        ? `${t.location.latitude.toFixed(4)}, ${t.location.longitude.toFixed(4)}`
                        : "None"}
                    </dd>
                  </div>
                </dl>

                {t.location && (
                  <p className="flex items-start gap-1.5 text-xs text-proc-700 bg-proc-50 p-2 rounded-lg border border-proc-100">
                    <LocateFixed className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      {t.location.note}
                      {t.location.accuracy_m != null
                        ? ` (accuracy ±${Math.round(t.location.accuracy_m)}m)`
                        : ""}
                    </span>
                  </p>
                )}

                {/* Routing Decisions History */}
                <div>
                  <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-ink-faint">
                    Routing Decision History
                  </p>
                  <ol className="space-y-1.5 max-h-36 overflow-y-auto">
                    {t.routing_history?.map((d) => (
                      <li
                        key={d.id}
                        className="rounded-lg border border-line bg-paper/60 p-2 text-xs"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-ink">
                            {d.outcome === "ROUTED" ? `Routed → ${d.queue}` : "Manual Triage Required"}
                          </span>
                          <span className="text-[10px] text-ink-faint">
                            Event #{d.event_id}
                          </span>
                        </div>
                        <p className="mt-0.5 text-ink-soft text-[11px]">
                          Method: {d.method.replace("_", " ").toLowerCase()} · {d.reason.replaceAll("_", " ").toLowerCase()}
                        </p>
                        <span className="mt-1 block text-[10px] text-ink-faint">
                          {fmtDate(d.decided_at)} · {d.decided_by_user_id ? `Assigned by Officer #${d.decided_by_user_id}` : "Automated spatial routing"}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>

                {t.resolution_note && (
                  <Notice tone="ok" title="Resolution Confirmed">
                    {t.resolution_note}
                  </Notice>
                )}

                {/* Actions depending on ticket status */}
                {t.status === "ROUTED" && (
                  <Btn
                    tone="track"
                    busy={busy}
                    onClick={() => act("status", { status: "IN_PROGRESS" })}
                    className="w-full"
                  >
                    <Play className="h-4 w-4" />
                    Dispatch Ward Crew (Start Work)
                  </Btn>
                )}

                {t.status === "IN_PROGRESS" && (
                  <div className="space-y-3 rounded-xl border border-line bg-paper/50 p-3">
                    <Field label="Resolution Notes">
                      <input
                        className={inputCls}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="Detail action taken (e.g. Crew cleared overflowing bin)"
                      />
                    </Field>
                    <Btn
                      tone="ok"
                      busy={busy}
                      disabled={note.trim().length < 3 || busy}
                      onClick={() => act("status", { status: "RESOLVED", note })}
                      className="w-full"
                    >
                      <CheckCheck className="h-4 w-4" />
                      Mark Resolved
                    </Btn>
                  </div>
                )}

                {(t.status === "UNROUTABLE" || t.status === "ROUTED") && (
                  <details
                    className="rounded-xl border border-line bg-white p-3"
                    open={t.status === "UNROUTABLE"}
                  >
                    <summary className="cursor-pointer text-xs font-bold uppercase tracking-wider text-ink flex items-center gap-1.5">
                      <RouteIcon className="h-4 w-4 text-track-600" />
                      {t.status === "UNROUTABLE" ? "Manual Triage & Routing" : "Re-route Ticket"}
                    </summary>
                    <div className="mt-3 space-y-3">
                      <Field label="Administrative Reason">
                        <input
                          className={inputCls}
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          placeholder="Reason for manual assignment (recorded in audit trail)"
                        />
                      </Field>
                      <Field label="Assign Target Ward">
                        <select
                          className={inputCls}
                          value={wardId}
                          onChange={(e) => setWardId(e.target.value)}
                        >
                          <option value="">Choose a ward…</option>
                          {wards.data?.features.map((w) => (
                            <option key={w.properties.id} value={w.properties.id}>
                              {w.properties.name}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <div className="flex flex-wrap gap-2 pt-1">
                        <Btn
                          tone="proc"
                          busy={busy}
                          disabled={!wardId || reason.trim().length < 5 || busy}
                          onClick={() =>
                            act("reroute", { ward_id: Number(wardId), reason })
                          }
                          className="!py-1.5 text-xs"
                        >
                          Assign Manually
                        </Btn>
                        <Btn
                          tone="neutral"
                          variant="outline"
                          busy={busy}
                          disabled={reason.trim().length < 5 || busy}
                          onClick={() => act("reroute", { reason })}
                          className="!py-1.5 text-xs"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          Retry Spatial Routing
                        </Btn>
                      </div>
                    </div>
                  </details>
                )}

                {/* Audit Trail Verification for this Ticket */}
                <div className="border-t border-line pt-3">
                  <Btn
                    tone="neutral"
                    variant="outline"
                    busy={busy}
                    onClick={verify}
                    className="w-full !py-1.5 text-xs"
                  >
                    <ShieldCheck className="h-4 w-4" />
                    Verify Ticket Audit Chain ({t.chain_id})
                  </Btn>

                  {err && <div className="mt-2"><Notice tone="flag">{err}</Notice></div>}

                  {integrity && (
                    <div className="mt-2">
                      {integrity.valid ? (
                        <Notice
                          tone="ok"
                          title={`Chain Intact: ${integrity.total_events} Events Verified`}
                        >
                          SHA-256 hash verified from ticket creation through resolution.
                        </Notice>
                      ) : (
                        <Notice
                          tone="flag"
                          title={`Tampering detected at event index ${integrity.broken_at_index}`}
                        >
                          {integrity.reason}
                        </Notice>
                      )}
                    </div>
                  )}

                  {events && (
                    <div className="mt-3">
                      <ChainTimeline events={events} result={integrity} />
                    </div>
                  )}
                </div>
              </div>
            )}
          </Card>
        </div>

      </div>

      {/* Bottom Table: All Tickets */}
      <Card className="mt-6" title="Sanitation Tickets Register">
        <Table
          empty="No sanitation tickets match the selected status filter."
          head={[
            "Ticket #",
            "Issue Type",
            "Ward → Queue",
            "Status",
            "Reported At",
            "Coordinates",
          ]}
          rows={rows.map((r) => [
            <button
              key="i"
              type="button"
              onClick={() => setSel(r.id)}
              className="font-bold text-track-700 underline hover:text-track-800"
            >
              #{r.id}
            </button>,
            ISSUE_LABEL[r.issue_type],
            r.ward ? `${cleanLabel(r.ward.name)} → ${cleanLabel(r.queue?.name)}` : "Central Triage",
            <TicketBadge key="s" s={r.status} />,
            fmtDate(r.created_at),
            r.location ? (
              <span key="l" className="font-mono text-xs">
                {r.location.latitude.toFixed(4)}, {r.location.longitude.toFixed(4)}
              </span>
            ) : (
              "—"
            ),
          ])}
        />
      </Card>
    </Shell>
  );
}
