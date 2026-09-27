"use client";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Camera,
  Clock,
  FileCheck2,
  FileWarning,
  Hash,
  LocateFixed,
  ShieldCheck,
  ShieldX,
  StickyNote,
  User as UserIcon,
} from "lucide-react";
import { api, ApiError, apiBlob, apiUpload } from "@/lib/api";
import { fmtDate } from "@/lib/hooks";
import { fmtBytes } from "@/lib/nav";
import { EVIDENCE_CATEGORIES, type EvidenceConfig, type EvidenceItem, type EvidenceSide } from "@/lib/types";
import { Badge, Btn, Field, inputCls, Notice, type Tone } from "./ui";
import { CameraCapture, type CaptureResult } from "./CameraCapture";

export const sideTone: Record<EvidenceSide, Tone> = { WORKER: "track", FACILITY: "auth", NEUTRAL: "neutral" };
const sideLabel: Record<EvidenceSide, string> = { WORKER: "Supports worker", FACILITY: "Supports facility", NEUTRAL: "Neutral" };

/** Authenticated preview: the file needs the bearer token, so fetch it as a blob and show an object URL. */
function Media({ item }: { item: EvidenceItem }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let made: string | null = null;
    let dead = false;
    if (item.content_url) {
      apiBlob(item.content_url)
        .then((b) => { if (!dead) { made = URL.createObjectURL(b); setUrl(made); } })
        .catch((e) => setErr(e instanceof ApiError ? e.message : "Could not load"));
    }
    return () => { dead = true; if (made) URL.revokeObjectURL(made); };
  }, [item.content_url]);
  if (!item.content_url) return null;
  if (err) return <div className="flex h-32 items-center justify-center rounded-md border border-flag-100 bg-flag-50 px-2 text-center text-xs text-flag-700">{err}</div>;
  if (!url) return <div className="h-32 animate-pulse rounded-md bg-paper" aria-label="Loading preview" />;
  return item.media_type?.startsWith("video/")
    // eslint-disable-next-line jsx-a11y/media-has-caption
    ? <video controls src={url} className="h-40 w-full rounded-md bg-ink object-contain" />
    // eslint-disable-next-line @next/next/no-img-element
    : <img src={url} alt={item.description || "Evidence photo"} className="h-40 w-full rounded-md border border-line bg-paper object-contain" />;
}

