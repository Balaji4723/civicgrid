"use client";
import "leaflet/dist/leaflet.css";
import type { Map as LMap, LayerGroup } from "leaflet";
import { useEffect, useRef } from "react";
import type { FacilityCollection, Ticket, TicketStatus, WardCollection } from "@/lib/types";
import { ISSUE_LABEL } from "@/lib/types";
import { cleanLabel } from "@/lib/nav";

/**
 * Sanitation map. Deliberately draws NO base-map tiles: the ward polygons and report points come from our own API,
 * so the application works offline and never calls OpenStreetMap or any other tile server.
 */
export const STATUS_COLOR: Record<TicketStatus, string> = {
  SUBMITTED: "#7B8B80", ROUTED: "#D9700F", IN_PROGRESS: "#2563B0", RESOLVED: "#1E8449", UNROUTABLE: "#C93545",
};

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));

export function SanitationMap({ wards, tickets = [], facilities, height = 420, selectedId, onSelect, onPick, picked, label }: {
  wards: WardCollection | null; tickets?: Ticket[]; facilities?: FacilityCollection | null; height?: number;
  selectedId?: number | null; onSelect?: (id: number) => void; onPick?: (lat: number, lng: number) => void;
  picked?: { lat: number; lng: number } | null; label?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<LMap | null>(null);
  const layers = useRef<{ wards?: LayerGroup; tickets?: LayerGroup; facilities?: LayerGroup; picked?: LayerGroup }>({});
  const fitted = useRef(false);
  const cb = useRef({ onSelect, onPick });
  cb.current = { onSelect, onPick };

  // create the map once
  useEffect(() => {
    let dead = false;
    (async () => {
      const L = (await import("leaflet")).default;
      if (dead || !el.current || map.current) return;
      const m = L.map(el.current, { zoomControl: true, attributionControl: false, zoomSnap: 0.25 }).setView([19.09, 72.885], 12);
      L.control.scale({ metric: true, imperial: false }).addTo(m);
      layers.current = { wards: L.layerGroup().addTo(m), facilities: L.layerGroup().addTo(m), tickets: L.layerGroup().addTo(m), picked: L.layerGroup().addTo(m) };
      m.on("click", (e) => cb.current.onPick?.(+e.latlng.lat.toFixed(6), +e.latlng.lng.toFixed(6)));
      map.current = m;
    })();
    return () => { dead = true; map.current?.remove(); map.current = null; fitted.current = false; };
  }, []);

  // (re)draw data whenever it changes
  useEffect(() => {
    let cancelled = false;
    const draw = async () => {
      const L = (await import("leaflet")).default;
      const m = map.current;
      if (cancelled || !m || !layers.current.wards) return;
      const { wards: lw, tickets: lt, facilities: lf, picked: lp } = layers.current;
      lw!.clearLayers(); lt!.clearLayers(); lf!.clearLayers(); lp!.clearLayers();

      if (wards) {
        const g = L.geoJSON(wards as unknown as GeoJSON.FeatureCollection, {
          style: () => ({ color: "#6D3FB2", weight: 2, dashArray: "6 4", fillColor: "#6D3FB2", fillOpacity: 0.07 }),
          onEachFeature: (f, layer) => layer.bindTooltip(esc(cleanLabel(String((f.properties as { name: string }).name))), { permanent: true, direction: "center", className: "cg-ward-label", interactive: false }),
        }).addTo(lw!);
        if (!fitted.current) { m.fitBounds(g.getBounds(), { padding: [24, 24] }); fitted.current = true; }
      }

      facilities?.features.forEach((f) => {
        const [lng, lat] = f.geometry.coordinates;
        L.marker([lat, lng], { icon: L.divIcon({ className: "", iconSize: [14, 14], html: '<div style="width:14px;height:14px;background:#6D3FB2;border:2px solid #fff;border-radius:3px;box-shadow:0 0 0 1px #6D3FB2"></div>' }) })
          .bindTooltip(`${esc(f.properties.name)} · ${esc(f.properties.kind)}`).addTo(lf!);
      });
      tickets.forEach((t) => {
        if (!t.location) return;
        const sel = t.id === selectedId;
        const c = L.circleMarker([t.location.latitude, t.location.longitude], {
          radius: sel ? 11 : 8, color: sel ? "#17231C" : "#fff", weight: sel ? 3 : 2, fillColor: STATUS_COLOR[t.status], fillOpacity: 0.95,
        }).addTo(lt!);
        c.bindPopup(
          `<strong>#${t.id} · ${esc(ISSUE_LABEL[t.issue_type])}</strong><br/>${esc(t.status.replace("_", " "))}` +
          `<br/>${t.ward ? esc(t.ward.name) + " → " + esc(t.queue?.name ?? "no queue") : "No ward (manual triage)"}` +
          `<br/><span style="color:#4A5A50;font-size:11px">${esc(t.location.note)}</span>`);
        c.on("click", (e) => { L.DomEvent.stopPropagation(e); cb.current.onSelect?.(t.id); });
      });
      if (picked) {
        L.circleMarker([picked.lat, picked.lng], { radius: 9, color: "#17231C", weight: 3, fillColor: "#fff", fillOpacity: 1 }).addTo(lp!);
        L.circleMarker([picked.lat, picked.lng], { radius: 3, color: "#17231C", fillColor: "#17231C", fillOpacity: 1 }).addTo(lp!);
      }
    };
    void draw();
    const m = map.current;
    if (!m) { // map still initialising: retry once it is ready
      const t = setInterval(() => { if (map.current) { clearInterval(t); void draw(); } }, 60);
      return () => { cancelled = true; clearInterval(t); };
    }
    return () => { cancelled = true; };
  }, [wards, tickets, facilities, selectedId, picked]);

  const src = label ?? wards?.source.label;
  return (
    <div className="relative overflow-hidden rounded-lg border border-line" style={{ height }}>
      <div ref={el} className="h-full w-full" style={{ background: "#EAF0EC", cursor: onPick ? "crosshair" : undefined }}
        role="application" aria-label="Sanitation map. Ward boundaries and report locations; a table of the same reports is provided on the page." />
      {src && (
        <div className={`pointer-events-none absolute left-2 top-2 z-[1000] rounded-md border px-2 py-1 text-[11px] font-semibold ${wards?.source.all_official ? "border-ok-100 bg-ok-50 text-ok-700" : "border-proc-100 bg-proc-50 text-proc-700"}`}>
          {src}
        </div>
      )}
      <style>{`.cg-ward-label{background:transparent;border:0;box-shadow:none;color:#55308D;font-weight:600;font-size:12px}.cg-ward-label:before{display:none}`}</style>
    </div>
  );
}

export function MapLegend() {
  const items: [string, string][] = [["ROUTED", "Routed to ward queue"], ["IN_PROGRESS", "In progress"], ["RESOLVED", "Resolved"], ["UNROUTABLE", "Manual triage"]];
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft" aria-label="Map legend">
      {items.map(([k, l]) => (
        <li key={k} className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-full border border-white shadow-[0_0_0_1px_#DCE4DE]" style={{ background: STATUS_COLOR[k as TicketStatus] }} />{l}</li>
      ))}
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-3 rounded-[3px] bg-auth-600" />Facility</li>
    </ul>
  );
}
