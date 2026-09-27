"use client";
import { Badge, Card } from "./ui";
import type { Discrepancy } from "@/lib/types";

/** Side-by-side view of the independent signals for one discrepancy. Highlights what disagrees. */
export function Signals({ d }: { d: Discrepancy }) {
  const { declaration, receiving, audit } = d.details;
  const isQty = d.type === "QUANTITY";
  const cell = (label: string, value: string, bad: boolean) => (
    <div className={`rounded-md border p-3 ${bad ? "border-flag-100 bg-flag-50" : "border-line bg-paper"}`}>
      <p className="text-xs text-ink-soft">{label}</p>
      <p className={`mt-0.5 text-lg font-semibold ${bad ? "text-flag-700" : ""}`}>{value}</p>
    </div>
  );
  const dv = isQty ? `${declaration.quantity} kg` : `${declaration.stream === "SEGREGATED" ? "Segregated" : "Mixed"} (${declaration.segregated}/${declaration.households_collected} homes)`;
  const rv = isQty ? `${receiving.quantity} kg` : receiving.condition === "UNACCEPTABLE" ? "Unacceptable" : "Acceptable";
  const av = audit ? (isQty ? `${audit.quantity} kg` : audit.condition === "UNACCEPTABLE" ? "Unacceptable" : "Acceptable") : "Not yet audited";
  return (
    <Card title="Independent signals" right={<Badge tone={isQty ? "proc" : "flag"}>{isQty ? "Quantity check" : "Stream check"}</Badge>}>
      <div className="grid gap-3 sm:grid-cols-3">
        {cell(isQty ? "1 · Worker declared quantity" : "1 · Collection-Side Stream Condition", dv, false)}
        {cell(isQty ? "2 · Facility recorded quantity" : "2 · Facility Receiving Condition", rv, true)}
        {cell(isQty ? "3 · Independent audit quantity" : "3 · Independent Audit Finding", av, !!audit)}
      </div>

      <p className="mt-3 text-sm text-ink-soft">
        {audit
          ? "Two unrelated signals now agree against the declaration, so the mismatch is corroborated."
          : "Only one signal disagrees with the declaration. It is flagged for review, and nobody is attributed fault until a second, independent signal agrees."}
      </p>
    </Card>
  );
}
