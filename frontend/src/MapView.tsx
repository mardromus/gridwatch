import { useEffect, useRef } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import type { Incident, NetworkMap } from "./types";

interface MapViewProps {
  network: NetworkMap | null;
  incidents: Incident[];
  selected: Incident | null;
  onSelect: (incidentId: string) => void;
}

function FocusIncident({ incident }: { incident: Incident | null }) {
  const map = useMap();
  const focusedIncidentId = useRef<string | null>(null);
  useEffect(() => {
    if (!incident) {
      focusedIncidentId.current = null;
      return;
    }
    if (focusedIncidentId.current === incident.incident_id) return;
    focusedIncidentId.current = incident.incident_id;
    map.flyTo([incident.lat, incident.lon], 16, { duration: 0.65 });
  }, [incident, map]);
  return null;
}

export function MapView({ network, incidents, selected, onSelect }: MapViewProps) {
  const poleById = new Map(network?.poles.map((pole) => [pole.pole_id, pole]));
  const focusedPoles = selected?.dt_id
    ? network?.poles.filter((pole) => pole.dt_id === selected.dt_id) ?? []
    : [];
  const point = (poleId: string | null) => {
    const pole = poleId ? poleById.get(poleId) : null;
    return pole ? [pole.lat, pole.lon] as [number, number] : null;
  };
  const groupedInferredZone = Boolean(
    selected?.asset_id.endsWith("inferred fault zone")
      && selected.candidate_path.length > 1,
  );
  const boundaries = selected && groupedInferredZone
    ? selected.candidate_path
        .map((poleId) => {
          const candidate = poleById.get(poleId);
          return [point(candidate?.parent_pole_id ?? null), point(poleId)]
            .filter((position): position is [number, number] => Boolean(position));
        })
        .filter((positions) => positions.length > 1)
    : selected
      ? [[selected.upstream_pole_id, ...selected.candidate_path]
        .filter((poleId): poleId is string => Boolean(poleId))
        .map(point)
        .filter((position): position is [number, number] => Boolean(position))]
      : [];

  return (
    <div className="map-shell">
      <MapContainer center={[12.972, 77.61]} zoom={12} preferCanvas zoomControl>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FocusIncident incident={selected} />
        {network?.transformers.map((transformer) => (
          <CircleMarker
            key={transformer.dt_id}
            center={[transformer.lat, transformer.lon]}
            radius={4}
            pathOptions={{ color: "#0b6159", fillColor: "#f1c75b", fillOpacity: 0.9, weight: 2 }}
          >
            <Popup>
              <strong>{transformer.dt_id}</strong>
              <br />{transformer.capacity_kva} kVA · {transformer.households_served} homes
            </Popup>
          </CircleMarker>
        ))}
        {focusedPoles.filter((pole) => pole.energized).map((pole) => (
          <CircleMarker
            key={pole.pole_id}
            center={[pole.lat, pole.lon]}
            radius={2.5}
            interactive={false}
            pathOptions={pole.device_id
              ? { color: "#24755b", fillColor: "#64d49d", fillOpacity: 0.72, weight: 1 }
              : { color: "#6f7a76", fillColor: "#b9c2bf", fillOpacity: 0.72, weight: 1 }}
          />
        ))}
        {network?.poles.filter((pole) => !pole.energized).map((pole) => (
          <CircleMarker
            key={pole.pole_id}
            center={[pole.lat, pole.lon]}
            radius={3}
            pathOptions={{ color: "#9e2f2f", fillColor: "#e5523f", fillOpacity: 0.85, weight: 1 }}
          />
        ))}
        {incidents.filter((incident) => incident.status !== "closed").map((incident) => (
          <CircleMarker
            key={incident.incident_id}
            center={[incident.lat, incident.lon]}
            radius={incident.incident_id === selected?.incident_id ? 13 : 9}
            eventHandlers={{ click: () => onSelect(incident.incident_id) }}
            pathOptions={{
              color: incident.incident_id === selected?.incident_id ? "#17211f" : "#ffffff",
              fillColor: incident.confidence >= 0.8 ? "#d94232" : "#d89224",
              fillOpacity: 1,
              weight: 3,
            }}
          >
            <Popup>{incident.asset_id} · {incident.affected_poles} poles</Popup>
          </CircleMarker>
        ))}
        {boundaries.map((positions, index) => (
          <Polyline
            key={`${selected?.incident_id ?? "boundary"}-${index}`}
            positions={positions}
            pathOptions={{ color: "#d94232", weight: 6, dashArray: "8 6" }}
          />
        ))}
      </MapContainer>
      <div className="map-legend" aria-label="Map legend">
        <span><i className="legend-dot transformer" />Transformer</span>
        {selected?.dt_id && <span><i className="legend-dot live" />Live pole</span>}
        {selected?.dt_id && <span><i className="legend-dot no-device" />No device</span>}
        <span><i className="legend-dot incident" />Fault boundary</span>
        <span><i className="legend-dot dark" />Dark pole</span>
      </div>
      <div className="map-coordinate">
        {selected ? `${selected.lat.toFixed(5)}, ${selected.lon.toFixed(5)}` : "Bengaluru subdivision"}
      </div>
    </div>
  );
}