"use client";
import { Coins } from "lucide-react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";
import { Card, Notice, Spinner } from "@/components/ui";
import { Shell } from "@/components/Shell";

interface HouseholdData {
  household: { id: number; ward: string; address: string; owner_name: string };
  civic_credits: number;
  collection_history: {
    load_id: string | null;
    status: "SEGREGATED" | "UNSEGREGATED";
    timestamp: string;
  }[];
}

export default function CivicCreditsPage() {
  const me = useLoad(() => api<HouseholdData>("/citizen/me"));
  const credits = me.data?.civic_credits ?? 0;
  const history = me.data?.collection_history ?? [];
  const segregatedCount = history.filter((c) => c.status === "SEGREGATED").length;

  return (
    <Shell
      allow={["CITIZEN"]}
      accent="ok"
      title="Civic Credits"
      subtitle="Your household civic participation balance"
    >
      {me.error && <Notice tone="flag" title="Unable to load records">{me.error}</Notice>}
      {!me.data && !me.error && <Spinner label="Loading civic credits" />}

      {me.data && (
        <div className="space-y-6">
          {/* Balance card */}
          <Card tone="ok" title="Current Balance">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-ok-600 text-white shadow-sm">
                <Coins className="h-7 w-7" />
              </div>
              <div>
                <p className="text-4xl font-bold text-ok-700 tabular-nums">{credits}</p>
                <p className="mt-0.5 text-sm text-ok-600 font-medium">Civic Credits</p>
              </div>
            </div>
          </Card>

          {/* What civic credits are */}
          <Card title="About Civic Credits">
            <div className="space-y-3 text-sm text-ink-soft leading-relaxed">
              <p>
                Civic Credits reflect your household&apos;s participation in the CivicGrid municipal
                waste management system. Your current balance is <strong className="text-ink">{credits} credits</strong>.
              </p>
              <p>
                Credits are tracked by the municipal system based on your collection participation
                record. Your household has {segregatedCount} segregated collection
                {segregatedCount === 1 ? "" : "s"} recorded.
              </p>
              <div className="rounded-lg border border-line bg-paper/60 p-3 text-xs">
                <p className="font-semibold text-ink mb-1">System Note</p>
                <p>
                  The civic credits balance displayed here is the value stored in the CivicGrid
                  system for your household. Contact your ward authority for questions about
                  balance updates or credit policies.
                </p>
              </div>
            </div>
          </Card>
        </div>
      )}
    </Shell>
  );
}
