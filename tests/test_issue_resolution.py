"""Focused regression tests for fixes from the release-candidate audit."""

import unittest
from unittest.mock import patch
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.comparison import compare_measurements
from python.input_validation import validate_message_id
from python.integration.schemas import OptimizationBenefits, OptimizationResponse
from python.integration.job_manager import OptimizationJobManager
from python.integration.supabase_repository import SupabaseRepository
from python.metrics_collector import MetricsCollector
from python.scenario_inputs import default_density, make_route_variant
from python.simulation_pair import SimulationPair
from python.traci_controller import TraCIController
from python.integration.id_mapper import CORRIDOR_MAP
import python.traci_controller as controller_module


class FixedClient:
    def __init__(self):
        self.calls = 0

    def optimize(self, request):
        self.calls += 1
        return OptimizationResponse(
            message_id=request.message_id,
            simulation_id=request.simulation_id,
            scenario_id=request.scenario_id,
            optimizer_used="Quantum",
            bitstring="100000000000000000",
            objective_value=7.25,
            benefits=OptimizationBenefits(travel_time_saved_minutes=1.0, queue_reduction_percent=2.0),
            status="completed",
        )


class Domain:
    pass


class IssueResolutionTests(unittest.TestCase):
    def test_measured_comparison_uses_quantum_minus_classical_and_valid_percent(self):
        result = compare_measurements(
            {"avg_speed_kmh": 10.0, "queue_length_m": 100.0, "avg_completed_travel_time_s": None},
            {"avg_speed_kmh": 12.0, "queue_length_m": 75.0, "avg_completed_travel_time_s": 50.0},
        )
        self.assertEqual(result["avg_speed_kmh"]["quantum_minus_classical"], 2.0)
        self.assertEqual(result["avg_speed_kmh"]["improvement_percent"], 20.0)
        self.assertEqual(result["queue_length_m"]["improvement_percent"], 25.0)
        self.assertIsNone(result["avg_completed_travel_time_s"]["quantum_minus_classical"])
        self.assertIsNone(compare_measurements({"queue_length_m": 0}, {"queue_length_m": 1})["queue_length_m"]["improvement_percent"])
        self.assertIsNone(compare_measurements({"queue_length_m": 1}, {"queue_length_m": 2}, synchronized=False)["queue_length_m"]["quantum_minus_classical"])

    def test_metrics_are_measured_not_seeded_and_record_completed_trips(self):
        collector = MetricsCollector()
        vehicle = {"id": "v1", "type": "car", "speed": 5.0, "waiting_time": 2.0,
                   "accumulated_waiting_time": 9.0}
        collector.update(100.0, [vehicle], [], {"edge": {"occupancy": 0.1, "queue_len": 6.5}},
                         "event_day", [40.0, 60.0], [3.0, 5.0])
        self.assertNotIn("scenario_stats", collector.__dict__)
        self.assertEqual(collector.live_kpis["completed_vehicles"], 2)
        self.assertEqual(collector.live_kpis["avg_completed_travel_time_s"], 50.0)
        self.assertEqual(collector.live_kpis["total_completed_travel_time_s"], 100.0)
        self.assertEqual(collector.live_kpis["accumulated_waiting_time_s"], 9.0)

    def test_speed_target_stores_each_requested_multiplier(self):
        controller = TraCIController(label="speed-unit")
        for multiplier in (1, 2, 3, 4, 1):
            controller.set_speed(multiplier)
            self.assertEqual(controller.speed_multiplier, multiplier)

    def test_pair_sync_checks_pair_scenario_inputs_network_and_time(self):
        classical = TraCIController(label="sync-classical", simulation_id="pair_test_classical")
        quantum = TraCIController(label="sync-quantum", simulation_id="pair_test_quantum")
        pair = SimulationPair(classical=classical, quantum=quantum)
        pair.run_id, pair.scenario_id = "pair_test", "event_day"
        def state(sim_id, clock):
            return {"simulation_id": sim_id, "scenario_id": "event_day", "config_hash": "cfg",
                    "network_hash": "net", "time": clock}
        classical.latest_state = state(classical.simulation_id, 20.0)
        quantum.latest_state = state(quantum.simulation_id, 20.5)
        self.assertTrue(pair.synchronization()["synchronized"])
        quantum.latest_state["config_hash"] = "other"
        self.assertEqual(pair.synchronization()["status"], "DESYNCHRONIZED")

    def test_message_id_contract_rejects_missing_and_unsafe_values(self):
        self.assertEqual(validate_message_id("TEST-123"), "TEST-123")
        for value in (None, "", "a" * 129, "bad id", "\n"):
            with self.assertRaises(ValueError):
                validate_message_id(value)

    def test_duplicate_request_is_skipped_without_second_optimizer_call(self):
        client = FixedClient()
        repo = SupabaseRepository(supabase_url="", supabase_key="")
        manager = OptimizationJobManager(repository=repo, client=client)
        first = manager.create_and_run_job("sim_test", "event_day", apply_to_sumo=False,
                                           message_id="TEST-123")
        second = manager.create_and_run_job("sim_test", "event_day", apply_to_sumo=False,
                                            message_id="TEST-123")
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(repo.list_recent_runs()), 1)

    def test_optimization_lifecycle_emits_backend_stages(self):
        manager = OptimizationJobManager(
            repository=SupabaseRepository(supabase_url="", supabase_key=""), client=FixedClient())
        events = []
        manager.status_callback = events.append
        response = manager.create_and_run_job("sim_lifecycle", "event_day", apply_to_sumo=False,
                                               message_id="LIFECYCLE-001")
        stages = [event["stage"] for event in events]
        self.assertEqual(response.status, "completed")
        for stage in ("QUEUED", "RUNNING", "RESULT_RECEIVED", "VALIDATING", "MAPPING", "COMPLETED"):
            self.assertIn(stage, stages)

    def test_density_route_file_scales_flow_definitions(self):
        density = default_density("event_day")
        modified = dict(density)
        modified["cars"] = 1000
        path = make_route_variant("event_day", modified)
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(path).getroot()
            total = 0.0
            for item in root:
                if item.tag == "flow" and item.get("type") in {"car", "taxi"}:
                    total += float(item.get("vehsPerHour", "0"))
            self.assertAlmostEqual(total, 1000.0, places=3)
        finally:
            path.unlink(missing_ok=True)

    def test_route_block_closes_entry_and_reopen_restores_lane_permissions(self):
        mapping = CORRIDOR_MAP["Anna Salai"]
        edge_ids = mapping.primary_sumo_edges + mapping.reverse_sumo_edges
        lane = Domain()
        lane.allowed = {f"{edge}_0": [] for edge in edge_ids}
        lane.disallowed = {f"{edge}_0": [] for edge in edge_ids}
        lane.speeds = {f"{edge}_0": 13.9 for edge in edge_ids}
        lane.getMaxSpeed = lambda lane_id: lane.speeds[lane_id]
        lane.setMaxSpeed = lambda lane_id, value: lane.speeds.__setitem__(lane_id, value)
        lane.getAllowed = lambda lane_id: lane.allowed[lane_id]
        lane.getDisallowed = lambda lane_id: lane.disallowed[lane_id]
        lane.setAllowed = lambda lane_id, values: lane.allowed.__setitem__(lane_id, list(values))
        lane.setDisallowed = lambda lane_id, values: lane.disallowed.__setitem__(lane_id, list(values))
        edge = Domain()
        edge.getIDList = lambda: edge_ids
        edge.getLaneNumber = lambda _edge_id: 1
        edge.getTraveltime = lambda _edge_id: 10.0
        edge.getLength = lambda _edge_id: 100.0
        edge.adaptTraveltime = lambda _edge_id, _cost: None
        vehicle_types = Domain()
        vehicle_types.getIDList = lambda: ["car"]
        vehicle_types.getVehicleClass = lambda _vtype: "passenger"
        vehicle = Domain()
        vehicle.getIDList = lambda: []
        domains = {"edge": edge, "lane": lane, "vehicletype": vehicle_types, "vehicle": vehicle}
        controller = TraCIController(label="route-test")
        controller.base_lane_permissions = dict(lane.allowed)
        controller.base_lane_disallowed = dict(lane.disallowed)
        controller.lane_base_speed_limits = dict(lane.speeds)
        with patch.object(controller_module.traci, "switch"), \
             patch.object(controller_module.traci, "edge", edge), \
             patch.object(controller_module.traci, "lane", lane), \
             patch.object(controller_module.traci, "vehicletype", vehicle_types), \
             patch.object(controller_module.traci, "vehicle", vehicle):
            blocked = controller.apply_route_control("Anna Salai", blocked=True)
            self.assertTrue(blocked["new_entries_blocked"])
            self.assertTrue(all("passenger" in lane.disallowed[lane_id] for lane_id in lane.disallowed))
            reopened = controller.apply_route_control("Anna Salai", blocked=False)
        self.assertTrue(reopened["readback_confirmed"])
        self.assertTrue(all(lane.disallowed[lane_id] == [] for lane_id in lane.disallowed))

    def test_route_block_rejects_scheduled_flow_route_conflicts_before_traci(self):
        controller = TraCIController(label="route-flow-safety")
        controller.flow_route_edges = set(CORRIDOR_MAP["Anna Salai"].primary_sumo_edges +
                                          CORRIDOR_MAP["Anna Salai"].reverse_sumo_edges)
        with patch.object(controller_module.traci, "switch") as switch:
            with self.assertRaisesRegex(ValueError, "scheduled vehicles invalid"):
                controller.apply_route_control("Anna Salai", blocked=True)
            switch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
