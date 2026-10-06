from contextlib import nullcontext
from unittest import TestCase
from unittest.mock import Mock, patch

import traci
from python.simulation_pair import SimulationPair


class EdgeClosureTransactionTests(TestCase):
    def make_controller(self, flow_edges=(), active_edges=()):
        controller = Mock()
        controller.traci_session.return_value = nullcontext()
        controller.optimizer_constraint_context.return_value = {
            "edge_ids": {"edge-a", "edge-b"}, "tls_ids": set(),
            "vehicle_ids": set(), "flow_route_edges": set(flow_edges),
            "active_route_edges": set(active_edges), "blocked_edges": set(),
        }
        controller.apply_edge_closure.side_effect = lambda edges, closed: {
            "success": True, "status": "success", "edges": edges,
            "closed": closed, "mutations": len(edges),
        }
        controller.block_edges.side_effect = lambda edges: controller.apply_edge_closure(edges, True)
        controller.restore_edges.side_effect = lambda edges: controller.apply_edge_closure(edges, False)
        return controller

    def test_loaded_future_flow_rejects_pair_before_any_mutation(self):
        classical = self.make_controller(flow_edges={"edge-a"})
        quantum = self.make_controller()
        pair = SimulationPair(classical=classical, quantum=quantum)

        result = pair.apply_edge_closure(["edge-a"], True)

        self.assertFalse(result["success"])
        self.assertEqual(result["mutations"], 0)
        classical.apply_edge_closure.assert_not_called()
        quantum.apply_edge_closure.assert_not_called()

    def test_active_route_rejects_pair_before_any_mutation(self):
        classical = self.make_controller(active_edges={"edge-b"})
        quantum = self.make_controller()
        classical.optimizer_constraint_context.return_value["vehicle_ids"] = {"vehicle-a"}
        pair = SimulationPair(classical=classical, quantum=quantum)

        with patch.object(traci.vehicle, "getRoute", return_value=("edge-b", "edge-out")), \
                patch.object(traci.vehicle, "getRouteIndex", return_value=0):
            result = pair.apply_edge_closure(["edge-b"], True)

        self.assertFalse(result["success"])
        self.assertEqual(result["mutations"], 0)
        classical.apply_edge_closure.assert_not_called()
        quantum.apply_edge_closure.assert_not_called()

    def test_pair_closure_requires_both_live_context_readbacks(self):
        classical = self.make_controller()
        quantum = self.make_controller()
        pair = SimulationPair(classical=classical, quantum=quantum)

        result = pair.block_edges(["edge-a"])

        self.assertTrue(result["success"])
        classical.block_edges.assert_called_once_with(["edge-a"])
        quantum.block_edges.assert_called_once_with(["edge-a"])
