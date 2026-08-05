from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from uuid import uuid4

from app.audit import AuditStore
from app.domain import FaultKind, Localization, Observation, Topology
from app.seed import SeedNetwork, generate_network


class TicketStatus(StrEnum):
    DETECTED = "detected"
    ACKNOWLEDGED = "acknowledged"
    CREW_ASSIGNED = "crew_assigned"
    RESOLVED = "resolved"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    device_id: str
    pole_id: str
    event: str
    energized: bool
    ts: str
    seq: int
    battery_mv: int = 3480
    rssi: int = -91
    fw: str = "1.4.2"


@dataclass(slots=True)
class TimelineEntry:
    at: str
    event: str
    detail: str


@dataclass(frozen=True, slots=True)
class CausalFingerprint:
    predicted_reporting: int
    observed_dark: int
    silent_or_unknown: int
    live_contradictions: int
    unexplained_dark: int
    expected_loss_reports: int
    fit_score: float
    verdict: str
    schedule_context: str
    schedule_coverage: float | None = None


@dataclass(slots=True)
class Incident:
    incident_id: str
    localization: Localization
    status: TicketStatus
    detected_at: str
    affected_pole_ids: set[str]
    confirmed_dark_pole_ids: set[str]
    affected_households: int
    fingerprint: CausalFingerprint
    timeline: list[TimelineEntry]
    crew: str | None = None
    resolved_at: str | None = None
    verification_ratio: float = 0.0

    def to_dict(self) -> dict[str, object]:
        result = asdict(self.localization)
        result.update(
            {
                "incident_id": self.incident_id,
                "status": self.status,
                "detected_at": self.detected_at,
                "crew": self.crew,
                "resolved_at": self.resolved_at,
                "verification_ratio": self.verification_ratio,
                "affected_households": self.affected_households,
                "affected_pole_ids": sorted(self.affected_pole_ids),
                "confirmed_dark_pole_ids": sorted(self.confirmed_dark_pole_ids),
                "fingerprint": asdict(self.fingerprint),
                "timeline": [asdict(entry) for entry in self.timeline],
            }
        )
        return result


@dataclass(slots=True)
class SimulatedFault:
    simulation_id: str
    kind: str
    target_id: str
    affected_pole_ids: set[str]
    started_at: str
    scheduled: bool = False
    repaired: bool = False
    schedule_scope_id: str | None = None


@dataclass(slots=True)
class IngestMetrics:
    accepted: int = 0
    duplicates: int = 0
    stale: int = 0
    rejected: int = 0


