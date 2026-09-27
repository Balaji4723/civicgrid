"use client";
import { AlertTriangle, CheckCircle2, Info, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { DiscStatus } from "@/lib/types";

export type Tone = "ok" | "track" | "auth" | "proc" | "flag" | "neutral";

const soft: Record<Tone, string> = {
  ok: "bg-ok-50 text-ok-700 border-ok-100",
  track: "bg-track-50 text-track-700 border-track-100",
  auth: "bg-auth-50 text-auth-700 border-auth-100",
  proc: "bg-proc-50 text-proc-700 border-proc-100",
  flag: "bg-flag-50 text-flag-700 border-flag-100",
  neutral: "bg-paper text-ink-soft border-line",
};
const solid: Record<Tone, string> = {
  ok: "bg-ok-600 hover:bg-ok-700 text-white shadow-sm active:bg-ok-800",
  track: "bg-track-600 hover:bg-track-700 text-white shadow-sm active:bg-track-800",
  auth: "bg-auth-600 hover:bg-auth-700 text-white shadow-sm active:bg-auth-800",
  proc: "bg-proc-600 hover:bg-proc-700 text-white shadow-sm active:bg-proc-800",
  flag: "bg-flag-600 hover:bg-flag-700 text-white shadow-sm active:bg-flag-800",
  neutral: "bg-ink hover:bg-ink-soft text-white shadow-sm active:bg-black",
};

export function Card({ title, right, children, className = "", tone }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; tone?: Tone;
}) {
  const bar = tone ? { ok: "border-t-ok-600", track: "border-t-track-600", auth: "border-t-auth-600", proc: "border-t-proc-600", flag: "border-t-flag-600", neutral: "border-t-ink" }[tone] : "";
  return (
    <section className={`rounded-xl border border-line bg-white shadow-[0_1px_3px_rgba(0,0,0,0.04)] ${tone ? `border-t-[3px] ${bar}` : ""} ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line/80 px-4 py-3 sm:px-5">
          <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${soft[tone]}`}>{children}</span>;
}

export const discTone: Record<DiscStatus, Tone> = {
  FLAGGED: "flag", EVIDENCE_PENDING: "proc", CORROBORATED: "auth", INVESTIGATING: "auth", RESOLVED: "ok", CLOSED: "ok",
};
export const StatusBadge = ({ status }: { status: DiscStatus }) => <Badge tone={discTone[status]}>{status.replace("_", " ")}</Badge>;

export const loadTone = (s: string): Tone =>
  ({ COLLECTING: "track", DECLARED: "track", VERIFIED: "ok", DISPUTED: "flag", SETTLED: "ok" } as Record<string, Tone>)[s] ?? "neutral";
export const LoadBadge = ({ status }: { status: string }) => <Badge tone={loadTone(status)}>{status}</Badge>;

export function Btn({ tone = "neutral", variant = "solid", busy, className = "", children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone; variant?: "solid" | "outline"; busy?: boolean }) {
  const base = "inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-track-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.99]";
  const look = variant === "solid" ? solid[tone] : `border bg-white ${soft[tone]} hover:brightness-95 active:bg-paper`;
  return (
    <button {...rest} disabled={rest.disabled || busy} className={`${base} ${look} ${className}`}>
      {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-soft">{hint}</span>}
    </label>
  );
}
export const inputCls = "w-full rounded-lg border border-line bg-white px-3.5 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-track-600 focus:outline-none focus:ring-1 focus:ring-track-600 transition-colors shadow-sm";

export function Notice({ tone = "track", title, children }: { tone?: Tone; title?: string; children?: ReactNode }) {
  const Icon = tone === "flag" ? AlertTriangle : tone === "ok" ? CheckCircle2 : Info;
  return (
    <div role={tone === "flag" ? "alert" : "status"} className={`flex gap-3 rounded-xl border p-3.5 text-sm ${soft[tone]}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">{title && <p className="font-semibold">{title}</p>}{children && <div className={title ? "mt-0.5" : ""}>{children}</div>}</div>
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="flex items-center gap-2 py-4 text-sm text-ink-soft"><Loader2 className="h-4 w-4 animate-spin text-track-600" aria-hidden />{label}…</div>;
}

export function Kpi({ label, value, tone = "neutral" }: { label: string; value: ReactNode; tone?: Tone }) {
  const c = { ok: "text-ok-700", track: "text-track-700", auth: "text-auth-700", proc: "text-proc-700", flag: "text-flag-700", neutral: "text-ink" }[tone];
  return (
    <div className="rounded-xl border border-line bg-white px-4 py-3.5 shadow-[0_1px_3px_rgba(0,0,0,0.03)] transition-all">
      <p className="text-xs font-medium text-ink-soft">{label}</p>
      <p className={`mt-1 text-2xl font-bold tracking-tight ${c}`}>{value}</p>
    </div>
  );
}

export function Table({ head, rows, empty = "Nothing here yet." }: { head: string[]; rows: ReactNode[][]; empty?: string }) {
  return (
    <div className="-mx-4 sm:mx-0 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line bg-paper/50 text-xs text-ink-soft">
            {head.map((h, idx) => <th key={idx} className="px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={head.length} className="px-4 py-8 text-center text-ink-soft">{empty}</td></tr>}
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60 transition-colors hover:bg-paper/40 last:border-0">
              {r.map((c, j) => <td key={j} className="px-4 py-3 align-middle">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
