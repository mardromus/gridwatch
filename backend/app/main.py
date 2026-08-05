from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.ai_brief import OperatorBrief, generate_operator_brief
from app.engine import GridService, TelemetryEvent

app = FastAPI(
    title="GridWatch API",
    description="Deterministic low-tension distribution fault localization and verification",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
service = GridService()
brief_cache: dict[tuple[object, ...], OperatorBrief] = {}


class TelemetryPayload(BaseModel):
    device_id: str
    pole_id: str
    event: Literal["heartbeat", "power_lost", "power_restored", "boot"]
    energized: bool
    ts: str
    seq: int = Field(ge=0)
    battery_mv: int = 3480
    rssi: int = -91
    fw: str = "1.4.2"


class TelemetryBatch(BaseModel):
    events: list[TelemetryPayload] = Field(min_length=1, max_length=5_000)


class SimulationRequest(BaseModel):
    kind: Literal[
        "span",
        "dt",
        "feeder",
        "sensor_failure",
        "scheduled_outage",
        "schedule_mismatch",
        "duplicate_noise",
    ]
    target_id: str | None = None


class TransitionRequest(BaseModel):
    action: Literal["acknowledge", "assign", "resolve"]
    crew: str | None = Field(default=None, max_length=80)


class BriefRequest(BaseModel):
    language: Literal["English", "Kannada", "Hindi"] = "English"


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "gridwatch",
        "seeded_poles": len(service.network.poles),
    }


@app.get("/api/dashboard")
def dashboard() -> dict[str, object]:
    return service.dashboard()


@app.get("/api/network")
def network() -> dict[str, object]:
    return service.network_map()


@app.get("/scheduled-outages")
@app.get("/api/scheduled-outages")
def scheduled_outages(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
) -> list[dict[str, object]]:
    del from_, to
    return [
        {
            "id": simulation.simulation_id,
            "scope": "dt",
            "target_id": simulation.schedule_scope_id,
            "start": simulation.started_at,
            "end": None,
            "reason": "Simulated planned maintenance",
        }
        for simulation in service.simulations.values()
        if simulation.schedule_scope_id and not simulation.repaired
    ]


@app.post("/api/telemetry")
def ingest(batch: TelemetryBatch) -> dict[str, int]:
    events = [TelemetryEvent(**payload.model_dump()) for payload in batch.events]
    return service.ingest(events)


@app.post("/api/simulator/inject")
def inject(request: SimulationRequest) -> dict[str, object]:
    try:
        return service.inject(request.kind, request.target_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/simulator/{simulation_id}/repair")
def repair(simulation_id: str) -> dict[str, object]:
    if simulation_id not in service.simulations:
        raise HTTPException(status_code=404, detail="Simulation not found")
    try:
        return service.repair(simulation_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/simulator/reset")
def reset() -> dict[str, str]:
    service.reset()
    brief_cache.clear()
    return {"status": "reset"}


@app.post("/api/incidents/{incident_id}/transition")
def transition(incident_id: str, request: TransitionRequest) -> dict[str, object]:
    if incident_id not in service.incidents:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        return service.transition(incident_id, request.action, request.crew).to_dict()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/incidents/{incident_id}/brief", response_model=OperatorBrief)
async def operator_brief(incident_id: str, request: BriefRequest) -> OperatorBrief:
    incident = service.incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident_data = incident.to_dict()
    fingerprint = incident_data.get("fingerprint", {})
    cache_key = (
        incident_id,
        incident.detected_at,
        incident.status,
        incident.localization.asset_id,
        fingerprint.get("fit_score") if isinstance(fingerprint, dict) else None,
        request.language,
    )
    cached = brief_cache.get(cache_key)
    if cached:
        return cached
    generated = await generate_operator_brief(incident_data, request.language)
    brief_cache[cache_key] = generated
    if len(brief_cache) > 200:
        brief_cache.pop(next(iter(brief_cache)))
    return generated


static_dir = Path(os.getenv("STATIC_DIR", Path(__file__).parents[2] / "frontend" / "dist"))


def frontend_file(path: str) -> Path:
    static_root = static_dir.resolve()
    candidate = (static_root / path).resolve()
    if candidate.is_relative_to(static_root) and candidate.is_file():
        return candidate
    return static_root / "index.html"


if static_dir.exists():
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        return FileResponse(frontend_file(path))
