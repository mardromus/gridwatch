from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt


class TopologySource(StrEnum):
    RECORDED = "recorded"
    INFERRED = "inferred"


class FaultKind(StrEnum):
    SPAN = "span"
    TRANSFORMER = "transformer"
    FEEDER = "feeder"


@dataclass(frozen=True, slots=True)
class Pole:
    pole_id: str
    lat: float
    lon: float
    feeder_id: str
    dt_id: str
    pincode: str | None
    parent_pole_id: str | None
    topology_source: TopologySource = TopologySource.RECORDED
    device_id: str | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    energized: bool
    observed_at: str = ""


@dataclass(frozen=True, slots=True)
class Localization:
    kind: FaultKind
    asset_id: str
    feeder_id: str
    dt_id: str | None
    upstream_pole_id: str | None
    downstream_pole_id: str | None
    candidate_path: tuple[str, ...]
    lat: float
    lon: float
    pincode: str | None
    affected_poles: int
    confidence: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocalizationResult:
    faults: tuple[Localization, ...]
    sensor_anomalies: tuple[str, ...] = field(default_factory=tuple)


class Topology:
    def __init__(self, poles: Iterable[Pole]) -> None:
        self.poles = {pole.pole_id: pole for pole in poles}
        self.children: dict[str, list[str]] = {pole_id: [] for pole_id in self.poles}
        self.by_dt: dict[str, list[str]] = {}
        self.by_feeder: dict[str, set[str]] = {}
        for pole in self.poles.values():
            if pole.parent_pole_id in self.children:
                self.children[pole.parent_pole_id].append(pole.pole_id)
            self.by_dt.setdefault(pole.dt_id, []).append(pole.pole_id)
            self.by_feeder.setdefault(pole.feeder_id, set()).add(pole.dt_id)

    def ancestors(self, pole_id: str) -> list[str]:
        result: list[str] = []
        current = self.poles[pole_id]
        seen = {pole_id}
        while current.parent_pole_id in self.poles:
            parent_id = current.parent_pole_id
            if parent_id in seen:
                raise ValueError(f"Topology cycle detected at {parent_id}")
            result.append(parent_id)
            seen.add(parent_id)
            current = self.poles[parent_id]
        return result

    def descendants(self, pole_id: str) -> set[str]:
        result: set[str] = set()
        pending = list(self.children[pole_id])
        while pending:
            child_id = pending.pop()
            if child_id in result:
                continue
            result.add(child_id)
            pending.extend(self.children[child_id])
        return result

    def localize(self, observations: dict[str, Observation]) -> LocalizationResult:
        dark = {
            pole_id
            for pole_id, observation in observations.items()
            if pole_id in self.poles and not observation.energized
        }
        live = {
            pole_id
            for pole_id, observation in observations.items()
            if pole_id in self.poles and observation.energized
        }
        first_dark_at = min((observations[pole_id].observed_at for pole_id in dark), default="")
        confirmed_live = {
            pole_id
            for pole_id in live
            if not first_dark_at or observations[pole_id].observed_at >= first_dark_at
        }

        anomalies = {
            pole_id
            for pole_id in dark
            if any(descendant in confirmed_live for descendant in self.descendants(pole_id))
        }
        credible_dark = dark - anomalies

        dt_outages = self._full_dt_outages(credible_dark, confirmed_live)
        feeder_outages = {
            feeder_id
            for feeder_id, dt_ids in self.by_feeder.items()
            if len(dt_ids) > 1 and dt_ids.issubset(dt_outages)
        }

        faults: list[Localization] = []
        consumed_dts: set[str] = set()
        for feeder_id in sorted(feeder_outages):
            dt_ids = self.by_feeder[feeder_id]
            pole_ids = [pole_id for dt_id in dt_ids for pole_id in self.by_dt[dt_id]]
            representative = self.poles[pole_ids[0]]
            faults.append(
                Localization(
                    kind=FaultKind.FEEDER,
                    asset_id=feeder_id,
                    feeder_id=feeder_id,
                    dt_id=None,
                    upstream_pole_id=None,
                    downstream_pole_id=None,
                    candidate_path=(),
                    lat=representative.lat,
                    lon=representative.lon,
                    pincode=representative.pincode,
                    affected_poles=len(pole_ids),
                    confidence=0.97,
                    reasons=(
                        f"All observed poles under {len(dt_ids)} transformers are dark",
                        "Pattern crosses transformer boundaries on one feeder",
                    ),
                )
            )
            consumed_dts.update(dt_ids)

        for dt_id in sorted(dt_outages - consumed_dts):
            pole_ids = self.by_dt[dt_id]
            representative = self.poles[pole_ids[0]]
            faults.append(
                Localization(
                    kind=FaultKind.TRANSFORMER,
                    asset_id=dt_id,
                    feeder_id=representative.feeder_id,
                    dt_id=dt_id,
                    upstream_pole_id=None,
                    downstream_pole_id=None,
                    candidate_path=(),
                    lat=representative.lat,
                    lon=representative.lon,
                    pincode=representative.pincode,
                    affected_poles=len(pole_ids),
                    confidence=0.95,
                    reasons=(
                        "All reporting branches under the transformer are dark",
                        "No live pole remains below the transformer",
                    ),
                )
            )

        remaining_dark = {
            pole_id for pole_id in credible_dark if self.poles[pole_id].dt_id not in dt_outages
        }
        frontier = [
            pole_id
            for pole_id in remaining_dark
            if not any(ancestor in remaining_dark for ancestor in self.ancestors(pole_id))
        ]
        span_faults = [
            self._span_localization(dark_pole_id, observations) for dark_pole_id in sorted(frontier)
        ]
        faults.extend(self._group_inferred_frontiers(span_faults))

        return LocalizationResult(tuple(faults), tuple(sorted(anomalies)))

    def _group_inferred_frontiers(self, span_faults: list[Localization]) -> list[Localization]:
        grouped: list[Localization] = []
        inferred_by_dt: dict[str, list[Localization]] = {}
        for fault in span_faults:
            downstream = self.poles.get(fault.downstream_pole_id or "")
            if downstream and downstream.topology_source == TopologySource.INFERRED:
                inferred_by_dt.setdefault(downstream.dt_id, []).append(fault)
            else:
                grouped.append(fault)

        for dt_id, candidates in inferred_by_dt.items():
            if len(candidates) == 1:
                grouped.append(candidates[0])
                continue
            primary = max(candidates, key=lambda candidate: candidate.affected_poles)
            affected: set[str] = set()
            for candidate in candidates:
                if candidate.downstream_pole_id:
                    affected.add(candidate.downstream_pole_id)
                    affected.update(self.descendants(candidate.downstream_pole_id))
            grouped.append(
                Localization(
                    kind=FaultKind.SPAN,
                    asset_id=f"{dt_id} inferred fault zone",
                    feeder_id=primary.feeder_id,
                    dt_id=dt_id,
                    upstream_pole_id=primary.upstream_pole_id,
                    downstream_pole_id=primary.downstream_pole_id,
                    candidate_path=tuple(
                        candidate.downstream_pole_id
                        for candidate in candidates
                        if candidate.downstream_pole_id
                    ),
                    lat=sum(candidate.lat for candidate in candidates) / len(candidates),
                    lon=sum(candidate.lon for candidate in candidates) / len(candidates),
                    pincode=primary.pincode,
                    affected_poles=len(affected),
                    confidence=min(primary.confidence, 0.5),
                    reasons=(
                        f"{len(candidates)} geometry-inferred boundaries were grouped "
                        "into one incident",
                        "Recorded pole order is unavailable; inspect the highlighted "
                        "candidate zone",
                        "Grouping prevents one physical outage from creating an alert "
                        "per dark cluster",
                    ),
                )
            )
        return grouped

    def _full_dt_outages(self, dark: set[str], live: set[str]) -> set[str]:
        outages: set[str] = set()
        for dt_id, pole_ids in self.by_dt.items():
            roots = [pole_id for pole_id in pole_ids if self.poles[pole_id].parent_pole_id is None]
            dark_branches = [
                root
                for root in roots
                if root in dark or any(descendant in dark for descendant in self.descendants(root))
            ]
            observed = [pole_id for pole_id in pole_ids if pole_id in dark or pole_id in live]
            dark_ratio = sum(pole_id in dark for pole_id in observed) / max(len(observed), 1)
            if (
                len(roots) >= 2
                and len(dark_branches) == len(roots)
                and dark_ratio >= 0.7
                and not any(pole_id in live for pole_id in pole_ids)
            ):
                outages.add(dt_id)
        return outages

    def _span_localization(
        self, dark_pole_id: str, observations: dict[str, Observation]
    ) -> Localization:
        dark_pole = self.poles[dark_pole_id]
        path = [dark_pole_id]
        upstream_id = dark_pole.parent_pole_id
        while upstream_id in self.poles and upstream_id not in observations:
            path.append(upstream_id)
            upstream_id = self.poles[upstream_id].parent_pole_id

        upstream = self.poles.get(upstream_id) if upstream_id else None
        topology_sources = {self.poles[pole_id].topology_source for pole_id in path}
        if upstream:
            topology_sources.add(upstream.topology_source)
        inferred = TopologySource.INFERRED in topology_sources
        missing_boundary_devices = len(path) > 1
        confidence = 0.68 if inferred else 0.94
        reasons = [
            f"{upstream_id or dark_pole.dt_id} is the nearest energized anchor",
            f"{dark_pole_id} and its observed downstream poles are dark",
        ]
        if inferred:
            reasons.append("Pole order is geometry-inferred, so the span may be wrong")
        if missing_boundary_devices:
            confidence -= 0.14
            reasons.append(f"{len(path) - 1} uninstrumented pole(s) widen the candidate range")

        if upstream:
            lat = (upstream.lat + dark_pole.lat) / 2
            lon = (upstream.lon + dark_pole.lon) / 2
            asset_id = f"{upstream.pole_id}--{dark_pole_id}"
            pincode = dark_pole.pincode or upstream.pincode
        else:
            lat, lon = dark_pole.lat, dark_pole.lon
            asset_id = f"{dark_pole.dt_id}--{dark_pole_id}"
            pincode = dark_pole.pincode

        return Localization(
            kind=FaultKind.SPAN,
            asset_id=asset_id,
            feeder_id=dark_pole.feeder_id,
            dt_id=dark_pole.dt_id,
            upstream_pole_id=upstream_id,
            downstream_pole_id=dark_pole_id,
            candidate_path=tuple(reversed(path)),
            lat=lat,
            lon=lon,
            pincode=pincode,
            affected_poles=1 + len(self.descendants(dark_pole_id)),
            confidence=max(round(confidence, 2), 0.1),
            reasons=tuple(reasons),
        )


def haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    earth_radius_m = 6_371_000
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(value))
