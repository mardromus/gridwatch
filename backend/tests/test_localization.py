import unittest

from app.domain import FaultKind, Observation, Pole, Topology, TopologySource


def pole(
    pole_id: str,
    parent: str | None,
    *,
    dt: str = "D-1",
    feeder: str = "F-1",
    source: TopologySource = TopologySource.RECORDED,
) -> Pole:
    number = int(pole_id.split("-")[-1])
    return Pole(
        pole_id=pole_id,
        lat=12.96 + number / 10_000,
        lon=77.59,
        feeder_id=feeder,
        dt_id=dt,
        pincode="560078",
        parent_pole_id=parent,
        topology_source=source,
        device_id=f"DEV-{pole_id}",
    )


class LocalizationTests(unittest.TestCase):
    def test_groups_downstream_dark_poles_into_one_span(self) -> None:
        topology = Topology([pole("P-1", None), pole("P-2", "P-1"), pole("P-3", "P-2")])
        result = topology.localize(
            {"P-1": Observation(True), "P-2": Observation(False), "P-3": Observation(False)}
        )

        self.assertEqual(len(result.faults), 1)
        self.assertEqual(result.faults[0].asset_id, "P-1--P-2")
        self.assertEqual(result.faults[0].affected_poles, 2)

    def test_isolated_dark_sensor_with_live_child_is_not_a_fault(self) -> None:
        topology = Topology([pole("P-1", None), pole("P-2", "P-1"), pole("P-3", "P-2")])
        result = topology.localize(
            {
                "P-1": Observation(True, "2026-08-04T01:01:00Z"),
                "P-2": Observation(False, "2026-08-04T01:00:00Z"),
                "P-3": Observation(True, "2026-08-04T01:01:00Z"),
            }
        )

        self.assertEqual(result.faults, ())
        self.assertEqual(result.sensor_anomalies, ("P-2",))

    def test_stale_live_heartbeat_below_new_dark_report_does_not_hide_fault(self) -> None:
        topology = Topology([pole("P-1", None), pole("P-2", "P-1"), pole("P-3", "P-2")])
        result = topology.localize(
            {
                "P-1": Observation(True, "2026-08-04T00:59:00Z"),
                "P-2": Observation(False, "2026-08-04T01:00:00Z"),
                "P-3": Observation(True, "2026-08-04T00:58:00Z"),
            }
        )

        self.assertEqual(len(result.faults), 1)
        self.assertEqual(result.faults[0].asset_id, "P-1--P-2")

    def test_missing_boundary_device_reports_a_range(self) -> None:
        topology = Topology([pole("P-1", None), pole("P-2", "P-1"), pole("P-3", "P-2")])
        result = topology.localize({"P-1": Observation(True), "P-3": Observation(False)})

        fault = result.faults[0]
        self.assertEqual(fault.candidate_path, ("P-2", "P-3"))
        self.assertEqual(fault.upstream_pole_id, "P-1")
        self.assertLess(fault.confidence, 0.9)

    def test_finds_two_faults_on_separate_branches(self) -> None:
        topology = Topology(
            [
                pole("P-1", None),
                pole("P-2", "P-1"),
                pole("P-3", "P-2"),
                pole("P-4", "P-1"),
                pole("P-5", "P-4"),
            ]
        )
        result = topology.localize(
            {
                "P-1": Observation(True),
                "P-2": Observation(False),
                "P-3": Observation(False),
                "P-4": Observation(False),
                "P-5": Observation(False),
            }
        )

        self.assertEqual({fault.asset_id for fault in result.faults}, {"P-1--P-2", "P-1--P-4"})

    def test_geometry_inferred_topology_is_explicitly_lower_confidence(self) -> None:
        topology = Topology(
            [
                pole("P-1", None, source=TopologySource.INFERRED),
                pole("P-2", "P-1", source=TopologySource.INFERRED),
            ]
        )
        result = topology.localize({"P-1": Observation(True), "P-2": Observation(False)})

        self.assertEqual(result.faults[0].kind, FaultKind.SPAN)
        self.assertEqual(result.faults[0].confidence, 0.68)
        self.assertIn("geometry-inferred", " ".join(result.faults[0].reasons))

    def test_fragmented_inferred_boundaries_become_one_fault_zone(self) -> None:
        topology = Topology(
            [
                pole("P-1", None, source=TopologySource.INFERRED),
                pole("P-2", "P-1", source=TopologySource.INFERRED),
                pole("P-3", "P-1", source=TopologySource.INFERRED),
            ]
        )
        result = topology.localize(
            {
                "P-1": Observation(True),
                "P-2": Observation(False),
                "P-3": Observation(False),
            }
        )

        self.assertEqual(len(result.faults), 1)
        self.assertEqual(result.faults[0].asset_id, "D-1 inferred fault zone")
        self.assertEqual(set(result.faults[0].candidate_path), {"P-2", "P-3"})
        self.assertLessEqual(result.faults[0].confidence, 0.5)

    def test_collapses_complete_transformer_outages_to_one_feeder_fault(self) -> None:
        poles = [
            pole("P-1", None, dt="D-1", feeder="F-1"),
            pole("P-2", "P-1", dt="D-1", feeder="F-1"),
            pole("P-3", None, dt="D-1", feeder="F-1"),
            pole("P-4", "P-3", dt="D-1", feeder="F-1"),
            pole("P-5", None, dt="D-2", feeder="F-1"),
            pole("P-6", "P-5", dt="D-2", feeder="F-1"),
            pole("P-7", None, dt="D-2", feeder="F-1"),
            pole("P-8", "P-7", dt="D-2", feeder="F-1"),
        ]
        result = Topology(poles).localize(
            {pole_item.pole_id: Observation(False) for pole_item in poles}
        )

        self.assertEqual(len(result.faults), 1)
        self.assertEqual(result.faults[0].kind, FaultKind.FEEDER)
        self.assertEqual(result.faults[0].asset_id, "F-1")


if __name__ == "__main__":
    unittest.main()
