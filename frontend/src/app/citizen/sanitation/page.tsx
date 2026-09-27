"use client";
import { useState } from "react";
import {
  Camera,
  CheckCircle2,
  Clock,
  LocateFixed,
  Send,
} from "lucide-react";
import { api, ApiError, apiUpload } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import {
  ISSUE_LABEL,
  ISSUE_TYPES,
  type IssueType,
  type Ticket,
} from "@/lib/types";
import { Badge, Btn, Card, Field, inputCls, Notice, Spinner } from "@/components/ui";
import { Shell } from "@/components/Shell";
import { CameraCapture, type CaptureResult } from "@/components/CameraCapture";
import { TicketBadge } from "@/components/TicketBadge";
import { cleanLabel } from "@/lib/nav";

export default function SanitationReportsPage() {
  const reports = useLoad(() => api<Ticket[]>("/citizen/sanitation-reports"));

  const [issue, setIssue] = useState<IssueType>("OVERFLOWING_BIN");
  const [text, setText] = useState("");
  const [capture, setCapture] = useState<CaptureResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState<Ticket | null>(null);

  function handleCapture(result: CaptureResult) {
    setCapture(result);
    setErr(null);
    setSent(null);
  }

  async function submitReport() {
    if (!capture) {
      setErr("Please take a photo of the issue before submitting.");
      return;
    }
    setBusy(true);
    setErr(null);
    setSent(null);
    try {
      const form = new FormData();
      form.append("file", capture.file);
      let photoName: string | null = null;
      try {
        const uploaded = await apiUpload<{ filename: string }>("/citizen/sanitation-upload", form);
        photoName = uploaded.filename;
      } catch {
        photoName = capture.file.name;
      }

      const t = await api<Ticket>("/citizen/sanitation-reports", {
        body: {
          description: text,
          issue_type: issue,
          photo_name: photoName,
          latitude: capture.gps?.lat ?? null,
          longitude: capture.gps?.lng ?? null,
          accuracy_m: capture.gps?.accuracy != null ? Math.round(capture.gps.accuracy) : null,
          location_source: "DEVICE_REPORTED",
        },
      });
      setSent(t);
      setText("");
      setCapture(null);
      await reports.reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed to submit sanitation report.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      allow={["CITIZEN"]}
      accent="ok"
      title="Sanitation Reports"
      subtitle="Report civic issues and track your submissions"
    >
      <div className="grid gap-6 lg:grid-cols-12">

        {/* Report Form */}
        <div className="lg:col-span-7 space-y-6">
          <Card tone="ok" title="Report a Sanitation Issue">
            <div className="space-y-4">
              <Field label="Issue Type">
                <select
                  className={inputCls}
                  value={issue}
                  onChange={(e) => setIssue(e.target.value as IssueType)}
                >
                  {ISSUE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {ISSUE_LABEL[t]}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Description">
                <textarea
                  className={inputCls}
                  rows={3}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Describe the issue — be specific about location and condition (e.g. Overflowing bin at the corner of Main St, not cleared for 3 days)"
                />
              </Field>

              {/* Camera — the only evidence capture method */}
              <div>
                <label className="mb-2 block text-sm font-medium text-ink">
                  Photo Evidence <span className="text-flag-600">*</span>
                </label>
                <p className="mb-2.5 text-xs text-ink-soft">
                  Use your device camera to capture the issue. Your GPS location is recorded
                  automatically — you do not need to enter coordinates.
                </p>

                {!capture ? (
                  <CameraCapture
                    label="Open Camera to Capture Issue"
                    onCapture={handleCapture}
                    withGps={true}
                  />
                ) : (
                  <div className="space-y-2.5">
                    <div className="relative overflow-hidden rounded-xl border border-ok-200 bg-ok-50">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={capture.dataUrl}
                        alt="Captured issue photo"
                        className="w-full max-h-52 object-cover"
                      />
                      <div className="absolute top-2 left-2 rounded-full bg-ok-600/90 px-2.5 py-1 text-[11px] font-bold text-white flex items-center gap-1">
                        <CheckCircle2 className="h-3 w-3" /> Photo ready
                      </div>
                    </div>

                    <div className="rounded-lg border border-line bg-paper p-2.5 text-xs space-y-1">
                      {capture.gps ? (
                        <p className="flex items-center gap-1.5 text-ok-700 font-medium">
                          <LocateFixed className="h-3.5 w-3.5" />
                          Location captured automatically · ±{Math.round(capture.gps.accuracy)} m
                        </p>
                      ) : (
                        <p className="flex items-center gap-1.5 text-ink-soft">
                          <LocateFixed className="h-3.5 w-3.5" />
                          GPS unavailable — report directed to manual triage
                        </p>
                      )}
                      <p className="flex items-center gap-1.5 text-ink-soft">
                        <Clock className="h-3.5 w-3.5" />
                        {new Date(capture.timestamp).toLocaleString()}
                      </p>
                    </div>

                    <button
                      type="button"
                      onClick={() => setCapture(null)}
                      className="text-xs text-ink-soft underline underline-offset-2 hover:text-ink"
                    >
                      Retake photo
                    </button>
                  </div>
                )}
              </div>

              <div className="pt-1 flex flex-col gap-2">
                <Btn
                  tone="ok"
                  busy={busy}
                  disabled={!capture || text.trim().length < 5}
                  onClick={submitReport}
                  className="w-full"
                >
                  <Send className="h-4 w-4" />
                  Submit Sanitation Report
                </Btn>
                {!capture && text.trim().length >= 5 && (
                  <p className="text-xs text-flag-700 flex items-center gap-1">
                    <Camera className="h-3.5 w-3.5" />
                    A photo is required before submitting.
                  </p>
                )}
              </div>

              {err && <Notice tone="flag">{err}</Notice>}

              {sent && (
                <Notice
                  tone={sent.status === "ROUTED" ? "ok" : "proc"}
                  title={
                    sent.status === "ROUTED"
                      ? `Report #${sent.id} — Routed to Field Queue`
                      : `Report #${sent.id} — Pending Manual Triage`
                  }
                >
                  {sent.status === "ROUTED" ? (
                    <span>
                      Assigned to <strong>{cleanLabel(sent.queue?.name)}</strong>{" "}
                      ({cleanLabel(sent.ward?.name)}) via GPS ward matching.
                    </span>
                  ) : (
                    <span>Directed to central municipal queue for administrative routing.</span>
                  )}
                  {sent.routing && (
                    <div className="mt-1 text-[11px] text-ink-faint">
                      Recorded in tamper-evident audit chain ({sent.chain_id}, event #{sent.routing.event_id}).
                    </div>
                  )}
                </Notice>
              )}
            </div>
          </Card>
        </div>

        {/* Reports List */}
        <div className="lg:col-span-5 space-y-6">
          <Card title="My Submitted Reports">
            {!reports.data && !reports.error && <Spinner label="Loading reports" />}
            {reports.error && <Notice tone="flag">{reports.error}</Notice>}
            {reports.data?.length === 0 && (
              <p className="py-6 text-center text-sm text-ink-soft">
                No sanitation reports submitted yet.
              </p>
            )}
            <ul className="divide-y divide-line text-sm max-h-[600px] overflow-y-auto">
              {reports.data?.map((r) => (
                <li key={r.id} className="py-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-ink text-sm">
                      #{r.id} · {ISSUE_LABEL[r.issue_type]}
                    </p>
                    <TicketBadge s={r.status} />
                  </div>
                  <p className="mt-1 text-ink-soft text-xs leading-relaxed">{r.description}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-faint">
                    <span>
                      {r.ward
                        ? `${cleanLabel(r.ward.name)} → ${cleanLabel(r.queue?.name)}`
                        : "Central Triage"}
                    </span>
                    <span>·</span>
                    <span>{fmtDate(r.created_at)}</span>
                    {r.location && (
                      <>
                        <span>·</span>
                        <span className="flex items-center gap-1">
                          <LocateFixed className="h-3 w-3" />
                          {r.location.latitude.toFixed(4)}, {r.location.longitude.toFixed(4)}
                        </span>
                      </>
                    )}
                  </div>
                  {r.resolution_note && (
                    <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-ok-50 p-2 text-xs text-ok-700 border border-ok-100">
                      <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                      <span>
                        <strong>Resolved:</strong> {r.resolution_note}
                      </span>
                    </div>
                  )}
                  {r.status === "IN_PROGRESS" && (
                    <Badge tone="track" >In progress</Badge>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </div>

      </div>
    </Shell>
  );
}
