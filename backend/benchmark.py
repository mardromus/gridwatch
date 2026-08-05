from __future__ import annotations

import os
import platform
from dataclasses import asdict
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from app.engine import GridService, TelemetryEvent, iso_now


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(ceil(len(ordered) * 0.95) - 1, 0)]


def burst_events(
    service: GridService, sequences: dict[str, int]
) -> list[TelemetryEvent]:
    instrumented = [pole for pole in service.network.poles if pole.device_id]
    timestamp = iso_now()
    events: list[TelemetryEvent] = []
    for index in range(5_000):
        pole = instrumented[index % len(instrumented)]
        device_id = pole.device_id or ""
        sequences[device_id] += 1
        events.append(
            TelemetryEvent(
                device_id=device_id,
                pole_id=pole.pole_id,
                event="heartbeat",
                energized=True,
                ts=timestamp,
                seq=sequences[device_id],
                fw=service.network.firmware[device_id],
            )
        )
    return events


def main() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as temporary_directory:
        os.environ["GRIDWATCH_DB_PATH"] = str(
            Path(temporary_directory) / "gridwatch-benchmark.db"
        )
        from app.main import app, service
        from fastapi.testclient import TestClient

        fault_samples: list[float] = []
        incident_list_samples: list[float] = []
        restoration_samples: list[float] = []

        with TestClient(app) as client:
            sequences = {
                pole.device_id: 100
                for pole in service.network.poles
                if pole.device_id
            }
            events = burst_events(service, sequences)
            started = perf_counter()
            ingest_response = client.post(
                "/api/telemetry", json={"events": [asdict(event) for event in events]}
            )
            ingest_seconds = perf_counter() - started
            ingest_response.raise_for_status()
            accepted = ingest_response.json()["accepted"]
            if accepted != len(events):
                raise RuntimeError(f"Expected {len(events)} accepted events, got {accepted}")
            if service.audit_store.counts()["telemetry_events"] != len(events):
                raise RuntimeError("Disk audit row count does not match accepted burst")

            sustained_messages = 0
            started = perf_counter()
            for _ in range(10):
                sustained_events = burst_events(service, sequences)
                sustained_response = client.post(
                    "/api/telemetry",
                    json={"events": [asdict(event) for event in sustained_events]},
                )
                sustained_response.raise_for_status()
                sustained_messages += sustained_response.json()["accepted"]
            sustained_seconds = perf_counter() - started
            if sustained_messages != 50_000:
                raise RuntimeError(
                    f"Expected 50000 sustained events, got {sustained_messages}"
                )

            for _ in range(30):
                client.post("/api/simulator/reset").raise_for_status()

                started = perf_counter()
                simulation_response = client.post(
                    "/api/simulator/inject", json={"kind": "span"}
                )
                simulation_response.raise_for_status()
                dashboard_response = client.get("/api/dashboard")
                dashboard_response.raise_for_status()
                fault_samples.append((perf_counter() - started) * 1_000)

                dashboard = dashboard_response.json()
                active = [
                    incident
                    for incident in dashboard["incidents"]
                    if incident["status"] != "closed"
                ]
                if len(active) != 1:
                    raise RuntimeError(f"Expected one active incident, got {len(active)}")

                incident_id = active[0]["incident_id"]
                simulation_id = simulation_response.json()["simulation_id"]
                for action, crew in (
                    ("acknowledge", None),
                    ("assign", "Benchmark crew"),
                    ("resolve", None),
                ):
                    transition = client.post(
                        f"/api/incidents/{incident_id}/transition",
                        json={"action": action, "crew": crew},
                    )
                    transition.raise_for_status()

                started = perf_counter()
                repair_response = client.post(
                    f"/api/simulator/{simulation_id}/repair"
                )
                repair_response.raise_for_status()
                verified_response = client.get("/api/dashboard")
                verified_response.raise_for_status()
                restoration_samples.append((perf_counter() - started) * 1_000)
                verified = next(
                    incident
                    for incident in verified_response.json()["incidents"]
                    if incident["incident_id"] == incident_id
                )
                if verified["status"] != "closed":
                    raise RuntimeError("Restoration telemetry did not auto-close the incident")

                started = perf_counter()
                client.get("/api/dashboard").raise_for_status()
                incident_list_samples.append((perf_counter() - started) * 1_000)

        service.audit_store.close()

    print(f"platform={platform.system()} {platform.machine()} Python {platform.python_version()}")
    print(f"disk_api_burst_messages={accepted}")
    print(f"disk_api_burst_seconds={ingest_seconds:.4f}")
    print(f"disk_api_burst_throughput={accepted / ingest_seconds:.0f} msg/s")
    print(f"disk_api_sustained_messages={sustained_messages}")
    print(f"disk_api_sustained_seconds={sustained_seconds:.4f}")
    print(
        f"disk_api_sustained_throughput={sustained_messages / sustained_seconds:.0f} msg/s"
    )
    print(f"fault_to_visible_ticket_p95={p95(fault_samples):.1f} ms")
    print(f"incident_list_api_p95={p95(incident_list_samples):.1f} ms")
    print(f"restoration_to_verified_p95={p95(restoration_samples):.1f} ms")
    print("scope=local TestClient; disk SQLite; HTTP/Pydantic included; browser render excluded")


if __name__ == "__main__":
    main()
