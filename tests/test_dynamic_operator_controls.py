"""Focused checks for dynamic operator metadata and configured effects."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.scenario_inputs import make_route_variant, default_density, operator_profiles
from python.traci_controller import TraCIController
from python.simulation_pair import SimulationPair
from python.integration.id_mapper import CORRIDOR_MAP
from python.integration.schemas import OptimizationRequestPayload
from python.server import live_intersection_loads, _json_safe
import math
import python.traci_controller as controller_module


class FakeDomain:
    pass


class DynamicOperatorControlTests(unittest.TestCase):
    def test_route_metadata_comes_from_active_route_variant(self):
        route_file = make_route_variant("event_day", default_density("event_day"))
        try:
            controller = TraCIController(label="route-metadata-test")
            controller.route_variant = route_file
            vehicle = FakeDomain()
            vehicle.getIDList = lambda: []
            with patch.object(controller_module.traci, "switch"), patch.object(controller_module.traci, "vehicle", vehicle):
                routes = controller.network_routes()
            self.assertTrue(routes)
            self.assertTrue(all(item["route_id"] and item["edges"] for item in routes))
            self.assertTrue(all("vehicle_classes" in item and "alternative_routes" in item for item in routes))
            self.assertTrue(any(item["active_flow_count"] > 0 for item in routes))
        finally:
            route_file.unlink(missing_ok=True)

    def test_effect_profiles_are_explicit_and_validated_configuration(self):
        profiles = operator_profiles()
        self.assertIn("weather", profiles)
        self.assertTrue(profiles["weather"])
        self.assertGreater(profiles["construction"]["speed_cap_mps"], 0)
        self.assertGreater(profiles["construction"]["travel_time_factor"], 0)
        self.assertGreater(profiles["vip"]["travel_time_factor"], 0)
        payload = OptimizationRequestPayload()
        self.assertEqual(payload.intersections, {})
        self.assertIsNone(payload.event.total_vehicles)
        self.assertFalse(payload.constraints.vip)
        self.assertFalse(payload.constraints.construction)

    def test_signal_phase_operation_rejects_unknown_tls_before_mutation(self):
        tls = FakeDomain()
        tls.getIDList = lambda: ["tls-live"]
        traci_fake = controller_module.traci
        with patch.object(traci_fake, "switch"), patch.object(traci_fake, "trafficlight", tls):
            controller = TraCIController(label="signal-metadata-test")
            with self.assertRaisesRegex(ValueError, "Unknown traffic-light ID"):
                controller.set_signal_phase_duration("tls-missing", 0, 20)

    def test_pair_route_failure_rolls_back_first_context(self):
        class FakeRouteController:
            def __init__(self, should_fail=False):
                self.should_fail = should_fail
                self.restored = False
                self.flow_route_edges = set()

            def snapshot_route_operation(self, *_args):
                return {"snapshot": True}

            def apply_route_control(self, *_args):
                if self.should_fail:
                    raise RuntimeError("injected second-context failure")
                return {"readback_confirmed": True, "errors": [], "failed": 0,
                        "blocked": False, "successful": 0}

            def restore_route_operation(self, _snapshot):
                self.restored = True
                return []

        classical, quantum = FakeRouteController(), FakeRouteController(should_fail=True)
        pair = SimulationPair(classical=classical, quantum=quantum)
        with self.assertRaisesRegex(RuntimeError, "both SUMO sessions were restored"):
            pair.apply_route_control("Anna Salai")
        self.assertTrue(classical.restored)
        self.assertTrue(quantum.restored)

    def test_pair_block_preflight_checks_both_scheduled_flow_sets(self):
        class FakeRouteController:
            def __init__(self, conflicts=False):
                mapping = CORRIDOR_MAP["Anna Salai"]
                self.flow_route_edges = (set(mapping.primary_sumo_edges + mapping.reverse_sumo_edges)
                                         if conflicts else set())

            def snapshot_route_operation(self, *_args):
                self.fail("mutation snapshot must not occur on unsafe block")

        pair = SimulationPair(classical=FakeRouteController(),
                              quantum=FakeRouteController(conflicts=True))
        with self.assertRaisesRegex(ValueError, "scheduled flows traverse"):
            pair.apply_route_control("Anna Salai", blocked=True)

    def test_optimizer_intersection_inputs_are_aggregated_from_live_vehicle_edges(self):
        result = live_intersection_loads(
            [{"road_id": "E_WEST_1"}, {"road_id": "E_WEST_1"}, {"road_id": "E_NORTH_1"}],
            {"J_NW", "J_N_CENTRAL"})
        self.assertEqual(result["J1"], 3)
        self.assertEqual(result["J2"], 1)
        self.assertEqual(result["J8"], 0)
        self.assertNotIn("J3", result)

    def test_state_serialization_normalizes_nonfinite_telemetry(self):
        self.assertIsNone(_json_safe(math.nan))
        self.assertEqual(_json_safe({"nested": [math.inf, 1.0]}), {"nested": [None, 1.0]})

    def test_route_rollback_replans_from_live_edge_instead_of_replaying_stale_route(self):
        class VehicleDomain:
            route = ("E_CURRENT", "E_NEXT", "E_DEST")

            @staticmethod
            def getIDList():
                return ["vehicle-1"]

            @staticmethod
            def getRoadID(_vehicle_id):
                return "E_CURRENT"

            @classmethod
            def getRoute(cls, _vehicle_id):
                return cls.route

            @staticmethod
            def getTypeID(_vehicle_id):
                return "car"

            @classmethod
            def setRoute(cls, _vehicle_id, route):
                cls.route = tuple(route)

        class SimulationDomain:
            @staticmethod
            def findRoute(from_edge, to_edge, vType):
                self.assertEqual((from_edge, to_edge, vType), ("E_CURRENT", "E_DEST", "car"))
                return type("Route", (), {"edges": ("E_CURRENT", "E_DETOUR", "E_DEST")})()

        vehicle = VehicleDomain()
        with patch.object(controller_module.traci, "vehicle", vehicle), \
             patch.object(controller_module.traci, "simulation", SimulationDomain):
            error = TraCIController._restore_vehicle_destination(
                "vehicle-1", ("E_OLD_ORIGIN", "E_CURRENT", "E_DEST"))
        self.assertIsNone(error)
        self.assertEqual(vehicle.route, ("E_CURRENT", "E_DETOUR", "E_DEST"))

    def test_route_rollback_skips_transient_internal_lane(self):
        vehicle = FakeDomain()
        vehicle.getIDList = lambda: ["vehicle-1"]
        vehicle.getRoadID = lambda _vehicle_id: ":junction_0"
        vehicle.setRoute = lambda *_args: self.fail("must not mutate an internal-lane vehicle")
        with patch.object(controller_module.traci, "vehicle", vehicle):
            error = TraCIController._restore_vehicle_destination("vehicle-1", ("E_A", "E_B"))
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
