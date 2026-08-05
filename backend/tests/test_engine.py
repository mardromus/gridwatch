import unittest
from datetime import UTC, datetime, timedelta

from app.engine import GridService, TelemetryEvent, TicketStatus, iso_now
from app.seed import generate_network


class GridServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = GridService(generate_network(dt_count=6, poles_per_dt=30))

    def test_span_fault_creates_one_ticket_not_one_per_dark_pole(self) -> None:
        simulation = self.service.inject("span")

        incidents = self.service.dashboard()["incidents"]
        self.assertEqual(len(incidents), 1)
        self.assertGreater(simulation["affected_poles"], 1)
        self.assertEqual(incidents[0]["kind"], "span")
        self.assertGreater(incidents[0]["affected_households"], 0)
        self.assertEqual(
            len(incidents[0]["affected_pole_ids"]),
            len(self.service.incidents[incidents[0]["incident_id"]].affected_pole_ids),
        )
        self.assertEqual(
            self.service.dashboard()["summary"]["affected_households"],
            incidents[0]["affected_households"],
        )
        fingerprint = incidents[0]["fingerprint"]
        self.assertGreater(fingerprint["observed_dark"], 0)
        self.assertEqual(fingerprint["live_contradictions"], 0)
        self.assertGreaterEqual(fingerprint["fit_score"], 0.65)

    def test_three_simultaneous_faults_create_three_tickets(self) -> None:
        for _ in range(3):
            self.service.inject("span")

        incidents = self.service.dashboard()["incidents"]
        self.assertEqual(len(incidents), 3)
        self.assertEqual(len({incident["dt_id"] for incident in incidents}), 3)

    def test_sensor_failure_does_not_create_incident(self) -> None:
        result = self.service.inject("sensor_failure")

        self.assertTrue(result["suppressed"])
        self.assertEqual(self.service.dashboard()["incidents"], [])

    def test_unrelated_offline_baseline_is_unknown_and_does_not_alert(self) -> None:
        installed = sum(pole.device_id is not None for pole in self.service.network.poles)
        reporting = self.service.dashboard()["summary"]["reporting_devices"]

        self.assertAlmostEqual(reporting / installed, 0.96, delta=0.02)
        self.assertEqual(set(self.service.observations) & self.service.unrelated_offline, set())
        self.assertEqual(self.service.dashboard()["incidents"], [])

    def test_single_loss_waits_for_independent_dark_corroboration(self) -> None:
        target = self.service._choose_target("span")
        events = self.service._loss_events(
            self.service._physical_affected("span", target)
        )
        self.assertGreaterEqual(len(events), 2)

        self.service.ingest([events[0]])
        self.assertEqual(self.service.dashboard()["incidents"], [])

        self.service.ingest([events[1]])
        self.assertEqual(len(self.service.dashboard()["incidents"]), 1)

    def test_downstream_first_packets_refine_one_incident(self) -> None:
        target = self.service._choose_target("span")
        events = reversed(
            self.service._loss_events(
                self.service._physical_affected("span", target)
            )
        )

        for event in events:
            self.service.ingest([event])

        self.assertEqual(len(self.service.incidents), 1)
        incident = next(iter(self.service.incidents.values()))
        self.assertIn("refined", [entry.event for entry in incident.timeline])

    def test_scheduled_outage_does_not_create_incident(self) -> None:
        result = self.service.inject("scheduled_outage")

        self.assertTrue(result["suppressed"])
        self.assertEqual(self.service.dashboard()["incidents"], [])

    def test_partial_fault_inside_scheduled_window_is_escalated(self) -> None:
        result = self.service.inject("schedule_mismatch")

        incidents = self.service.dashboard()["incidents"]
        self.assertFalse(result["suppressed"])
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["fingerprint"]["schedule_context"], "mismatch")
        self.assertLess(incidents[0]["fingerprint"]["schedule_coverage"], 0.65)
        self.assertIn("planned window", incidents[0]["timeline"][0]["detail"])

    def test_duplicate_and_out_of_order_messages_are_rejected(self) -> None:
        result = self.service.inject("duplicate_noise")

        self.assertEqual(result["telemetry"]["accepted"], 1)
        self.assertEqual(result["telemetry"]["duplicates"], 1)
        self.assertEqual(result["telemetry"]["stale"], 1)
        self.assertEqual(self.service.audit_store.counts()["telemetry_events"], 1)

    def test_late_retry_does_not_overwrite_current_state(self) -> None:
        pole = next(pole for pole in self.service.network.poles if pole.device_id)
        late_loss = TelemetryEvent(
            device_id=pole.device_id or "",
            pole_id=pole.pole_id,
            event="power_lost",
            energized=False,
            ts=iso_now(datetime.now(UTC) - timedelta(hours=6)),
            seq=999,
        )

        result = self.service.ingest([late_loss])

        self.assertEqual(result["stale"], 1)
        self.assertTrue(self.service.observations[pole.pole_id].energized)
        self.assertEqual(self.service.dashboard()["incidents"], [])

    def test_timezone_naive_timestamp_is_rejected_without_mutating_state(self) -> None:
        pole = next(pole for pole in self.service.network.poles if pole.device_id)
        naive_loss = TelemetryEvent(
            device_id=pole.device_id or "",
            pole_id=pole.pole_id,
            event="power_lost",
            energized=False,
            ts=datetime.now().isoformat(timespec="milliseconds"),
            seq=101,
        )

        result = self.service.ingest([naive_loss])

        self.assertEqual(result["rejected"], 1)
        self.assertTrue(self.service.observations[pole.pole_id].energized)
        self.assertEqual(self.service.dashboard()["incidents"], [])

    def test_repair_only_closes_after_operator_marks_work_complete(self) -> None:
        simulation = self.service.inject("span")
        incident_id = self.service.dashboard()["incidents"][0]["incident_id"]
        self.service.transition(incident_id, "acknowledge")
        self.service.transition(incident_id, "assign", "Crew 7")
        self.service.transition(incident_id, "resolve")

        awaiting = self.service.incidents[incident_id]
        self.assertEqual(awaiting.status, TicketStatus.RESOLVED)
        self.assertEqual(awaiting.verification_ratio, 0)

        self.service.repair(simulation["simulation_id"])

        closed = self.service.incidents[incident_id]
        self.assertEqual(closed.status, TicketStatus.CLOSED)
        self.assertGreaterEqual(closed.verification_ratio, 0.8)
        self.assertEqual(closed.timeline[-2].event, "verified")
        self.assertEqual(self.service.audit_store.counts()["incident_snapshots"], 1)

    def test_repair_before_work_complete_is_rejected_and_remains_available(self) -> None:
        simulation = self.service.inject("span")
        incident_id = self.service.dashboard()["incidents"][0]["incident_id"]

        with self.assertRaisesRegex(ValueError, f"Mark {incident_id} work complete"):
            self.service.repair(simulation["simulation_id"])

        self.assertFalse(self.service.simulations[simulation["simulation_id"]].repaired)
        self.assertFalse(
            all(
                self.service.physical_energized[pole_id]
                for pole_id in self.service.simulations[
                    simulation["simulation_id"]
                ].affected_pole_ids
            )
        )

    def test_repair_emits_boot_then_restored_with_reset_sequence(self) -> None:
        simulation = self.service.inject("span")
        incident_id = self.service.dashboard()["incidents"][0]["incident_id"]
        self.service.transition(incident_id, "acknowledge")
        self.service.transition(incident_id, "assign", "Crew 7")
        self.service.transition(incident_id, "resolve")

        result = self.service.repair(simulation["simulation_id"])

        self.assertEqual(result["events_emitted"], result["restored"] * 2)
        affected_reporter = next(
            pole_id
            for pole_id in self.service.simulations[
                simulation["simulation_id"]
            ].affected_pole_ids
            if self.service.topology.poles[pole_id].device_id
        )
        restoration_rows = self.service.audit_store.connection.execute(
            """
            SELECT event_type, sequence_number
            FROM telemetry_events
            WHERE pole_id = ? AND event_type IN ('boot', 'power_restored')
            ORDER BY rowid
            """,
            (affected_reporter,),
        ).fetchall()
        self.assertEqual(restoration_rows, [("boot", 0), ("power_restored", 1)])

    def test_ticket_workflow_rejects_skipped_states(self) -> None:
        self.service.inject("span")
        incident_id = self.service.dashboard()["incidents"][0]["incident_id"]

        with self.assertRaisesRegex(ValueError, "Cannot assign"):
            self.service.transition(incident_id, "assign", "Crew 7")
        self.service.transition(incident_id, "acknowledge")
        with self.assertRaisesRegex(ValueError, "Cannot resolve"):
            self.service.transition(incident_id, "resolve")


if __name__ == "__main__":
    unittest.main()
