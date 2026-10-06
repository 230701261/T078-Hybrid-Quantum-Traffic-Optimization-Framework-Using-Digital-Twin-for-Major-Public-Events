"""Route planning and active-vehicle rerouting against a live SUMO session."""

from __future__ import annotations

from typing import Any, Iterable

import traci
from .integration.constraint_engine import ConstraintEngine


class NetworkRoutingService:
    """Discovers candidate paths from SUMO and verifies before/after state."""

    def __init__(self, controller):
        self.controller = controller

    def inspect_vehicle(self, vehicle_id: str) -> dict[str, Any]:
        with self.controller.traci_session():
            if not self.controller.running:
                raise ValueError("SUMO is not running")
            active = set(traci.vehicle.getIDList())
            if vehicle_id not in active:
                raise ValueError(f"Vehicle {vehicle_id!r} is not active")
            route = tuple(traci.vehicle.getRoute(vehicle_id))
            if not route:
                raise ValueError("Active vehicle has no route")
            index = int(traci.vehicle.getRouteIndex(vehicle_id))
            current_edge = route[min(max(index, 0), len(route) - 1)]
            return {
                "vehicle_id": vehicle_id,
                "current_road_id": str(traci.vehicle.getRoadID(vehicle_id)),
                "current_edge": current_edge,
                "destination": route[-1],
                "route": route,
                "vehicle_type": traci.vehicle.getTypeID(vehicle_id),
                "vehicle_class": traci.vehicletype.getVehicleClass(traci.vehicle.getTypeID(vehicle_id)),
            }

    def route_avoids_edges(self, route: Iterable[str], forbidden_edges: Iterable[str]) -> bool:
        return not (set(route) & set(forbidden_edges))

    def validate_route(self, route: Iterable[str], vehicle_class: str,
                       forbidden_edges: Iterable[str] = ()) -> dict[str, Any]:
        route = tuple(route)
        forbidden = set(forbidden_edges)
        if not route:
            return {"valid": False, "reason": "EMPTY_ROUTE"}
        if len(set(route)) != len(route):
            return {"valid": False, "reason": "CYCLIC_ROUTE"}
        with self.controller.traci_session():
            edge_ids = set(traci.edge.getIDList())
            for edge_id in route:
                if edge_id not in edge_ids:
                    return {"valid": False, "reason": "INVALID_EDGE", "edge_id": edge_id}
                if edge_id in forbidden:
                    return {"valid": False, "reason": "HARD_CONSTRAINT_EDGE", "edge_id": edge_id}
                lane_ids = [f"{edge_id}_{i}" for i in range(traci.edge.getLaneNumber(edge_id))]
                if not any(
                    (not traci.lane.getAllowed(lane_id) or vehicle_class in traci.lane.getAllowed(lane_id))
                    and vehicle_class not in traci.lane.getDisallowed(lane_id)
                    for lane_id in lane_ids
                ):
                    return {"valid": False, "reason": "INACCESSIBLE_EDGE", "edge_id": edge_id}
            for left, right in zip(route, route[1:]):
                if traci.edge.getToJunction(left) != traci.edge.getFromJunction(right):
                    return {"valid": False, "reason": "DISCONNECTED_ROUTE", "edge_pair": [left, right]}
        return {"valid": True, "route": list(route)}

    def get_route(self, source_edge: str, destination_edge: str, vehicle_type: str,
                  via: Iterable[str] = ()) -> tuple[str, ...]:
        with self.controller.traci_session():
            points = [source_edge, *list(via), destination_edge]
            combined: list[str] = []
            for start_edge, end_edge in zip(points, points[1:]):
                result = traci.simulation.findRoute(start_edge, end_edge, vType=vehicle_type)
                segment = list(result.edges)
                if not segment:
                    return ()
                if combined and segment[0] == combined[-1]:
                    segment = segment[1:]
                combined.extend(segment)
        return tuple(combined)

    def get_alternative_route(self, vehicle_id: str,
                              forbidden_edges: Iterable[str] = ()) -> dict[str, Any]:
        vehicle = self.inspect_vehicle(vehicle_id)
        current = tuple(vehicle["route"])
        source = vehicle["current_edge"]
        destination = vehicle["destination"]
        vehicle_type = vehicle["vehicle_type"]
        vehicle_class = vehicle["vehicle_class"]
        forbidden = set(forbidden_edges)
        with self.controller.traci_session():
            discovered_edges = [edge for edge in traci.edge.getIDList()
                                if not edge.startswith(":") and edge not in {source, destination}]
        # Ask SUMO to route through each discovered candidate edge. Candidate
        # paths come from the loaded network; none are stored or invented here.
        candidates: set[tuple[str, ...]] = set()
        for waypoint in discovered_edges:
            try:
                candidate = self.get_route(source, destination, vehicle_type, [waypoint])
            except Exception:
                continue
            if candidate and candidate != current and self.route_avoids_edges(candidate, forbidden):
                checked = self.validate_route(candidate, vehicle_class, forbidden)
                gate = ConstraintEngine.validate_batch([{
                    "action_type": "vehicle_reroute", "sumo_target_id": vehicle_id,
                    "parameters": {"vehicle_id": vehicle_id, "route": candidate,
                                   "source_edge": source, "destination_edge": destination},
                }], {"edge_ids": set(discovered_edges) | {source, destination},
                     "tls_ids": set(), "vehicle_ids": {vehicle_id},
                     "blocked_edges": forbidden,
                     "route_validator": lambda _route: checked["valid"]})
                if checked["valid"] and gate["valid"]:
                    candidates.add(candidate)
        if not candidates:
            return {"success": False, "reason_code": "NO_ALTERNATIVE_ROUTE",
                    "reason": "SUMO found no accessible alternative route preserving the destination",
                    "vehicle": vehicle, "route": None}
        # Prefer the route that introduces the fewest edges; SUMO produced and
        # validated every candidate against the actual current network.
        alternative = min(candidates, key=lambda candidate: (len(candidate), candidate))
        return {"success": True, "vehicle": vehicle, "route": list(alternative)}

    def reroute_vehicle(self, vehicle_id: str,
                        forbidden_edges: Iterable[str] = ()) -> dict[str, Any]:
        plan = self.get_alternative_route(vehicle_id, forbidden_edges)
        if not plan["success"]:
            return plan
        return self.apply_route_plan(plan, forbidden_edges)

    def apply_route_plan(self, plan: dict[str, Any],
                         forbidden_edges: Iterable[str] = ()) -> dict[str, Any]:
        if not plan.get("success"):
            return plan
        vehicle_id = plan["vehicle"]["vehicle_id"]
        before = plan["vehicle"]
        candidate = tuple(plan["route"])
        checked = self.validate_route(candidate, before["vehicle_class"], forbidden_edges)
        if not checked["valid"] or candidate[0] != before["current_edge"] or candidate[-1] != before["destination"]:
            return {"success": False, "reason_code": "ROUTE_PREFLIGHT_FAILED",
                    "reason": checked.get("reason", "Route endpoints do not preserve current position and destination"),
                    "before": before}

        with self.controller.traci_session():
            if vehicle_id not in set(traci.vehicle.getIDList()):
                return {"success": False, "reason_code": "VEHICLE_NO_LONGER_ACTIVE",
                        "before": before}
            live_context = self.controller.optimizer_constraint_context()
            live_context["blocked_edges"] = (set(live_context.get("blocked_edges", ()))
                                               | set(forbidden_edges))
            live_context["route_validator"] = lambda candidate_route: self.validate_route(
                candidate_route, before["vehicle_class"],
                live_context["blocked_edges"]).get("valid", False)
            gate = ConstraintEngine.validate_batch([{
                "action_type": "vehicle_reroute", "sumo_target_id": vehicle_id,
                "parameters": {"vehicle_id": vehicle_id, "route": candidate,
                               "source_edge": before["current_edge"],
                               "destination_edge": before["destination"]},
            }], live_context)
            if not gate["valid"]:
                return {"success": False, "reason_code": "CONSTRAINT_REJECTED",
                        "validation": gate, "before": before}
            # No simulation step can interleave while the controller session
            # lock is held across mutation and readback.
            old_route = tuple(traci.vehicle.getRoute(vehicle_id))
            route_index = int(traci.vehicle.getRouteIndex(vehicle_id))
            live_edge = old_route[min(max(route_index, 0), len(old_route) - 1)] if old_route else None
            if live_edge != before["current_edge"] or not old_route or old_route[-1] != before["destination"]:
                return {"success": False, "reason_code": "VEHICLE_POSITION_CHANGED",
                        "before": before, "live_route": list(old_route),
                        "live_current_edge": live_edge}
            if old_route != tuple(before["route"]):
                return {"success": False, "reason_code": "VEHICLE_ROUTE_CHANGED",
                        "before": before, "live_route": list(old_route)}
            try:
                traci.vehicle.setRoute(vehicle_id, list(candidate))
                actual = tuple(traci.vehicle.getRoute(vehicle_id))
                active = vehicle_id in set(traci.vehicle.getIDList())
                success = actual == candidate and actual != old_route and actual[-1] == before["destination"] and active
                if not success:
                    traci.vehicle.setRoute(vehicle_id, list(old_route))
                return {"success": success,
                        "reason_code": None if success else "ROUTE_READBACK_MISMATCH",
                        "vehicle_id": vehicle_id, "current_edge": before["current_edge"],
                        "destination": before["destination"], "before_route": list(old_route),
                        "after_route": list(actual), "vehicle_active": active,
                        "sumo_running": self.controller.running}
            except Exception as ex:
                try:
                    traci.vehicle.setRoute(vehicle_id, list(old_route))
                except Exception:
                    pass
                return {"success": False, "reason_code": "ROUTE_MUTATION_REJECTED",
                        "reason": str(ex), "vehicle_id": vehicle_id,
                        "before_route": list(old_route), "sumo_running": self.controller.running}

    def find_affected_flows(self, edge_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Report loaded future flows touching targets; do not claim diversion."""
        targets = set(edge_ids)
        path = self.controller.route_variant
        if not path or not path.exists():
            return []
        import xml.etree.ElementTree as ET
        root = ET.parse(path).getroot()
        routes = {node.get("id"): tuple(node.get("edges", "").split())
                  for node in root if node.tag == "route"}
        affected = []
        for node in root:
            if node.tag not in {"flow", "personFlow"}:
                continue
            route_id = node.get("route")
            edges = routes.get(route_id, ())
            hit = sorted(set(edges) & targets)
            if hit:
                affected.append({"id": node.get("id"), "route_id": route_id,
                                 "type": node.get("type"), "edges": list(edges),
                                 "affected_edges": hit, "status": "scheduled_loaded_not_diverted"})
        return affected
