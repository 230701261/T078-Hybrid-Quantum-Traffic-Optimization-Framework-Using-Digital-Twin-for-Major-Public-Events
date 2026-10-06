from contextlib import nullcontext
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import traci

from python.network_routing_service import NetworkRoutingService


class RoutingServiceTests(TestCase):
    def setUp(self):
        self.controller = SimpleNamespace(running=True, traci_session=nullcontext,
                                          route_variant=None)
        self.service = NetworkRoutingService(self.controller)
        self.vehicle = {"vehicle_id": "veh-1", "current_road_id": "edge-b",
                        "current_edge": "edge-b", "destination": "edge-d",
                        "route": ("edge-a", "edge-b", "edge-d"),
                        "vehicle_type": "car", "vehicle_class": "passenger"}

    def test_discovers_live_alternative_via_actual_network_edge(self):
        self.service.inspect_vehicle = lambda _vehicle: self.vehicle
        with patch.object(traci.edge, "getIDList", return_value=["edge-a", "edge-b", "edge-d", "edge-x"]), \
             patch.object(traci.simulation, "findRoute", side_effect=lambda source, dest, **_kwargs:
                          SimpleNamespace(edges={("edge-b", "edge-x"): ("edge-b", "edge-x"),
                                                 ("edge-x", "edge-d"): ("edge-x", "edge-d")}
                                          .get((source, dest), ()))):
            self.service.validate_route = lambda route, _vclass, _forbidden=(): {"valid": True, "route": list(route)}
            result = self.service.get_alternative_route("veh-1")
        self.assertTrue(result["success"])
        self.assertEqual(result["route"], ["edge-b", "edge-x", "edge-d"])
        self.assertEqual(result["route"][-1], self.vehicle["destination"])

    def test_no_alternative_returns_explicit_rejection(self):
        self.service.inspect_vehicle = lambda _vehicle: self.vehicle
        with patch.object(traci.edge, "getIDList", return_value=["edge-a", "edge-b", "edge-d"]), \
             patch.object(traci.simulation, "findRoute", return_value=SimpleNamespace(edges=())):
            result = self.service.get_alternative_route("veh-1")
        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], "NO_ALTERNATIVE_ROUTE")

    def test_route_constraint_rejects_forbidden_edge(self):
        self.assertFalse(self.service.route_avoids_edges(
            ["edge-b", "edge-closed", "edge-d"], ["edge-closed"]))

    def test_rejects_cyclic_route(self):
        self.service.controller.traci_session = lambda: nullcontext()
        with patch.object(traci.edge, "getIDList", return_value=["edge-a", "edge-b"]):
            result = self.service.validate_route(["edge-a", "edge-b", "edge-a"], "passenger")
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "CYCLIC_ROUTE")