export function EvidenceCard({ item }: { item: EvidenceItem }) {
  const [v, setV] = useState<{ valid: boolean | null; file_matches_database?: boolean; database_matches_audit_chain?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const isFile = item.kind === "FILE_EVIDENCE";
  async function verify() {
    setBusy(true);
    try { setV(await api(`/evidence/${item.id}/verify`)); } finally { setBusy(false); }
  }
  const KindIcon = isFile ? FileCheck2 : item.kind === "NOTE" ? StickyNote : ShieldCheck;
  return (
    <article className="grid gap-3 rounded-lg border border-line bg-white p-3 sm:grid-cols-[180px_1fr]" aria-label={`Evidence ${item.id}`}>
      <div>{isFile ? <Media item={item} /> : (
        <div className={`flex h-32 flex-col items-center justify-center gap-1 rounded-md border px-2 text-center text-xs ${item.kind === "NOTE" ? "border-proc-100 bg-proc-50 text-proc-700" : "border-line bg-paper text-ink-soft"}`}>
          <KindIcon className="h-6 w-6" aria-hidden />{item.kind === "NOTE" ? "Note only. Nothing was uploaded." : "Audit result record"}
        </div>)}</div>
      <div className="min-w-0 space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={isFile ? "ok" : item.kind === "NOTE" ? "proc" : "auth"}><KindIcon className="h-3 w-3" aria-hidden />{item.kind === "NOTE" ? "NOTE — NOT EVIDENCE" : item.kind.replace("_", " ")}</Badge>
          <Badge tone={sideTone[item.side]}>{sideLabel[item.side]}</Badge>
          {item.category && <Badge>{item.category.replaceAll("_", " ").toLowerCase()}</Badge>}
          {item.independence.independent
            ? <Badge tone="ok"><ShieldCheck className="h-3 w-3" aria-hidden />Independent</Badge>
            : <Badge tone="flag"><ShieldX className="h-3 w-3" aria-hidden />Not independent</Badge>}
        </div>
        {item.description && <p>{item.description}</p>}
        {!item.independence.independent && <ul className="list-disc space-y-0.5 pl-5 text-xs text-flag-700">{item.independence.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {item.duplicate_of && <p className="flex items-center gap-1 text-xs text-proc-700"><AlertTriangle className="h-3 w-3" aria-hidden />Same file content as <span className="font-mono">{item.duplicate_of}</span></p>}
        <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
          <div className="flex items-center gap-1.5"><UserIcon className="h-3 w-3 text-ink-faint" aria-hidden /><dt className="sr-only">Uploaded by</dt><dd>{item.uploader.name ?? item.uploader.actor} <span className="text-ink-faint">({item.uploader.role?.toLowerCase().replace("_", " ") ?? "unknown"})</span></dd></div>
          <div className="flex items-center gap-1.5"><Clock className="h-3 w-3 text-ink-faint" aria-hidden /><dt className="sr-only">Uploaded</dt><dd>{fmtDate(item.created_at)}</dd></div>
          {isFile && <div className="sm:col-span-2 flex items-center gap-1.5"><Hash className="h-3 w-3 shrink-0 text-ink-faint" aria-hidden /><dt className="sr-only">SHA-256</dt><dd className="min-w-0 truncate font-mono" title={item.sha256 ?? ""}>SHA-256 {item.sha256}</dd></div>}
          {isFile && <div className="text-ink-soft">{item.filename} · {item.media_type} · {fmtBytes(item.size_bytes)}</div>}
          {item.audit_event_id && <div className="text-ink-soft">Hash written to audit event #{item.audit_event_id}</div>}
        </dl>
        {item.gps && (
          <p className="flex items-start gap-1.5 rounded-md border border-proc-100 bg-proc-50 px-2 py-1 text-xs text-proc-700">
            <LocateFixed className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
            <span><span className="font-mono">{item.gps.latitude.toFixed(5)}, {item.gps.longitude.toFixed(5)}</span>{item.gps.accuracy_m != null ? ` ±${Math.round(item.gps.accuracy_m)} m` : ""} · {item.gps.label}</span>
          </p>
        )}
        {isFile && (
          <div className="flex flex-wrap items-center gap-2">
            <Btn tone="neutral" variant="outline" busy={busy} onClick={verify} className="!px-2.5 !py-1 text-xs"><ShieldCheck className="h-3.5 w-3.5" aria-hidden />Verify file integrity</Btn>
            {v && (v.valid
              ? <span className="text-xs font-medium text-ok-700">File, database and audit chain all agree.</span>
              : <span className="text-xs font-medium text-flag-700">MISMATCH: {v.file_matches_database === false ? "the stored file no longer matches its recorded hash. " : ""}{v.database_matches_audit_chain === false ? "The database hash differs from the audit chain." : ""}</span>)}
          </div>
        )}
      </div>
    </article>
  );
}

export function EvidenceList({ items, empty }: { items: EvidenceItem[]; empty?: string }) {
  if (items.length === 0) return <p className="rounded-md border border-dashed border-line p-4 text-center text-sm text-ink-soft">{empty ?? "No evidence yet."}</p>;
  return <div className="space-y-3">{items.map((i) => <EvidenceCard key={i.id} item={i} />)}</div>;
}

/**
 * EvidenceUploadForm — camera-only evidence capture form.
 *
 * There is NO file input. Evidence must be captured via the device camera.
 * The server validates the file content; this form sends the captured JPEG bytes.
 */
export function EvidenceUploadForm({
  path, onDone, config, fixedSide, defaultCategory = "LOAD_PHOTO", label = "Submit Evidence",
  onCaptureChange,
}: {
  path: string;
  onDone: (e: EvidenceItem) => void;
  config: EvidenceConfig | null;
  fixedSide?: EvidenceSide;
  defaultCategory?: (typeof EVIDENCE_CATEGORIES)[number];
  label?: string;
  onCaptureChange?: (capture: CaptureResult | null, meta?: { category: string; side: string; description: string }) => void;
}) {
  const [capture, setCapture] = useState<CaptureResult | null>(null);
  const [desc, setDesc] = useState("");
  const [cat, setCat] = useState<string>(defaultCategory);
  const [side, setSide] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function updateCapture(c: CaptureResult | null, currentDesc = desc, currentCat = cat, currentSide = side) {
    setCapture(c);
    onCaptureChange?.(c, { category: currentCat, side: fixedSide || currentSide, description: currentDesc });
  }

  async function submit() {
    if (!capture) return;
    setBusy(true);
    setErr(null);
    const f = new FormData();
    f.append("file", capture.file);
    f.append("description", desc);
    f.append("category", cat);
    if (fixedSide) {
      f.append("side", fixedSide);
    } else if (side) {
      f.append("side", side);
    }
    if (capture.gps) {
      f.append("latitude", String(capture.gps.lat));
      f.append("longitude", String(capture.gps.lng));
      f.append("accuracy_m", String(Math.round(capture.gps.accuracy)));
    }
    try {
      const e = await apiUpload<EvidenceItem>(path, f);
      updateCapture(null, "", defaultCategory, "");
      setDesc("");
      onDone(e);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Evidence submission failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-line bg-paper p-3">
      {/* Camera capture — the ONLY method */}
      <div>
        <p className="mb-1.5 text-xs font-medium text-ink">
          Photo Evidence <span className="text-flag-600">*</span>
        </p>
        {config && (
          <p className="mb-2 text-[11px] text-ink-soft">
            Capture using device camera. Server validates file content.
            Max image: {fmtBytes(config.max_image_bytes)}.
          </p>
        )}
        {!capture ? (
          <CameraCapture
            label="Open Camera to Capture Evidence"
            onCapture={(c) => updateCapture(c)}
            withGps={true}
          />
        ) : (
          <div className="space-y-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={capture.dataUrl}
              alt="Captured evidence"
              className="w-full max-h-48 rounded-lg object-cover border border-line"
            />
            <div className="flex flex-wrap items-center gap-3 text-xs">
              {capture.gps ? (
                <span className="flex items-center gap-1 text-ok-700">
                  <LocateFixed className="h-3.5 w-3.5" />
                  GPS captured · ±{Math.round(capture.gps.accuracy)} m
                </span>
              ) : (
                <span className="flex items-center gap-1 text-ink-soft">
                  <LocateFixed className="h-3.5 w-3.5" />
                  No GPS
                </span>
              )}
              <button
                type="button"
                onClick={() => updateCapture(null)}
                className="text-ink-soft underline underline-offset-2"
              >
                Retake
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Type">
          <select
            className={inputCls}
            value={cat}
            onChange={(e) => {
              const val = e.target.value;
              setCat(val);
              updateCapture(capture, desc, val, side);
            }}
          >
            {EVIDENCE_CATEGORIES.map((c) => (
              <option key={c} value={c}>{c.replaceAll("_", " ").toLowerCase()}</option>
            ))}
          </select>
        </Field>

        {!fixedSide && (
          <Field label="Which signal does it support?" hint="Your classification. Not a finding of fault.">
            <select
              className={inputCls}
              value={side}
              onChange={(e) => {
                const val = e.target.value;
                setSide(val);
                updateCapture(capture, desc, cat, val);
              }}
            >
              <option value="">Automatic (server decides)</option>
              <option value="WORKER">Worker&apos;s declaration</option>
              <option value="FACILITY">Facility&apos;s record</option>
              <option value="NEUTRAL">Neutral</option>
            </select>
          </Field>
        )}

        {fixedSide && (
          <div className="flex items-end">
            <Badge tone={sideTone[fixedSide]}>{sideLabel[fixedSide]} (fixed for your role)</Badge>
          </div>
        )}
      </div>

      <Field label="What does it show?">
        <input
          className={inputCls}
          value={desc}
          onChange={(e) => {
            const val = e.target.value;
            setDesc(val);
            updateCapture(capture, val, cat, side);
          }}
          placeholder="e.g. Weighbridge display reading 390 kg"
        />
      </Field>

      <Btn
        tone="ok"
        busy={busy}
        disabled={!capture || desc.trim().length < 3}
        onClick={submit}
      >
        <Camera className="h-4 w-4" aria-hidden />
        {label}
      </Btn>

      {err && <Notice tone="flag" title="Submission refused">{err}</Notice>}
    </div>
  );
}

export const EvidenceModeBadge = ({ mode }: { mode: "FILE_BACKED" | "LEGACY_NOTE_ONLY" | "NONE" }) =>
  mode === "FILE_BACKED"
    ? <Badge tone="ok"><Camera className="h-3 w-3" aria-hidden />EVIDENCE-BACKED (camera capture)</Badge>
    : mode === "LEGACY_NOTE_ONLY"
      ? <Badge tone="proc"><FileWarning className="h-3 w-3" aria-hidden />LEGACY NOTE — NOT EVIDENCE-BACKED</Badge>
      : <Badge>No evidence yet</Badge>;
