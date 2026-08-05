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
  const transformerById = new Map(
    network?.transformers.map((transformer) => [transformer.dt_id, transformer]),
  );
  const focusedPoles = selected?.dt_id
    ? network?.poles.filter((pole) => pole.dt_id === selected.dt_id) ?? []
    : [];
  const affectedPoleIds = new Set(selected?.affected_pole_ids ?? []);
  const focusedEdges = focusedPoles
    .map((pole) => {
      const upstream = pole.parent_pole_id
        ? poleById.get(pole.parent_pole_id)
        : transformerById.get(pole.dt_id);
      if (!upstream) return null;
      const positions: [[number, number], [number, number]] = [
        [upstream.lat, upstream.lon],
        [pole.lat, pole.lon],
      ];
      return {
        poleId: pole.pole_id,
        positions,
        inferred: pole.topology_source === "inferred",
      };
    })
    .filter((edge): edge is NonNullable<typeof edge> => Boolean(edge));
  const affectedDepth = new Map<string, number>();
  for (const poleId of affectedPoleIds) {
    let depth = 0;
    let current = poleById.get(poleId);
    const seen = new Set([poleId]);
    while (current?.parent_pole_id && affectedPoleIds.has(current.parent_pole_id)) {
      if (seen.has(current.parent_pole_id)) break;
      seen.add(current.parent_pole_id);
      depth += 1;
      current = poleById.get(current.parent_pole_id);
    }
    affectedDepth.set(poleId, depth);
  }
  const maxAffectedDepth = Math.max(0, ...affectedDepth.values());
  const heatIntensity = (poleId: string) => {
    const depth = affectedDepth.get(poleId) ?? maxAffectedDepth;
    return maxAffectedDepth ? 1 - 0.55 * depth / maxAffectedDepth : 1;
  };
  const heatColor = (poleId: string) => {
    const intensity = heatIntensity(poleId);
    return `hsl(${Math.round(42 * (1 - intensity))} 84% ${Math.round(48 + 5 * (1 - intensity))}%)`;
  };
  const affectedEdges = focusedEdges.filter((edge) => affectedPoleIds.has(edge.poleId));
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
        {focusedEdges.map((edge) => (
          <Polyline
            key={`edge-${edge.poleId}`}
            positions={edge.positions}
            interactive={false}
            pathOptions={edge.inferred
              ? { color: "#9a742e", weight: 1.5, opacity: 0.7, dashArray: "4 6" }
              : { color: "#405b55", weight: 1.5, opacity: 0.62 }}
          />
        ))}
        {affectedEdges.map((edge) => (
          <Polyline
            key={`impact-glow-${edge.poleId}`}
            positions={edge.positions}
            interactive={false}
            pathOptions={{ color: heatColor(edge.poleId), weight: 11, opacity: 0.18 }}
          />
        ))}
        {affectedEdges.map((edge) => (
          <Polyline
            key={`impact-core-${edge.poleId}`}
            positions={edge.positions}
            interactive={false}
            pathOptions={{ color: heatColor(edge.poleId), weight: 4, opacity: 0.9 }}
          />
        ))}
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
            radius={pole.device_id ? 3 : 2.5}
            pathOptions={pole.device_id
              ? { color: "#24755b", fillColor: "#64d49d", fillOpacity: 0.72, weight: 1 }
              : { color: "#6f7a76", fillColor: "#b9c2bf", fillOpacity: 0.72, weight: 1 }}
          >
            <Popup>
              <strong>{pole.pole_id}</strong>
              <br />{pole.device_id ? "Reporting live" : "No telemetry device"}
              <br />{pole.dt_id} · {pole.topology_source} topology
            </Popup>
          </CircleMarker>
        ))}
        {network?.poles.filter((pole) => !pole.energized).map((pole) => {
          const isFocused = pole.dt_id === selected?.dt_id;
          const isAffected = affectedPoleIds.has(pole.pole_id);
          const impact = isAffected ? heatIntensity(pole.pole_id) : 0;
          return (
            <CircleMarker
              key={pole.pole_id}
              center={[pole.lat, pole.lon]}
              radius={isFocused ? 3.5 + impact * 2 : 2.5}
              interactive={isFocused}
              pathOptions={{
                color: isAffected ? "#7c2119" : "#9e2f2f",
                fillColor: isAffected ? heatColor(pole.pole_id) : "#e5523f",
                fillOpacity: 0.92,
                weight: isFocused ? 2 : 1,
              }}
            >
              {isFocused && (
                <Popup>
                  <strong>{pole.pole_id}</strong>
                  <br />{isAffected ? "Affected outage corridor" : "Power-loss state"}
                  <br />{pole.dt_id} · {pole.topology_source} topology
                </Popup>
              )}
            </CircleMarker>
          );
        })}
        {incidents.filter((incident) => incident.status !== "closed").map((incident) => (
          <CircleMarker
            key={incident.incident_id}
            center={[incident.lat, incident.lon]}
            radius={Math.min(24, 8 + Math.sqrt(incident.affected_households) * 1.15)
              + (incident.incident_id === selected?.incident_id ? 3 : 0)}
            eventHandlers={{ click: () => onSelect(incident.incident_id) }}
            pathOptions={{
              color: incident.incident_id === selected?.incident_id ? "#17211f" : "#ffffff",
              fillColor: incident.confidence >= 0.8 ? "#d94232" : "#d89224",
              fillOpacity: 1,
              weight: 3,
            }}
          >
            <Popup>{incident.asset_id} · {incident.affected_households} homes · {incident.affected_poles} poles</Popup>
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
        {selected?.dt_id && <span><i className="legend-line recorded" />Recorded edge</span>}
        {selected?.dt_id && <span><i className="legend-line inferred" />Inferred edge</span>}
        {selected?.dt_id && <span><i className="legend-line impact" />Impact corridor</span>}
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