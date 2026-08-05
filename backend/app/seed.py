from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, pi, sin
from random import Random

from app.domain import Pole, TopologySource, haversine_meters


@dataclass(frozen=True, slots=True)
class Transformer:
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: int
    households_served: int


@dataclass(frozen=True, slots=True)
class SeedNetwork:
    poles: tuple[Pole, ...]
    transformers: tuple[Transformer, ...]
    true_parent: dict[str, str | None]
    firmware: dict[str, str]


@dataclass(frozen=True, slots=True)
class LayoutPole:
    lat: float
    lon: float
    parent_index: int | None


def _sector_for(
    item: dict[str, object],
    root_angles: dict[str, float],
    origin: tuple[float, float],
) -> str:
    pole_id = str(item["pole_id"])
    if pole_id in root_angles:
        return pole_id
    angle = atan2(float(item["lon"]) - origin[1], float(item["lat"]) - origin[0])
    return min(
        root_angles,
        key=lambda root_id: abs((angle - root_angles[root_id] + pi) % (2 * pi) - pi),
    )


def generate_network(
    *, dt_count: int = 30, poles_per_dt: int = 72, seed: int = 20260804
) -> SeedNetwork:
    random = Random(seed)
    transformers: list[Transformer] = []
    raw_poles: list[dict[str, object]] = []
    true_parent: dict[str, str | None] = {}
    firmware: dict[str, str] = {}
    pole_number = 1

    for dt_index in range(dt_count):
        feeder_id = f"F-{dt_index // 5 + 1:02d}"
        dt_id = f"D-{dt_index + 1:04d}"
        row, column = divmod(dt_index, 6)
        dt_lat = 12.935 + row * 0.018 + random.uniform(-0.001, 0.001)
        dt_lon = 77.555 + column * 0.021 + random.uniform(-0.001, 0.001)
        transformers.append(
            Transformer(
                dt_id=dt_id,
                feeder_id=feeder_id,
                lat=dt_lat,
                lon=dt_lon,
                capacity_kva=random.choice((100, 160, 250, 315, 500)),
                households_served=random.randint(220, 430),
            )
        )

        recorded_topology = dt_index >= round(dt_count * 0.6)
        layout = _branched_layout(dt_lat, dt_lon, poles_per_dt, random)
        local_pole_ids: list[str] = []
        for layout_pole in layout:
            pole_id = f"P-{pole_number:06d}"
            parent_id = (
                local_pole_ids[layout_pole.parent_index]
                if layout_pole.parent_index is not None
                else None
            )
            has_device = random.random() >= 0.09
            device_id = f"KSPDB-{dt_id}-{pole_number:06d}" if has_device else None
            pincode = None if random.random() < 0.03 else str(560001 + (dt_index % 90))
            raw_poles.append(
                {
                    "pole_id": pole_id,
                    "lat": round(layout_pole.lat, 6),
                    "lon": round(layout_pole.lon, 6),
                    "feeder_id": feeder_id,
                    "dt_id": dt_id,
                    "pincode": pincode,
                    "device_id": device_id,
                    "recorded": recorded_topology,
                }
            )
            true_parent[pole_id] = parent_id
            if device_id:
                firmware[device_id] = "1.2.8" if random.random() < 0.08 else "1.4.2"
            local_pole_ids.append(pole_id)
            pole_number += 1

    inferred_parents = _infer_missing_parents(raw_poles, transformers)
    poles = tuple(
        Pole(
            pole_id=str(item["pole_id"]),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            feeder_id=str(item["feeder_id"]),
            dt_id=str(item["dt_id"]),
            pincode=str(item["pincode"]) if item["pincode"] else None,
            parent_pole_id=(
                true_parent[str(item["pole_id"])]
                if item["recorded"]
                else inferred_parents[str(item["pole_id"])]
            ),
            topology_source=(
                TopologySource.RECORDED if item["recorded"] else TopologySource.INFERRED
            ),
            device_id=str(item["device_id"]) if item["device_id"] else None,
        )
        for item in raw_poles
    )
    return SeedNetwork(poles, tuple(transformers), true_parent, firmware)


