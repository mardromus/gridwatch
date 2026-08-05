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


if __name__ == "__main__":
    unittest.main()
