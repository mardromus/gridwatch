import unittest

from app.domain import Topology, TopologySource
from app.seed import generate_network


class SeedNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.network = generate_network()

    def test_seed_has_a_few_thousand_poles(self) -> None:
        self.assertEqual(len(self.network.poles), 2_160)
        self.assertEqual(len(self.network.transformers), 30)

    def test_seed_matches_device_and_topology_proportions(self) -> None:
        device_ratio = sum(pole.device_id is not None for pole in self.network.poles) / len(
            self.network.poles
        )
        inferred_ratio = sum(
            pole.topology_source == TopologySource.INFERRED for pole in self.network.poles
        ) / len(self.network.poles)

        self.assertAlmostEqual(device_ratio, 0.91, delta=0.02)
        self.assertAlmostEqual(inferred_ratio, 0.60, delta=0.01)

    def test_inferred_graph_is_acyclic(self) -> None:
        topology = Topology(self.network.poles)
        for pole in self.network.poles:
            topology.ancestors(pole.pole_id)

    def test_seed_has_branched_multi_circuit_layouts(self) -> None:
        children = {pole.pole_id: 0 for pole in self.network.poles}
        for parent_id in self.network.true_parent.values():
            if parent_id:
                children[parent_id] += 1

        roots_by_dt: dict[str, int] = {}
        inferred_roots_by_dt: dict[str, int] = {}
        for pole in self.network.poles:
            if self.network.true_parent[pole.pole_id] is None:
                roots_by_dt[pole.dt_id] = roots_by_dt.get(pole.dt_id, 0) + 1
            if (
                pole.topology_source == TopologySource.INFERRED
                and pole.parent_pole_id is None
            ):
                inferred_roots_by_dt[pole.dt_id] = inferred_roots_by_dt.get(pole.dt_id, 0) + 1

        branch_points = sum(child_count > 1 for child_count in children.values())
        self.assertEqual(set(roots_by_dt.values()), {2})
        self.assertGreaterEqual(branch_points, len(self.network.transformers) * 4)
        self.assertTrue(all(root_count >= 2 for root_count in inferred_roots_by_dt.values()))


if __name__ == "__main__":
    unittest.main()