def _branched_layout(
    dt_lat: float,
    dt_lon: float,
    pole_count: int,
    random: Random,
) -> list[LayoutPole]:
    layout: list[LayoutPole] = []
    street_axis = random.choice((0.0, pi / 4, pi / 2, 3 * pi / 4)) + random.uniform(
        -0.1, 0.1
    )

    for circuit_index, circuit_count in enumerate(_split_count(pole_count, 2)):
        if circuit_count == 0:
            continue
        circuit_angle = street_axis + circuit_index * random.uniform(1.65, 1.95)
        trunk_count = min(circuit_count, max(1, round(circuit_count * 0.55)))
        branch_pole_count = circuit_count - trunk_count
        branch_count = min(3, max(1, branch_pole_count // 3)) if branch_pole_count else 0
        branch_sizes = _split_count(branch_pole_count, branch_count) if branch_count else []

        previous_index: int | None = None
        trunk_indices: list[int] = []
        trunk_angles: list[float] = []
        lat, lon = dt_lat, dt_lon
        direction = circuit_angle
        bend_at = max(trunk_count // 2, 2)
        for position in range(trunk_count):
            if position == bend_at:
                direction += random.uniform(-0.28, 0.28)
            spacing = random.uniform(0.0003, 0.00038)
            lat += cos(direction) * spacing
            lon += sin(direction) * spacing
            pole_index = len(layout)
            layout.append(LayoutPole(lat, lon, previous_index))
            trunk_indices.append(pole_index)
            trunk_angles.append(direction)
            previous_index = pole_index

        for branch_index, branch_size in enumerate(branch_sizes):
            anchor_position = min(
                trunk_count - 1,
                max(1 if trunk_count > 1 else 0, round((branch_index + 1) * trunk_count / 4)),
            )
            anchor_index = trunk_indices[anchor_position]
            branch_lat = layout[anchor_index].lat
            branch_lon = layout[anchor_index].lon
            side = -1 if circuit_index == 0 else 1
            branch_direction = trunk_angles[anchor_position] + side * (
                pi / 2 + random.uniform(-0.16, 0.16)
            )
            previous_index = anchor_index
            for position in range(branch_size):
                if position == max(branch_size // 2, 2):
                    branch_direction += random.uniform(-0.2, 0.2)
                spacing = random.uniform(0.00029, 0.00036)
                branch_lat += cos(branch_direction) * spacing
                branch_lon += sin(branch_direction) * spacing
                pole_index = len(layout)
                layout.append(LayoutPole(branch_lat, branch_lon, previous_index))
                previous_index = pole_index

    return layout


def _split_count(total: int, parts: int) -> list[int]:
    base, remainder = divmod(total, parts)
    return [base + (1 if index < remainder else 0) for index in range(parts)]


def _infer_missing_parents(
    raw_poles: list[dict[str, object]], transformers: list[Transformer]
) -> dict[str, str | None]:
    transformer_by_id = {transformer.dt_id: transformer for transformer in transformers}
    inferred: dict[str, str | None] = {}
    by_dt: dict[str, list[dict[str, object]]] = {}
    for pole in raw_poles:
        if not pole["recorded"]:
            by_dt.setdefault(str(pole["dt_id"]), []).append(pole)

    for dt_id, dt_poles in by_dt.items():
        transformer = transformer_by_id[dt_id]
        origin = (transformer.lat, transformer.lon)
        ordered = sorted(
            dt_poles,
            key=lambda item: haversine_meters(origin, (float(item["lat"]), float(item["lon"]))),
        )
        root_items = [
            item
            for item in ordered
            if haversine_meters(origin, (float(item["lat"]), float(item["lon"]))) <= 55
        ]
        if not root_items and ordered:
            root_items = [ordered[0]]
        root_angles = {
            str(item["pole_id"]): atan2(
                float(item["lon"]) - origin[1],
                float(item["lat"]) - origin[0],
            )
            for item in root_items
        }

        sector_by_id = {
            str(item["pole_id"]): _sector_for(item, root_angles, origin) for item in ordered
        }
        connected: list[dict[str, object]] = []
        for item in ordered:
            point = (float(item["lat"]), float(item["lon"]))
            distance_from_dt = haversine_meters(origin, point)
            item_id = str(item["pole_id"])
            if item_id in root_angles:
                inferred[str(item["pole_id"])] = None
                connected.append(item)
                continue
            candidates = [
                candidate
                for candidate in connected
                if haversine_meters(origin, (float(candidate["lat"]), float(candidate["lon"])))
                < distance_from_dt
                and sector_by_id[str(candidate["pole_id"])] == sector_by_id[item_id]
            ]
            nearest = min(
                candidates,
                key=lambda candidate: haversine_meters(
                    point, (float(candidate["lat"]), float(candidate["lon"]))
                ),
                default=None,
            )
            nearest_distance = (
                haversine_meters(point, (float(nearest["lat"]), float(nearest["lon"])))
                if nearest
                else float("inf")
            )
            inferred[str(item["pole_id"])] = (
                str(nearest["pole_id"]) if nearest and nearest_distance <= 120 else None
            )
            connected.append(item)
    return inferred
