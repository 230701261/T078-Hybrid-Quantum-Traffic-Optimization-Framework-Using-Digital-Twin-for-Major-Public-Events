from contextlib import nullcontext
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from python.simulation_pair import (SimulationPair, _diversion_target_count,
                                    _route_position_is_reroutable,
                                    _ordered_edges_in_route)
from python.integration.constraint_engine import ConstraintEngine


class OperatorOperationTests(TestCase):
    def test_entry_block_rejects_scheduled_flow_conflict(self):
        result = ConstraintEngine.validate_batch([{
            "action_type": "operator_entry_block", "sumo_target_id": "edge-live",
            "parameters": {"blocked": True, "scheduled_flow_conflict": True,
                           "active_route_conflict": False}}], {"edge_ids": {"edge-live"}})
        self.assertFalse(result["valid"])
        self.assertIn("SCHEDULED_FLOW_CONFLICT", {item["code"] for item in result["errors"]})

    def test_diversion_share_rounds_only_to_real_vehicle_count(self):
        self.assertEqual(_diversion_target_count(100, 58), 58)
        self.assertEqual(_diversion_target_count(3, 58), 2)
        self.assertEqual(_diversion_target_count(0, 58), 0)

    def test_route_changes_wait_until_vehicle_leaves_internal_junction_edge(self):
        self.assertFalse(_route_position_is_reroutable(("edge-a", "edge-b"), 1, ":junction_0"))
        self.assertFalse(_route_position_is_reroutable(("edge-a", "edge-b"), 0, "edge-b"))
        self.assertTrue(_route_position_is_reroutable(("edge-a", "edge-b"), 1, "edge-b"))

    def test_route_readback_requires_bus_stops_in_original_order(self):
        self.assertTrue(_ordered_edges_in_route(("current", "alt", "stop-a", "stop-b", "dest"),
                                                ("stop-a", "stop-b")))
        self.assertFalse(_ordered_edges_in_route(("current", "alt", "stop-b", "stop-a", "dest"),
                                                 ("stop-a", "stop-b")))

    def test_route_operation_rejects_same_corridor_before_live_access(self):
        pair = SimulationPair(classical=object(), quantum=object())
        with self.assertRaisesRegex(ValueError, "different discovered corridors"):
            pair.apply_operator_route_operation("Anna Salai", "Anna Salai", 50)

    def test_route_operation_uses_configured_share_range(self):
        pair = SimulationPair(classical=object(), quantum=object())
        with self.assertRaisesRegex(ValueError, "between"):
            pair.apply_operator_route_operation("Anna Salai", "Wallajah Road", 101)

    def test_signal_failure_rolls_both_contexts_back(self):
        class FakeController:
            running = True

            def __init__(self, fail_apply=False):
                self.duration = 10.0
                self.fail_apply = fail_apply

            def traci_session(self):
                return nullcontext()

            def network_signals(self):
                return [{"tls_id": "live-tls", "current_phase": 0,
                         "phases": [{"phase": 0, "duration_s": self.duration,
                                     "min_duration_s": 5.0, "max_duration_s": 30.0}]}]

            def optimizer_constraint_context(self):
                return {"tls_ids": {"live-tls"}}

            def set_signal_phase_duration(self, _tls, _phase, duration):
                if self.fail_apply and duration != 10.0:
                    raise RuntimeError("simulated quantum TraCI failure")
                previous = self.duration
                self.duration = float(duration)
                return {"verified": True, "before_duration_s": previous,
                        "actual_duration_s": self.duration}

        classical, quantum = FakeController(), FakeController(fail_apply=True)
        pair = SimulationPair(classical=classical, quantum=quantum)
        with patch("python.simulation_pair.ConstraintEngine.validate_batch",
                   return_value={"valid": True, "errors": []}):
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                pair.apply_operator_signal_timing("live-tls", 0, 20.0)
        self.assertEqual(classical.duration, 10.0)
        self.assertEqual(quantum.duration, 10.0)

    def test_signal_constraint_rejection_mutates_neither_context(self):
        class FakeController:
            def __init__(self):
                self.calls = []

            def traci_session(self):
                return nullcontext()

            def network_signals(self):
                return [{"tls_id": "live-tls", "current_phase": 0,
                         "phases": [{"phase": 0, "duration_s": 10.0,
                                     "min_duration_s": 5.0, "max_duration_s": 30.0}]}]

            def optimizer_constraint_context(self):
                return {"tls_ids": {"live-tls"}}

            def set_signal_phase_duration(self, *_args):
                self.calls.append(_args)

        classical, quantum = FakeController(), FakeController()
        pair = SimulationPair(classical=classical, quantum=quantum)
        with patch("python.simulation_pair.ConstraintEngine.validate_batch",
                   return_value={"valid": False, "errors": [{"message": "timing not allowed"}]}):
            with self.assertRaisesRegex(ValueError, "timing not allowed"):
                pair.apply_operator_signal_timing("live-tls", 0, 20.0)
        self.assertEqual(classical.calls, [])
        self.assertEqual(quantum.calls, [])