class GridService:
    def __init__(
        self, network: SeedNetwork | None = None, audit_store: AuditStore | None = None
    ) -> None:
        self.network = network or generate_network()
        self.audit_store = audit_store or AuditStore(os.getenv("GRIDWATCH_DB_PATH", ":memory:"))
        self.topology = Topology(self.network.poles)
        self.observations: dict[str, Observation] = {}
        self.unrelated_offline: set[str] = set()
        self.physical_energized = {pole.pole_id: True for pole in self.network.poles}
        self.incidents: dict[str, Incident] = {}
        self.simulations: dict[str, SimulatedFault] = {}
        self.scheduled_scopes: set[tuple[str, str]] = set()
        self.metrics = IngestMetrics()
        self._seen_events: set[tuple[str, str, int, str]] = set()
        self._device_order: dict[str, tuple[int, str]] = {}
        self._device_seq: dict[str, int] = {}
        self._lock = RLock()
        self._initialize_live_state()

    def _initialize_live_state(self) -> None:
        observed_at = iso_now(datetime.now(UTC) - timedelta(minutes=2))
        previous_observed_at = iso_now(datetime.now(UTC) - timedelta(hours=1))
        for pole in self.network.poles:
            if pole.device_id:
                is_offline = int(pole.pole_id.rsplit("-", 1)[-1]) % 25 == 0
                if is_offline:
                    self.unrelated_offline.add(pole.pole_id)
                else:
                    self.observations[pole.pole_id] = Observation(True, observed_at)
                self._device_seq[pole.device_id] = 100
                self._device_order[pole.device_id] = (
                    100,
                    previous_observed_at if is_offline else observed_at,
                )

    def ingest(self, events: list[TelemetryEvent]) -> dict[str, int]:
        batch = IngestMetrics()
        audit_records: list[tuple[str, dict[str, object]]] = []
        with self._lock:
            for event in events:
                if event.pole_id not in self.topology.poles:
                    batch.rejected += 1
                    continue
                try:
                    device_time = datetime.fromisoformat(event.ts.replace("Z", "+00:00"))
                    if device_time.tzinfo is None or device_time.utcoffset() is None:
                        raise ValueError("Telemetry timestamp must include a timezone")
                    device_time = device_time.astimezone(UTC)
                except (TypeError, ValueError):
                    batch.rejected += 1
                    continue
                received_at = datetime.now(UTC)
                if device_time < received_at - timedelta(
                    minutes=10
                ) or device_time > received_at + timedelta(minutes=5):
                    batch.stale += 1
                    continue
                event_key = (event.device_id, event.event, event.seq, event.ts)
                if event_key in self._seen_events:
                    batch.duplicates += 1
                    continue
                self._seen_events.add(event_key)

                previous = self._device_order.get(event.device_id)
                if event.event == "boot":
                    if previous and event.ts < previous[1]:
                        batch.stale += 1
                        continue
                elif previous and event.seq <= previous[0]:
                    batch.stale += 1
                    continue

                self._device_order[event.device_id] = (event.seq, event.ts)
                self._device_seq[event.device_id] = event.seq
                self.unrelated_offline.discard(event.pole_id)
                self.observations[event.pole_id] = Observation(
                    event.energized, iso_now(received_at)
                )
                audit_records.append(("|".join(map(str, event_key)), asdict(event)))
                batch.accepted += 1

            self.audit_store.record_telemetry_batch(audit_records)
            self.metrics.accepted += batch.accepted
            self.metrics.duplicates += batch.duplicates
            self.metrics.stale += batch.stale
            self.metrics.rejected += batch.rejected
            if batch.accepted:
                self._reconcile()
        return asdict(batch)

    def _reconcile(self) -> None:
        reconciled_at = datetime.now(UTC)
        now = iso_now(reconciled_at)
        result = self.topology.localize(self.observations)
        for localization in result.faults:
            affected = self._localized_affected(localization)
            dark_evidence = sum(
                pole_id in self.observations
                and not self.observations[pole_id].energized
                for pole_id in affected
            )
            if dark_evidence < 2:
                continue
            schedule_context, schedule_coverage = self._schedule_assessment(localization)
            if schedule_context == "matched":
                continue
            existing = next(
                (
                    incident
                    for incident in self.incidents.values()
                    if self._correlates(
                        incident,
                        localization,
                        affected,
                        reconciled_at,
                    )
                ),
                None,
            )
            if existing:
                previous_asset = existing.localization.asset_id
                existing.localization = localization
                existing.affected_pole_ids.update(affected)
                existing.confirmed_dark_pole_ids.update(self._confirmed_dark(affected))
                existing.affected_households = self._estimate_affected_households(
                    existing.affected_pole_ids
                )
                existing.fingerprint = self._causal_fingerprint(
                    localization,
                    existing.affected_pole_ids,
                    schedule_context=schedule_context,
                    schedule_coverage=schedule_coverage,
                )
                if previous_asset != localization.asset_id:
                    existing.timeline.append(
                        TimelineEntry(
                            now,
                            "refined",
                            f"Boundary refined from {previous_asset} to "
                            f"{localization.asset_id} as telemetry arrived",
                        )
                    )
                self._persist_incident(existing)
                continue
            fingerprint = self._causal_fingerprint(
                localization,
                affected,
                schedule_context=schedule_context,
                schedule_coverage=schedule_coverage,
            )
            incident_id = f"INC-{datetime.now(UTC):%Y%m%d}-{len(self.incidents) + 1:04d}"
            detection_detail = "Telemetry correlation localized the fault"
            if schedule_context == "mismatch":
                detection_detail = (
                    "Escalated inside a planned window because field telemetry "
                    "does not match the scheduled scope"
                )
            self.incidents[incident_id] = Incident(
                incident_id=incident_id,
                localization=localization,
                status=TicketStatus.DETECTED,
                detected_at=now,
                affected_pole_ids=affected,
                confirmed_dark_pole_ids=self._confirmed_dark(affected),
                affected_households=self._estimate_affected_households(affected),
                fingerprint=fingerprint,
                timeline=[TimelineEntry(now, "detected", detection_detail)],
            )
            self._persist_incident(self.incidents[incident_id])

        for incident in self.incidents.values():
            if incident.status == TicketStatus.CLOSED:
                continue
            restored, instrumented = self._restoration_evidence(incident)
            previous_ratio = incident.verification_ratio
            incident.verification_ratio = len(restored) / max(len(instrumented), 1)
            if incident.verification_ratio >= 0.8:
                verified_at = iso_now()
                incident.resolved_at = verified_at
                incident.timeline.append(
                    TimelineEntry(
                        verified_at,
                        "verified",
                        f"{len(restored)}/{len(instrumented)} reporting poles restored",
                    )
                )
                incident.timeline.append(
                    TimelineEntry(
                        verified_at, "closed", "Closed automatically after telemetry verification"
                    )
                )
                incident.status = TicketStatus.CLOSED
                self._persist_incident(incident)
            elif incident.verification_ratio != previous_ratio:
                self._persist_incident(incident)

    def _restoration_evidence(self, incident: Incident) -> tuple[list[str], list[str]]:
        instrumented = [
            pole_id
            for pole_id in incident.confirmed_dark_pole_ids
            if self.topology.poles[pole_id].device_id
        ]
        restored = [
            pole_id
            for pole_id in instrumented
            if pole_id in self.observations
            and self.observations[pole_id].energized
            and self.observations[pole_id].observed_at >= incident.detected_at
        ]
        return restored, instrumented

    def _correlates(
        self,
        incident: Incident,
        localization: Localization,
        affected: set[str],
        reconciled_at: datetime,
    ) -> bool:
        if incident.status == TicketStatus.CLOSED:
            return False
        if incident.localization.asset_id == localization.asset_id:
            return True
        if incident.localization.feeder_id != localization.feeder_id:
            return False
        if (
            incident.localization.dt_id
            and localization.dt_id
            and incident.localization.dt_id != localization.dt_id
        ):
            return False
        if not incident.affected_pole_ids & affected:
            return False
        detected_at = datetime.fromisoformat(
            incident.detected_at.replace("Z", "+00:00")
        )
        return reconciled_at - detected_at <= timedelta(minutes=2)

    def transition(self, incident_id: str, action: str, crew: str | None = None) -> Incident:
        with self._lock:
            incident = self.incidents[incident_id]
            now = iso_now()
            if action == "acknowledge" and incident.status == TicketStatus.DETECTED:
                incident.status = TicketStatus.ACKNOWLEDGED
                incident.timeline.append(
                    TimelineEntry(now, "acknowledged", "Operator acknowledged")
                )
            elif action == "assign" and incident.status == TicketStatus.ACKNOWLEDGED:
                incident.status = TicketStatus.CREW_ASSIGNED
                incident.crew = crew or "Field crew 3"
                incident.timeline.append(TimelineEntry(now, "crew_assigned", incident.crew))
            elif action == "resolve" and incident.status == TicketStatus.CREW_ASSIGNED:
                restored, instrumented = self._restoration_evidence(incident)
                incident.verification_ratio = len(restored) / max(len(instrumented), 1)
                incident.timeline.append(
                    TimelineEntry(
                        now,
                        "resolution_rejected",
                        f"Closure rejected: {len(restored)}/{len(instrumented)} "
                        "confirmed-dark reporting poles restored",
                    )
                )
                self._persist_incident(incident)
                raise ValueError(
                    f"Cannot resolve {incident_id}: telemetry still shows "
                    f"{len(instrumented) - len(restored)}/{len(instrumented)} reporting poles dark"
                )
            else:
                raise ValueError(f"Cannot {action} incident in {incident.status} state")
            self._persist_incident(incident)
            return incident

    def inject(self, kind: str, target_id: str | None = None) -> dict[str, object]:
        with self._lock:
            if kind == "sensor_failure":
                return self._inject_sensor_failure(target_id)
            if kind == "duplicate_noise":
                return self._inject_duplicate_noise(target_id)

            scheduled = kind == "scheduled_outage"
            schedule_scope_id: str | None = None
            if kind == "schedule_mismatch":
                schedule_scope_id = target_id or self._choose_target("dt")
                physical_kind = "span"
                target_id = self._choose_span_target(schedule_scope_id)
            else:
                physical_kind = "dt" if scheduled else kind
                target_id = target_id or self._choose_target(physical_kind)
                if scheduled:
                    schedule_scope_id = target_id
            affected = self._physical_affected(physical_kind, target_id)
            if schedule_scope_id:
                self.scheduled_scopes.add(("dt", schedule_scope_id))
            for pole_id in affected:
                self.physical_energized[pole_id] = False
            events = self._loss_events(affected)
            simulation_id = f"SIM-{uuid4().hex[:8].upper()}"
            simulation = SimulatedFault(
                simulation_id,
                kind,
                target_id,
                affected,
                iso_now(),
                scheduled=scheduled,
                schedule_scope_id=schedule_scope_id,
            )
            self.simulations[simulation_id] = simulation
            result = self.ingest(events)
            return {
                "simulation_id": simulation_id,
                "kind": kind,
                "target_id": target_id,
                "affected_poles": len(affected),
                "telemetry": result,
                "suppressed": scheduled,
                "schedule_scope_id": schedule_scope_id,
            }

    def repair(self, simulation_id: str) -> dict[str, object]:
        with self._lock:
            simulation = self.simulations[simulation_id]
            for pole_id in simulation.affected_pole_ids:
                self.physical_energized[pole_id] = True
            events = self._restoration_events(simulation.affected_pole_ids)
            result = self.ingest(events)
            simulation.repaired = True
            if simulation.schedule_scope_id:
                self.scheduled_scopes.discard(("dt", simulation.schedule_scope_id))
            return {
                "simulation_id": simulation_id,
                "telemetry": result,
                "restored": len({event.pole_id for event in events}),
                "events_emitted": len(events),
            }

    def reset(self) -> None:
        with self._lock:
            self.audit_store.clear()
            self.__init__(self.network, self.audit_store)

    def dashboard(self) -> dict[str, object]:
        active = [
            incident
            for incident in self.incidents.values()
            if incident.status != TicketStatus.CLOSED
        ]
        return {
            "summary": {
                "active_incidents": len(active),
                "affected_poles": sum(item.localization.affected_poles for item in active),
                "affected_households": sum(item.affected_households for item in active),
                "network_poles": len(self.network.poles),
                "reporting_devices": len(self.observations),
                "inferred_topology_pct": round(
                    100
                    * sum(pole.topology_source == "inferred" for pole in self.network.poles)
                    / len(self.network.poles)
                ),
                "ingest": asdict(self.metrics),
                "audit": self.audit_store.counts(),
            },
            "incidents": [
                incident.to_dict()
                for incident in sorted(
                    self.incidents.values(), key=lambda item: item.detected_at, reverse=True
                )
            ],
            "simulations": [
                {
                    "simulation_id": item.simulation_id,
                    "kind": item.kind,
                    "target_id": item.target_id,
                    "affected_poles": len(item.affected_pole_ids),
                    "started_at": item.started_at,
                    "scheduled": item.scheduled,
                    "repaired": item.repaired,
                    "schedule_scope_id": item.schedule_scope_id,
                }
                for item in self.simulations.values()
            ],
        }

    def network_map(self) -> dict[str, object]:
        return {
            "transformers": [asdict(transformer) for transformer in self.network.transformers],
            "poles": [
                {
                    **asdict(pole),
                    "energized": self.physical_energized[pole.pole_id],
                }
                for pole in self.network.poles
            ],
        }

    def _persist_incident(self, incident: Incident) -> None:
        snapshot = incident.to_dict()
        snapshot["affected_pole_ids"] = sorted(incident.affected_pole_ids)
        self.audit_store.upsert_incident(snapshot)

    def _localized_affected(self, localization: Localization) -> set[str]:
        if localization.kind == FaultKind.FEEDER:
            return {
                pole.pole_id
                for pole in self.network.poles
                if pole.feeder_id == localization.feeder_id
            }
        if localization.kind == FaultKind.TRANSFORMER:
            return set(self.topology.by_dt[localization.dt_id or ""])
        if len(localization.candidate_path) > 1 and "inferred fault zone" in localization.asset_id:
            affected: set[str] = set()
            for pole_id in localization.candidate_path:
                affected.add(pole_id)
                affected.update(self.topology.descendants(pole_id))
            return affected
        downstream = localization.downstream_pole_id
        return {downstream, *self.topology.descendants(downstream)} if downstream else set()

    def _estimate_affected_households(self, affected: set[str]) -> int:
        total = 0.0
        for transformer in self.network.transformers:
            dt_poles = self.topology.by_dt[transformer.dt_id]
            affected_count = sum(pole_id in affected for pole_id in dt_poles)
            if affected_count:
                total += transformer.households_served * affected_count / len(dt_poles)
        return max(round(total), 1) if affected else 0

    def _confirmed_dark(self, affected: set[str]) -> set[str]:
        return {
            pole_id
            for pole_id in affected
            if pole_id in self.observations and not self.observations[pole_id].energized
        }

    def _schedule_assessment(self, localization: Localization) -> tuple[str, float | None]:
        scope: tuple[str, str] | None = None
        if ("feeder", localization.feeder_id) in self.scheduled_scopes:
            scope = ("feeder", localization.feeder_id)
        elif localization.dt_id and ("dt", localization.dt_id) in self.scheduled_scopes:
            scope = ("dt", localization.dt_id)
        if not scope:
            return "none", None

        scope_type, target_id = scope
        scope_poles = [
            pole
            for pole in self.network.poles
            if (scope_type == "feeder" and pole.feeder_id == target_id)
            or (scope_type == "dt" and pole.dt_id == target_id)
        ]
        expected_reporters = [
            pole
            for pole in scope_poles
            if pole.device_id
            and not self.network.firmware[pole.device_id].startswith("1.2")
        ]
        observed_dark = sum(
            pole.pole_id in self.observations
            and not self.observations[pole.pole_id].energized
            for pole in expected_reporters
        )
        expected_packets = max(round(0.7 * len(expected_reporters)), 1)
        coverage = min(observed_dark / expected_packets, 1.0)
        return ("matched" if coverage >= 0.65 else "mismatch"), round(coverage, 2)

    def _causal_fingerprint(
        self,
        localization: Localization,
        affected: set[str],
        *,
        schedule_context: str,
        schedule_coverage: float | None,
    ) -> CausalFingerprint:
        expected_reporters = {
            pole_id
            for pole_id in affected
            if self.topology.poles[pole_id].device_id
            and not self.network.firmware[
                self.topology.poles[pole_id].device_id or ""
            ].startswith("1.2")
        }
        observed_dark = {
            pole_id
            for pole_id in expected_reporters
            if pole_id in self.observations and not self.observations[pole_id].energized
        }
        first_dark_at = min(
            (self.observations[pole_id].observed_at for pole_id in observed_dark),
            default="",
        )
        live_contradictions = {
            pole_id
            for pole_id in expected_reporters
            if pole_id in self.observations
            and self.observations[pole_id].energized
            and self.observations[pole_id].observed_at >= first_dark_at
        }
        relevant_scope = (
            self.topology.by_dt.get(localization.dt_id or "", [])
            if localization.kind == FaultKind.SPAN
            else self.topology.poles.keys()
        )
        unexplained_dark = {
            pole_id
            for pole_id in relevant_scope
            if pole_id not in affected
            and pole_id in self.observations
            and not self.observations[pole_id].energized
        }
        expected_loss_reports = max(round(0.7 * len(expected_reporters)), 1)
        support = min(len(observed_dark) / expected_loss_reports, 1.0)
        contradiction_penalty = len(live_contradictions) / max(len(expected_reporters), 1)
        leakage_penalty = len(unexplained_dark) / max(
            len(observed_dark) + len(unexplained_dark), 1
        )
        fit_score = round(
            max(0.0, support * (1 - contradiction_penalty) * (1 - leakage_penalty)),
            2,
        )
        if fit_score >= 0.9:
            verdict = "strong causal match"
        elif fit_score >= 0.65:
            verdict = "probable causal match"
        else:
            verdict = "weak match; verify the candidate corridor"
        return CausalFingerprint(
            predicted_reporting=len(expected_reporters),
            observed_dark=len(observed_dark),
            silent_or_unknown=max(
                len(expected_reporters) - len(observed_dark) - len(live_contradictions),
                0,
            ),
            live_contradictions=len(live_contradictions),
            unexplained_dark=len(unexplained_dark),
            expected_loss_reports=expected_loss_reports,
            fit_score=fit_score,
            verdict=verdict,
            schedule_context=schedule_context,
            schedule_coverage=schedule_coverage,
        )

    def _choose_target(self, kind: str) -> str:
        active_targets = {item.target_id for item in self.simulations.values() if not item.repaired}
        if kind == "span":
            return self._choose_span_target()
        if kind == "dt":
            for transformer in self.network.transformers:
                if transformer.dt_id not in active_targets:
                    return transformer.dt_id
        if kind == "feeder":
            for transformer in self.network.transformers:
                if transformer.feeder_id not in active_targets:
                    return transformer.feeder_id
        raise ValueError(f"No available target for {kind}")

    def _choose_span_target(self, dt_id: str | None = None) -> str:
        active_targets = {item.target_id for item in self.simulations.values() if not item.repaired}
        active_span_dts = {
            self.topology.poles[item.target_id].dt_id
            for item in self.simulations.values()
            if not item.repaired and item.target_id in self.topology.poles
        }
        by_dt: dict[str, list[str]] = {}
        for pole in self.network.poles:
            by_dt.setdefault(pole.dt_id, []).append(pole.pole_id)
        for candidate_dt_id, pole_ids in by_dt.items():
            if dt_id and candidate_dt_id != dt_id:
                continue
            if not dt_id and candidate_dt_id in active_span_dts:
                continue
            candidates = [
                pole_id
                for pole_id in pole_ids
                if self.network.true_parent[pole_id]
                and any(parent_id == pole_id for parent_id in self.network.true_parent.values())
                and pole_id not in active_targets
            ]
            viable_candidates = [
                pole_id
                for pole_id in candidates
                if sum(
                    self._reports_loss(affected_pole_id)
                    for affected_pole_id in self._physical_affected("span", pole_id)
                )
                >= 2
            ]
            if viable_candidates:
                return viable_candidates[len(viable_candidates) // 2]
        raise ValueError("No available target for span")

    def _physical_affected(self, kind: str, target_id: str) -> set[str]:
        if kind == "span":
            children: dict[str, list[str]] = {pole.pole_id: [] for pole in self.network.poles}
            for pole_id, parent_id in self.network.true_parent.items():
                if parent_id:
                    children[parent_id].append(pole_id)
            affected = {target_id}
            pending = list(children[target_id])
            while pending:
                pole_id = pending.pop()
                affected.add(pole_id)
                pending.extend(children[pole_id])
            return affected
        if kind == "dt":
            return {pole.pole_id for pole in self.network.poles if pole.dt_id == target_id}
        if kind == "feeder":
            return {pole.pole_id for pole in self.network.poles if pole.feeder_id == target_id}
        raise ValueError(f"Unknown fault type {kind}")

    def _loss_events(self, affected: set[str]) -> list[TelemetryEvent]:
        events: list[TelemetryEvent] = []
        timestamp = iso_now()
        for pole_id in sorted(affected):
            if not self._reports_loss(pole_id):
                continue
            events.append(self._event(pole_id, "power_lost", False, timestamp))
        return events

    def _reports_loss(self, pole_id: str) -> bool:
        pole = self.topology.poles[pole_id]
        return bool(
            pole.device_id
            and pole_id not in self.unrelated_offline
            and not self.network.firmware[pole.device_id].startswith("1.2")
            and sum(ord(character) for character in pole_id) % 10 < 7
        )

    def _restoration_events(self, affected: set[str]) -> list[TelemetryEvent]:
        events: list[TelemetryEvent] = []
        restored_at = datetime.now(UTC)
        for pole_id in sorted(affected):
            pole = self.topology.poles[pole_id]
            if not pole.device_id or pole_id in self.unrelated_offline:
                continue
            firmware = self.network.firmware[pole.device_id]
            events.append(
                TelemetryEvent(
                    device_id=pole.device_id,
                    pole_id=pole_id,
                    event="boot",
                    energized=True,
                    ts=iso_now(restored_at),
                    seq=0,
                    fw=firmware,
                )
            )
            events.append(
                TelemetryEvent(
                    device_id=pole.device_id,
                    pole_id=pole_id,
                    event="power_restored",
                    energized=True,
                    ts=iso_now(restored_at + timedelta(seconds=1)),
                    seq=1,
                    fw=firmware,
                )
            )
        return events

    def _event(self, pole_id: str, event: str, energized: bool, timestamp: str) -> TelemetryEvent:
        pole = self.topology.poles[pole_id]
        if not pole.device_id:
            raise ValueError(f"Pole {pole_id} has no device")
        sequence = self._device_seq.get(pole.device_id, 100) + 1
        self._device_seq[pole.device_id] = sequence
        return TelemetryEvent(
            device_id=pole.device_id,
            pole_id=pole_id,
            event=event,
            energized=energized,
            ts=timestamp,
            seq=sequence,
            fw=self.network.firmware[pole.device_id],
        )

    def _inject_sensor_failure(self, target_id: str | None) -> dict[str, object]:
        candidates = [
            pole
            for pole in self.network.poles
            if pole.device_id
            and self.topology.children[pole.pole_id]
            and any(
                self.topology.poles[child].device_id
                for child in self.topology.children[pole.pole_id]
            )
        ]
        pole = next((item for item in candidates if item.pole_id == target_id), candidates[20])
        child_id = next(
            child
            for child in self.topology.children[pole.pole_id]
            if self.topology.poles[child].device_id
        )
        timestamp = iso_now()
        loss = self._event(pole.pole_id, "power_lost", False, timestamp)
        heartbeat = self._event(
            child_id, "heartbeat", True, iso_now(datetime.now(UTC) + timedelta(seconds=1))
        )
        telemetry = self.ingest([loss, heartbeat])
        return {
            "kind": "sensor_failure",
            "target_id": pole.pole_id,
            "affected_poles": 0,
            "telemetry": telemetry,
            "suppressed": True,
            "reason": "Live downstream evidence makes a line fault physically impossible",
        }

    def _inject_duplicate_noise(self, target_id: str | None) -> dict[str, object]:
        pole = next(
            pole
            for pole in self.network.poles
            if pole.device_id and (target_id is None or pole.pole_id == target_id)
        )
        event = self._event(pole.pole_id, "heartbeat", True, iso_now())
        out_of_order = TelemetryEvent(
            device_id=event.device_id,
            pole_id=event.pole_id,
            event="heartbeat",
            energized=True,
            ts=iso_now(datetime.now(UTC) - timedelta(seconds=30)),
            seq=event.seq - 2,
            fw=event.fw,
        )
        telemetry = self.ingest([event, event, out_of_order])
        return {
            "kind": "duplicate_noise",
            "target_id": pole.pole_id,
            "telemetry": telemetry,
            "suppressed": True,
        }


def iso_now(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
