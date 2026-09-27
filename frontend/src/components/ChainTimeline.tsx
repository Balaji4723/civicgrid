"use client";
import { Check, Link2Off, Minus } from "lucide-react";
import { fmtDate, short } from "@/lib/hooks";
import type { Integrity, LogEvent } from "@/lib/types";

/** The hash chain, drawn as a chain. After "Verify Chain": green = recomputed OK, red = first broken link, grey = not reached. */
export function ChainTimeline({ events, result }: { events: LogEvent[]; result: Integrity | null }) {
  const broken = result && !result.valid ? result.broken_at_index : null;
  return (
    <ol aria-label="Hash-chained events">
      {events.map((e, i) => {
        const state: "idle" | "ok" | "broken" | "unreached" =
          !result ? "idle" : broken === null ? "ok" : i < broken ? "ok" : i === broken ? "broken" : "unreached";
        const dot = { idle: "border-track-500 bg-white text-track-600", ok: "border-ok-600 bg-ok-600 text-white", broken: "border-flag-600 bg-flag-600 text-white", unreached: "border-line bg-paper text-ink-faint" }[state];
        const line = state === "ok" ? "bg-ok-600" : state === "broken" ? "bg-flag-600" : state === "unreached" ? "bg-line" : "bg-track-100";
        return (
          <li key={e.id} className="relative flex gap-3 pb-3 last:pb-0">
            {i < events.length - 1 && <span aria-hidden className={`absolute left-[13px] top-7 h-[calc(100%-1.25rem)] w-0.5 ${line}`} />}
            <span className={`z-10 mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 ${dot}`}>
              {state === "ok" ? <Check className="h-4 w-4" aria-label="verified" /> : state === "broken" ? <Link2Off className="h-4 w-4" aria-label="broken" /> : state === "unreached" ? <Minus className="h-4 w-4" aria-label="not checked" /> : <span className="text-[10px] font-semibold">{i}</span>}
            </span>
            <div className={`min-w-0 flex-1 rounded-md border px-3 py-2 ${state === "broken" ? "border-flag-100 bg-flag-50" : "border-line bg-white"}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <p className="text-sm font-medium">{e.event_type.replaceAll("_", " ").toLowerCase()}</p>
                <p className="text-xs text-ink-soft">index {i} · event id <span className="font-mono font-semibold text-ink">{e.id}</span> · {fmtDate(e.created_at)}</p>
              </div>
              <p className="mt-1 font-mono text-xs text-ink-soft">prev {short(e.prev_hash, 10)} <span className="text-ink-faint">→</span> hash <span className={state === "broken" ? "font-semibold text-flag-700" : ""}>{short(e.hash, 10)}</span></p>
              {state === "broken" && <p className="mt-1 text-xs font-medium text-flag-700">Recomputed hash does not match: this event was altered after it was logged.</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
