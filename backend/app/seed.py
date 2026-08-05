from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin
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
        arm_counts = _split_count(poles_per_dt, 3)
        for arm_index, arm_count in enumerate(arm_counts):
            angle = (arm_index * 2 * pi / 3) + random.uniform(-0.22, 0.22)
            previous_id: str | None = None
            for position in range(arm_count):
                pole_id = f"P-{pole_number:06d}"
                distance_degrees = 0.00042 * (position + 1)
                bend = sin(position / 5) * 0.00012
                lat = dt_lat + cos(angle) * distance_degrees + cos(angle + pi / 2) * bend
                lon = dt_lon + sin(angle) * distance_degrees + sin(angle + pi / 2) * bend
                has_device = random.random() >= 0.09
                device_id = f"KSPDB-{dt_id}-{pole_number:06d}" if has_device else None
                pincode = None if random.random() < 0.03 else str(560001 + (dt_index % 90))
                raw_poles.append(
                    {
                        "pole_id": pole_id,
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                        "feeder_id": feeder_id,
                        "dt_id": dt_id,
                        "pincode": pincode,
                        "device_id": device_id,
                        "recorded": recorded_topology,
                    }
                )
                true_parent[pole_id] = previous_id
                if device_id:
                    firmware[device_id] = "1.2.8" if random.random() < 0.08 else "1.4.2"
                previous_id = pole_id
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
        connected: list[dict[str, object]] = []
        for item in ordered:
            point = (float(item["lat"]), float(item["lon"]))
            distance_from_dt = haversine_meters(origin, point)
            candidates = [
                candidate
                for candidate in connected
                if haversine_meters(origin, (float(candidate["lat"]), float(candidate["lon"])))
                < distance_from_dt
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
