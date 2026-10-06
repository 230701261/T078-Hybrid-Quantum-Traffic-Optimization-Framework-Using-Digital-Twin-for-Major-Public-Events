from unittest import TestCase
from unittest.mock import patch

import traci

from python.integration.quantum_sumo_adapter import TraCIAdapter
from python.integration.schemas import DigitalTwinCommand
from python.integration.constraint_engine import ConstraintEngine


class ConstraintEngineAdapterTests(TestCase):
    def command(self, action="route_diversion", target="edge-a", parameters=None):
        return DigitalTwinCommand(
            action_type=action,
            logical_target="route",
            canonical_target="route",
            sumo_target_id=target,
            parameters=parameters or {"priority_multiplier": 0.8},
        )

    def setup_live_api(self, closed=False):
        mutate = patch.object(traci.edge, "adaptTraveltime")
        stack = [
            patch.object(traci.edge, "getIDList", return_value=["edge-a"]),
            patch.object(traci.edge, "getLaneNumber", return_value=1),
            patch.object(traci.lane, "getAllowed", return_value=[]),
            patch.object(traci.lane, "getDisallowed", return_value=(
                ["passenger", "bus", "motorcycle", "rail"] if closed else [])),
            patch.object(traci.trafficlight, "getIDList", return_value=["tls-a"]),
            mutate,
        ]
        mutation_mock = None
        for item in stack:
            started = item.start()
            if item is mutate:
                mutation_mock = started
            self.addCleanup(item.stop)
        return mutation_mock

    def test_closed_edge_rejects_whole_batch_before_mutation(self):
        mutate = self.setup_live_api(closed=True)
        result = TraCIAdapter.apply_commands([self.command()])
        self.assertFalse(result["success"])
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(result["details"][0]["stage"], "constraint_validation")
        mutate.assert_not_called()

    def test_unknown_edge_rejects_before_mutation(self):
        mutate = self.setup_live_api()
        result = TraCIAdapter.apply_commands([self.command(target="not-an-edge")])
        self.assertFalse(result["success"])
        self.assertEqual(result["applied_count"], 0)
        mutate.assert_not_called()

    def test_unknown_tls_rejects_before_mutation(self):
        mutate = self.setup_live_api()
        command = self.command("signal_extension", "not-a-tls", {"extra_green": 5})
        result = TraCIAdapter.apply_commands([command])
        self.assertFalse(result["success"])
        self.assertEqual(result["applied_count"], 0)
        mutate.assert_not_called()

    def test_valid_batch_is_accepted(self):
        self.setup_live_api()
        result = ConstraintEngine.validate_batch([self.command()])
        self.assertEqual(result, {"valid": True, "errors": []})

    def test_unreachable_vehicle_destination_is_rejected(self):
        command = {"action_type": "vehicle_reroute", "sumo_target_id": "vehicle-a",
                   "parameters": {"vehicle_id": "vehicle-a", "route": ["edge-a"]}}
        result = ConstraintEngine.validate_batch([command], {
            "edge_ids": {"edge-a"}, "tls_ids": set(), "vehicle_ids": {"vehicle-a"},
            "route_validator": lambda _route: False,
        })
        self.assertFalse(result["valid"])
        self.assertIn("UNREACHABLE_DESTINATION", {e["code"] for e in result["errors"]})

    def test_soft_preference_conflicting_with_hard_closure_is_rejected(self):
        self.setup_live_api()
        command = self.command(parameters={"priority_multiplier": 0.8,
                                           "preferred_edges": ["edge-a"]})
        result = ConstraintEngine.validate_batch([command], {"blocked_edges": {"edge-a"}})
        self.assertFalse(result["valid"])
        self.assertIn("CONSTRAINT_CONFLICT", {e["code"] for e in result["errors"]})

    def test_edge_closure_rejects_affected_future_flow_preflight(self):
        command = {"action_type": "operator_edge_control", "sumo_target_id": "edge-a",
                   "parameters": {"blocked": True}}
        result = ConstraintEngine.validate_batch([command], {
            "edge_ids": {"edge-a"}, "tls_ids": set(),
            "flow_route_edges": {"edge-a"}, "active_route_edges": set(),
        })
        self.assertFalse(result["valid"])
        self.assertIn("SCHEDULED_FLOW_CONFLICT", {e["code"] for e in result["errors"]})

    def test_mixed_batch_rejects_all_before_mutation(self):
        mutate = self.setup_live_api()
        commands = [self.command(), self.command("signal_extension", "unknown-tls", {"extra_green": 4})]
        result = TraCIAdapter.apply_commands(commands)
        self.assertFalse(result["success"])
        self.assertEqual(result["applied_count"], 0)
        self.assertTrue(any(e["code"] == "INVALID_TLS" for e in result["validation"]["errors"]))
        mutate.assert_not_called()

    def test_batch_rejects_conflicting_close_and_edge_action(self):
        self.setup_live_api()
        close = {"action_type": "operator_edge_control", "sumo_target_id": "edge-a",
                 "parameters": {"blocked": True}}
        preference = self.command(parameters={"priority_multiplier": 0.8})
        result = ConstraintEngine.validate_batch([close, preference], {
            "edge_ids": {"edge-a"}, "tls_ids": set(), "flow_route_edges": set(),
            "active_route_edges": set(),
        })
        self.assertFalse(result["valid"])
        self.assertIn("CONFLICTING_OPERATIONS", {error["code"] for error in result["errors"]})
