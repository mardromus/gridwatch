from __future__ import annotations

import json
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError


class OperatorBrief(BaseModel):
    headline: str = Field(max_length=120)
    situation: str = Field(max_length=500)
    evidence: list[str] = Field(min_length=2, max_length=6)
    recommended_action: str = Field(max_length=300)
    uncertainty: str = Field(max_length=300)
    language: str
    mode: str
    estimated_cost_usd: float = 0


class ModelBrief(BaseModel):
    headline: str = Field(max_length=120)
    situation: str = Field(max_length=500)
    evidence: list[str] = Field(min_length=2, max_length=6)
    recommended_action: str = Field(max_length=300)
    uncertainty: str = Field(max_length=300)
    language: str


async def generate_operator_brief(
    incident: dict[str, Any], language: str = "English"
) -> OperatorBrief:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return deterministic_brief(incident, language)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    facts = {
        key: incident.get(key)
        for key in (
            "incident_id",
            "kind",
            "asset_id",
            "pincode",
            "affected_poles",
            "affected_households",
            "confidence",
            "reasons",
            "status",
            "crew",
            "fingerprint",
        )
    }
    prompt = f"""You write concise utility control-room briefs in {language}.
Use only the JSON facts below. Never infer another location, fault type, crew, or restoration state.
State uncertainty plainly. Return JSON with exactly: headline, situation, evidence (array),
recommended_action, uncertainty, language. Do not use markdown.

FACTS:
{json.dumps(facts, ensure_ascii=False)}"""
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                f"{endpoint}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You summarize evidence. You do not diagnose or change facts."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = ModelBrief.model_validate_json(content)
            return OperatorBrief(
                **parsed.model_dump(),
                mode=f"llm:{model}",
                estimated_cost_usd=0.001,
            )
    except (httpx.HTTPError, KeyError, TypeError, ValidationError, json.JSONDecodeError):
        fallback = deterministic_brief(incident, language)
        fallback.mode = "deterministic_fallback_after_model_error"
        return fallback


def deterministic_brief(incident: dict[str, Any], language: str) -> OperatorBrief:
    confidence = round(float(incident.get("confidence", 0)) * 100)
    asset_id = str(incident.get("asset_id", "unknown asset"))
    status = str(incident.get("status", "detected")).replace("_", " ")
    fingerprint = incident.get("fingerprint", {})
    fit_score = round(float(fingerprint.get("fit_score", 0)) * 100)
    schedule_mismatch = fingerprint.get("schedule_context") == "mismatch"
    topology_note = next(
        (
            reason
            for reason in incident.get("reasons", [])
            if "inferred" in reason.lower() or "uninstrumented" in reason.lower()
        ),
        "No additional topology caveat was reported.",
    )
    if schedule_mismatch:
        topology_note = (
            "The planned outage scope does not match field telemetry. " + topology_note
        )
    return OperatorBrief(
        headline=f"{incident.get('kind', 'Fault').title()} fault at {asset_id}",
        situation=(
            f"Incident {incident.get('incident_id')} affects an estimated "
            f"{incident.get('affected_households', 0)} homes across "
            f"{incident.get('affected_poles', 0)} poles in PIN "
            f"{incident.get('pincode') or 'unavailable'}. "
            f"Current workflow state: {status}."
        ),
        evidence=[
            f"Deterministic localization confidence: {confidence}%",
            f"Causal telemetry fit: {fit_score}% ({fingerprint.get('verdict', 'unrated')})",
            (
                f"Loss packets: {fingerprint.get('observed_dark', 0)}; "
                f"live contradictions: {fingerprint.get('live_contradictions', 0)}"
            ),
            *[str(reason) for reason in incident.get("reasons", [])[:2]],
            *(
                ["Planned scope and observed outage signature do not align"]
                if schedule_mismatch
                else []
            ),
        ],
        recommended_action=(
            "Confirm the map boundary, acknowledge the ticket, and send the assigned crew to "
            f"{asset_id}. "
            "Do not close the ticket until restoration telemetry is recorded."
        ),
        uncertainty=topology_note,
        language=f"{language} (English fallback)",
        mode="deterministic_fallback",
    )
