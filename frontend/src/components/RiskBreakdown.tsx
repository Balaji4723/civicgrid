"use client";
import type { RiskFactor } from "@/lib/types";

/** Every factor with its raw value, weight, contribution and a plain-English explanation. Nothing is hidden. */
export function RiskBreakdown({ factors, score }: { factors: RiskFactor[]; score: number | null }) {
  const sorted = [...factors].sort((a, b) => b.contribution - a.contribution);
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b border-line text-xs text-ink-soft"><th className="px-2 py-1.5 font-medium">Factor</th><th className="px-2 py-1.5 font-medium">This load</th><th className="px-2 py-1.5 font-medium">Weight</th><th className="px-2 py-1.5 font-medium">Contribution</th></tr></thead>
          <tbody>
            {sorted.map((f) => (
              <tr key={f.key} className="border-b border-line/70 align-top last:border-0">
                <td className="px-2 py-2"><p className="font-medium">{f.label}</p><p className="max-w-md text-xs text-ink-soft">{f.explanation}</p></td>
                <td className="px-2 py-2 whitespace-nowrap">{f.raw_text}<p className="text-xs text-ink-faint">scored {(f.normalised * 100).toFixed(0)}% of max (cap {f.cap})</p></td>
                <td className="px-2 py-2 whitespace-nowrap">{(f.weight_share * 100).toFixed(0)}%</td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2"><div className="h-2 w-24 rounded-full bg-line" role="presentation"><div className="h-2 rounded-full bg-proc-600" style={{ width: `${Math.min(100, (f.contribution / Math.max(score || 0.0001, 0.0001)) * 100)}%` }} /></div><span className="font-mono text-xs">+{f.contribution.toFixed(3)}</span></div>
                </td>
              </tr>))}
          </tbody>
          {score !== null && <tfoot><tr><td colSpan={3} className="px-2 py-2 text-right text-sm font-semibold">Risk score</td><td className="px-2 py-2 font-mono font-semibold">{score.toFixed(3)}</td></tr></tfoot>}
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-soft">Score = Σ weight share × min(value ÷ cap, 1). A transparent ranking with policy-set weights, not a validated statistical model.</p>
    </div>
  );
}
