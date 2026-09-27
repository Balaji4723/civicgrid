"use client";
import { CheckCircle2, Clock, FileText } from "lucide-react";
import { api } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import { Badge, Card, Notice, Spinner } from "@/components/ui";
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

export default function CollectionHistoryPage() {
  const me = useLoad(() => api<HouseholdData>("/citizen/me"));
  const history = me.data?.collection_history ?? [];

  const segregatedCount = history.filter((c) => c.status === "SEGREGATED").length;
  const unsegregatedCount = history.filter((c) => c.status === "UNSEGREGATED").length;

  return (
    <Shell
      allow={["CITIZEN"]}
      accent="ok"
      title="Collection History"
      subtitle="Waste collection records for your household"
    >
      {me.error && <Notice tone="flag" title="Unable to load records">{me.error}</Notice>}
      {!me.data && !me.error && <Spinner label="Loading collection history" />}

      {me.data && (
        <div className="space-y-6">
          {/* Summary stats */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-line bg-white px-4 py-3.5 shadow-sm">
              <p className="text-xs font-medium text-ink-soft">Total Collections</p>
              <p className="mt-1 text-2xl font-bold text-ink">{history.length}</p>
            </div>
            <div className="rounded-xl border border-ok-100 bg-ok-50 px-4 py-3.5">
              <p className="text-xs font-medium text-ok-600">Segregated</p>
              <p className="mt-1 text-2xl font-bold text-ok-700">{segregatedCount}</p>
            </div>
            <div className="rounded-xl border border-flag-100 bg-flag-50 px-4 py-3.5">
              <p className="text-xs font-medium text-flag-600">Unsegregated</p>
              <p className="mt-1 text-2xl font-bold text-flag-700">{unsegregatedCount}</p>
            </div>
          </div>

          <Card
            title="All Collection Records"
            right={
              <span className="flex items-center gap-1.5 text-xs text-ink-soft">
                <FileText className="h-3.5 w-3.5" />
                {history.length} records
              </span>
            }
          >
            {history.length === 0 ? (
              <div className="py-10 text-center">
                <FileText className="mx-auto h-8 w-8 text-ink-faint mb-3" />
                <p className="text-sm font-medium text-ink">No collection records yet</p>
                <p className="mt-1 text-xs text-ink-soft">
                  Your household collection events will appear here after each scheduled pickup.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {history.map((c, i) => (
                  <li key={i} className="flex items-center justify-between py-3.5">
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                          c.status === "SEGREGATED"
                            ? "bg-ok-100 text-ok-600"
                            : "bg-flag-100 text-flag-600"
                        }`}
                      >
                        {c.status === "SEGREGATED" ? (
                          <CheckCircle2 className="h-4 w-4" />
                        ) : (
                          <Clock className="h-4 w-4" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="font-mono text-xs font-semibold text-ink">
                          {c.load_id ?? "Direct Collection"}
                        </p>
                        {c.load_id && (
                          <p className="text-[11px] text-ink-soft mt-0.5">Digital Load ID</p>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0 ml-3">
                      <Badge tone={c.status === "SEGREGATED" ? "ok" : "flag"}>
                        {c.status === "SEGREGATED" ? "Segregated" : "Unsegregated"}
                      </Badge>
                      <span className="text-[11px] text-ink-faint">{fmtDate(c.timestamp)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="rounded-xl border border-line bg-paper/40 px-4 py-3 text-xs text-ink-soft">
            <strong className="text-ink">About this data:</strong> Collection records are generated
            by your assigned field worker when waste is collected from your household. The Digital
            Load ID links your collection to the full municipal waste chain — from pickup through
            processing to final disposition.
          </div>
        </div>
      )}
    </Shell>
  );
}
