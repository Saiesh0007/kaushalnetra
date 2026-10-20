import { useEffect, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, Pane, Tooltip } from "react-leaflet";
import { useNavigate } from "react-router-dom";
import type { FeatureCollection } from "geojson";
import "leaflet/dist/leaflet.css";
import type { Centre } from "../api";
import { BAND_TONE, toneColor } from "./Status";

/* No tile server: India's boundary (DataMeet "india-composite", CC BY 4.0) and state outlines ship with the app,
   so the map is correct for an Indian government audience and works fully offline. */
let cache: Promise<[FeatureCollection, FeatureCollection]> | null = null;
const loadGeo = () =>
  (cache ??= Promise.all([
    fetch("/geo/states.json").then((r) => r.json()),
    fetch("/geo/india.json").then((r) => r.json()),
  ]) as Promise<[FeatureCollection, FeatureCollection]>);

export function IndiaMap({ centres, height = 460 }: { centres: Centre[]; height?: number }) {
  const nav = useNavigate();
  const [geo, setGeo] = useState<[FeatureCollection, FeatureCollection] | null>(null);
  useEffect(() => {
    loadGeo().then(setGeo).catch(() => undefined);
  }, []);
  const order = { low: 0, medium: 1, high: 2 } as const;
  const sorted = [...centres].sort((a, b) => order[a.risk.band] - order[b.risk.band]); // high risk drawn on top
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();

  return (
    <MapContainer
      bounds={[[6.5, 68.0], [37.2, 97.5]]}
      zoomSnap={0.25}
      style={{ height, background: "transparent" }}
      scrollWheelZoom={false}
      attributionControl={false}
    >
      {/* outlines get their own pane below the markers: whichever loads first, the opaque states never cover the dots */}
      <Pane name="geo" style={{ zIndex: 350 }}>
        {geo && (
          <>
            <GeoJSON data={geo[0]} style={{ color: v("--border"), weight: 0.8, fillColor: v("--surface-2"), fillOpacity: 1 }} interactive={false} />
            <GeoJSON data={geo[1]} style={{ color: v("--text-muted"), weight: 1.2, fill: false }} interactive={false} />
          </>
        )}
      </Pane>
      {sorted.map((c) => (
        <CircleMarker
          key={c.code}
          center={[c.lat, c.lon]}
          radius={c.simulated ? 6 : 9}
          pathOptions={{ color: v("--surface-1"), weight: 2, fillColor: toneColor(BAND_TONE[c.risk.band]), fillOpacity: 0.95 }}
          eventHandlers={{ click: () => nav(`/centres/${c.code}`) }}
        >
          <Tooltip direction="top" offset={[0, -6]}>
            <b>{c.name}</b>
            <br />
            {c.district}, {c.state} · {c.trade}
            <br />
            Risk {c.risk.score.toFixed(0)} ({c.risk.band}) · {c.open_alerts} open alerts
            <br />
            <i>{c.simulated ? "synthetic fleet data" : "processed by the AI pipeline"}</i>
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
