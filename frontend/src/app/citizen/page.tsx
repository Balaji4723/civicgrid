"use client";
import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Coins,
  FileText,
  Home,
  MapPin,
  Truck,
} from "lucide-react";
import { api } from "@/lib/api";
import { fmtDate, useLoad } from "@/lib/hooks";
import { Badge, Card, Notice, Spinner } from "@/components/ui";
import { Shell } from "@/components/Shell";
import { cleanLabel } from "@/lib/nav";

interface HouseholdData {
  household: { id: number; ward: string; address: string; owner_name: string };
  civic_credits: number;
  collection_history: {
    load_id: string | null;
    status: "SEGREGATED" | "UNSEGREGATED";
    timestamp: string;
  }[];
}

export default function CitizenHome() {
  const me = useLoad(() => api<HouseholdData>("/citizen/me"));
  const household = me.data?.household;
  const history = me.data?.collection_history ?? [];
  const latestCollection = history[0];
  const recentHistory = history.slice(0, 5);

  return (
    <Shell
      allow={["CITIZEN"]}
      accent="ok"
      title="My Household"
      subtitle={
        household
          ? `${household.address} · ${cleanLabel(household.ward)}`
          : "Household Portal"
      }
    >
      {me.error && <Notice tone="flag" title="Unable to load records">{me.error}</Notice>}
      {!me.data && !me.error && <Spinner label="Loading household profile" />}

      {me.data && household && (
        <div className="space-y-6">

          {/* Household Identity */}
          <Card tone="ok" title="Household Information">
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div className="rounded-lg bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Household ID</dt>
                <dd className="font-mono font-bold text-ink mt-0.5">HH-{household.id}</dd>
              </div>
              <div className="rounded-lg bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Assigned Ward</dt>
                <dd className="font-semibold text-ink mt-0.5">{cleanLabel(household.ward)}</dd>
              </div>
              <div className="col-span-2 rounded-lg bg-paper/60 p-3 border border-line/60">
                <dt className="text-xs text-ink-soft">Resident / Owner</dt>
                <dd className="font-medium text-ink mt-0.5">{household.owner_name}</dd>
              </div>
            </dl>

            {/* Latest collection status bar */}
            <div className="mt-4 flex items-center justify-between rounded-lg border border-line bg-paper/40 px-4 py-3">
              <div className="flex items-center gap-2 text-sm">
                <Truck className="h-4 w-4 text-ok-600 shrink-0" />
                <span className="font-medium text-ink">Latest Collection</span>
                {latestCollection && (
                  <span className="text-xs text-ink-faint">{fmtDate(latestCollection.timestamp)}</span>
                )}
              </div>
              {latestCollection ? (
                <Badge tone={latestCollection.status === "SEGREGATED" ? "ok" : "flag"}>
                  {latestCollection.status === "SEGREGATED" ? "Segregated" : "Unsegregated"}
                </Badge>
              ) : (
                <span className="text-xs text-ink-soft">No collections yet</span>
              )}
            </div>
          </Card>

          {/* Quick Actions */}
          <div className="grid gap-3 sm:grid-cols-3">
            <Link
              href="/citizen/sanitation"
              className="group flex items-center gap-3 rounded-xl border-2 border-ok-200 bg-ok-50 p-4 transition-all hover:border-ok-400 hover:bg-ok-100"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ok-600 text-white shadow-sm group-hover:bg-ok-700 transition-colors">
                <MapPin className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-ok-800 text-sm">Report Issue</p>
                <p className="text-xs text-ok-600 mt-0.5">Camera · GPS · Submit</p>
              </div>
              <ArrowRight className="ml-auto h-4 w-4 text-ok-500 shrink-0 group-hover:translate-x-0.5 transition-transform" />
            </Link>

            <Link
              href="/citizen/collections"
              className="group flex items-center gap-3 rounded-xl border border-line bg-white p-4 transition-all hover:border-track-300 hover:bg-track-50"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-track-100 text-track-700 group-hover:bg-track-200 transition-colors">
                <FileText className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-ink text-sm">Collection History</p>
                <p className="text-xs text-ink-soft mt-0.5">{history.length} records</p>
              </div>
              <ArrowRight className="ml-auto h-4 w-4 text-ink-faint shrink-0 group-hover:translate-x-0.5 transition-transform" />
            </Link>

            <Link
              href="/citizen/credits"
              className="group flex items-center gap-3 rounded-xl border border-line bg-white p-4 transition-all hover:border-ok-300 hover:bg-ok-50"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ok-100 text-ok-700 group-hover:bg-ok-200 transition-colors">
                <Coins className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-ink text-sm">Civic Credits</p>
                <p className="text-xs text-ink-soft mt-0.5">{me.data.civic_credits} balance</p>
              </div>
              <ArrowRight className="ml-auto h-4 w-4 text-ink-faint shrink-0 group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </div>

          {/* Recent collection activity */}
          <Card
            title="Recent Activity"
            right={
              <Link
                href="/citizen/collections"
                className="text-xs font-semibold text-track-700 hover:underline"
              >
                Full History →
              </Link>
            }
          >
            {recentHistory.length === 0 ? (
              <p className="py-4 text-center text-sm text-ink-soft">
                No collection events recorded yet. Your ward collection history will appear here.
              </p>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {recentHistory.map((c, i) => (
                  <li key={i} className="flex items-center justify-between py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${c.status === "SEGREGATED" ? "bg-ok-100 text-ok-600" : "bg-flag-100 text-flag-600"}`}>
                        {c.status === "SEGREGATED"
                          ? <CheckCircle2 className="h-3.5 w-3.5" />
                          : <Clock className="h-3.5 w-3.5" />
                        }
                      </div>
                      <div className="min-w-0">
                        <p className="font-mono text-xs font-semibold text-ink truncate">
                          {c.load_id ?? "Direct Collection"}
                        </p>
                        <p className="text-[11px] text-ink-faint">{fmtDate(c.timestamp)}</p>
                      </div>
                    </div>
                    <Badge tone={c.status === "SEGREGATED" ? "ok" : "flag"}>
                      {c.status === "SEGREGATED" ? "Segregated" : "Unsegregated"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Waste Segregation Assistant: "What Goes Where?" */}
          <SegregationAssistant />

          {/* Sanitation report shortcut info box */}
          <div className="rounded-xl border border-ok-200 bg-ok-50 px-4 py-3.5 flex items-start gap-3">
            <Home className="h-5 w-5 text-ok-600 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-semibold text-ok-800">See something that needs attention in your neighborhood?</p>
              <p className="mt-0.5 text-xs text-ok-700">
                Use{" "}
                <Link href="/citizen/sanitation" className="underline font-semibold">
                  Sanitation Reports
                </Link>{" "}
                to capture an issue with your device camera. Your GPS location is recorded automatically and routed to the correct ward authority.
              </p>
            </div>
          </div>

        </div>
      )}
    </Shell>
  );
}

const SEGREGATION_DATABASE: Record<string, { category: "WET" | "DRY" | "SANITARY" | "E_WASTE" | "SPECIAL"; label: string; stream: string; tip: string }> = {
  "banana peel": { category: "WET", label: "Wet / Organic Waste", stream: "Green Bin", tip: "Biodegradable. Composted at city composting facilities." },
  "food waste": { category: "WET", label: "Wet / Organic Waste", stream: "Green Bin", tip: "Drain excess liquid before placing in the green bin." },
  "fruit peels": { category: "WET", label: "Wet / Organic Waste", stream: "Green Bin", tip: "Compostable organic matter." },
  "vegetable scraps": { category: "WET", label: "Wet / Organic Waste", stream: "Green Bin", tip: "100% compostable organic waste." },
  "tea leaves": { category: "WET", label: "Wet / Organic Waste", stream: "Green Bin", tip: "Remove staple pins from tea bags before discarding." },
  "egg shells": { category: "WET", label: "Wet / Organic Waste", stream: "Green Bin", tip: "Crush lightly and place with kitchen wet waste." },
  "milk packet": { category: "DRY", label: "Dry / Recyclable Waste", stream: "Blue Bin", tip: "Rinse with water and dry flat before placing in dry bin." },
  "plastic bottle": { category: "DRY", label: "Dry / Recyclable Waste", stream: "Blue Bin", tip: "Crush the bottle and keep the cap on for recycling." },
  "cardboard": { category: "DRY", label: "Dry / Recyclable Waste", stream: "Blue Bin", tip: "Flatten boxes to conserve space." },
  "newspaper": { category: "DRY", label: "Dry / Recyclable Waste", stream: "Blue Bin", tip: "Keep clean and dry for paper recycling." },
  "pizza box": { category: "DRY", label: "Dry Waste / Special", stream: "Blue Bin (clean parts only)", tip: "If heavily oil-soaked, tear oily section into wet waste, clean lid into dry waste." },
  "shampoo bottle": { category: "DRY", label: "Dry / Recyclable Waste", stream: "Blue Bin", tip: "Rinse thoroughly to prevent stream contamination." },
  "sanitary pad": { category: "SANITARY", label: "Sanitary Waste", stream: "Separate Wrap / Red Dot", tip: "Wrap securely in newspaper/paper bag marked with a red dot." },
  "diaper": { category: "SANITARY", label: "Sanitary Waste", stream: "Separate Wrap / Red Dot", tip: "Roll, seal, and wrap in paper marked with a red dot." },
  "batteries": { category: "E_WASTE", label: "E-Waste / Hazardous", stream: "Special E-Waste Bin", tip: "Contains heavy metals. Deposit at ward e-waste drop-off box." },
  "mobile phone": { category: "E_WASTE", label: "E-Waste", stream: "Special E-Waste Collection", tip: "Take to municipal electronics collection center." },
  "broken glass": { category: "SPECIAL", label: "Domestic Hazardous / Sharp", stream: "Wrapped Newspaper", tip: "Wrap thickly in cardboard/newspaper and label 'GLASS' to protect collection workers." },
  "light bulb": { category: "SPECIAL", label: "Domestic Hazardous", stream: "Special Handling", tip: "Contains mercury or glass. Wrap safely for hazardous collection." },
};

function SegregationAssistant() {
  const [query, setQuery] = useState("");
  const [selectedResult, setSelectedResult] = useState<{
    query: string;
    category: "WET" | "DRY" | "SANITARY" | "E_WASTE" | "SPECIAL";
    label: string;
    stream: string;
    tip: string;
  } | null>(null);

  const quickPrompts = [
    { label: "Banana Peel / Food Scraps", key: "banana peel" },
    { label: "Plastic Milk Packet", key: "milk packet" },
    { label: "Cardboard Box", key: "cardboard" },
    { label: "Sanitary Napkin / Diaper", key: "sanitary pad" },
    { label: "Batteries / E-Waste", key: "batteries" },
    { label: "Broken Glass", key: "broken glass" },
  ];

  function handleLookup(item: string) {
    const clean = item.toLowerCase().trim();
    setQuery(item);
    
    // Direct or substring match
    const matchedKey = Object.keys(SEGREGATION_DATABASE).find(
      (k) => clean.includes(k) || k.includes(clean)
    );

    if (matchedKey) {
      setSelectedResult({ query: item, ...SEGREGATION_DATABASE[matchedKey] });
    } else if (clean.includes("food") || clean.includes("fruit") || clean.includes("veg") || clean.includes("meat") || clean.includes("rice") || clean.includes("bread") || clean.includes("roti")) {
      setSelectedResult({
        query: item,
        category: "WET",
        label: "Wet / Organic Waste",
        stream: "Green Bin",
        tip: "Kitchen & food waste is biodegradable and turned into organic compost.",
      });
    } else if (clean.includes("plastic") || clean.includes("paper") || clean.includes("can") || clean.includes("metal") || clean.includes("bottle") || clean.includes("packet") || clean.includes("box")) {
      setSelectedResult({
        query: item,
        category: "DRY",
        label: "Dry / Recyclable Waste",
        stream: "Blue Bin",
        tip: "Ensure item is clean and dry before placing in the blue recyclable bin.",
      });
    } else if (clean.includes("pad") || clean.includes("diaper") || clean.includes("tissue") || clean.includes("bandage") || clean.includes("mask") || clean.includes("syringe")) {
      setSelectedResult({
        query: item,
        category: "SANITARY",
        label: "Sanitary / Biomedical Waste",
        stream: "Red Dot Paper Wrap",
        tip: "Wrap securely in paper and mark with a red dot for safe incineration.",
      });
    } else if (clean.includes("phone") || clean.includes("wire") || clean.includes("cable") || clean.includes("charger") || clean.includes("battery") || clean.includes("laptop")) {
      setSelectedResult({
        query: item,
        category: "E_WASTE",
        label: "E-Waste",
        stream: "E-Waste Collection Point",
        tip: "Electronic waste is handled through specialized recovery drives.",
      });
    } else {
      setSelectedResult({
        query: item,
        category: "DRY",
        label: "Check Material / Dry Stream",
        stream: "Dry Bin (if clean)",
        tip: "If recyclable and non-organic, place in the dry bin. If organic/food, place in the green wet bin.",
      });
    }
  }

  const categoryTones = {
    WET: { bg: "bg-ok-50 border-ok-300 text-ok-900", badge: "ok" as const, icon: "🟢" },
    DRY: { bg: "bg-track-50 border-track-300 text-track-900", badge: "track" as const, icon: "🔵" },
    SANITARY: { bg: "bg-flag-50 border-flag-300 text-flag-900", badge: "flag" as const, icon: "🔴" },
    E_WASTE: { bg: "bg-proc-50 border-proc-300 text-proc-900", badge: "proc" as const, icon: "🟣" },
    SPECIAL: { bg: "bg-amber-50 border-amber-300 text-amber-900", badge: "neutral" as const, icon: "⚠️" },
  };

  return (
    <Card
      title="♻️ What Goes Where? — Waste Segregation Assistant"
      right={<span className="text-xs text-ink-soft">Source Segregation Guide</span>}
    >
      <p className="text-xs text-ink-soft mb-3">
        Type any household item or choose a quick prompt below to learn which bin it belongs to and proper handling instructions.
      </p>

      {/* Quick Prompts */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {quickPrompts.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => handleLookup(p.key)}
            className="rounded-full border border-line bg-paper/60 px-3 py-1 text-xs font-medium text-ink hover:border-ok-400 hover:bg-ok-50 hover:text-ok-800 transition-colors"
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Interactive Input */}
      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && query) handleLookup(query);
          }}
          placeholder="e.g. banana peel, milk packet, medicine bottle, batteries..."
          className="flex-1 rounded-xl border border-line bg-white px-3.5 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-ok-500 focus:outline-hidden focus:ring-2 focus:ring-ok-100"
        />
        <button
          type="button"
          onClick={() => {
            if (query) handleLookup(query);
          }}
          className="rounded-xl bg-ok-600 px-4 py-2 text-sm font-semibold text-white shadow-xs hover:bg-ok-700 transition-colors"
        >
          Check Bin
        </button>
      </div>

      {/* Result Display */}
      {selectedResult && (
        <div className={`rounded-xl border p-4 transition-all ${categoryTones[selectedResult.category].bg}`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base">{categoryTones[selectedResult.category].icon}</span>
                <span className="font-bold text-sm capitalize">{selectedResult.query}</span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-white/80 border border-current">
                  {selectedResult.stream}
                </span>
              </div>
              <p className="font-semibold text-xs mt-1.5 opacity-90">{selectedResult.label}</p>
              <p className="text-xs mt-1 leading-relaxed opacity-80">{selectedResult.tip}</p>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
