"""Coordinates two actual SUMO/TraCI instances with identical scenario inputs."""

from __future__ import annotations

import uuid
import secrets
import math
import time
from typing import Any, Optional

from .traci_controller import TraCIController
from .scenario_inputs import validate_density, validate_scenario_routes
from .network_routing_service import NetworkRoutingService
from .integration.constraint_engine import ConstraintEngine
from .integration.schemas import DigitalTwinCommand
import traci
from .traci_session import TRACI_SESSION_LOCK


def _diversion_target_count(eligible_count: int, requested_share: float) -> int:
    """Round to the nearest realizable whole vehicle for the requested share."""
    if eligible_count <= 0 or requested_share <= 0:
        return 0
    return min(eligible_count, int(eligible_count * requested_share / 100.0 + 0.5))


def _route_position_is_reroutable(route: tuple[str, ...], route_index: int,
                                  current_edge: str) -> bool:
    """SUMO route mutation is safe only when the vehicle is on its external route edge."""
    return (bool(route) and 0 <= route_index < len(route) and bool(current_edge)
            and not current_edge.startswith(":") and current_edge == route[route_index])


def _ordered_edges_in_route(route: tuple[str, ...], waypoints: tuple[str, ...],
                            start_index: int = 0) -> bool:
    """Return whether required stop edges remain in route order."""
    route_index = max(0, start_index)
    for waypoint in waypoints:
        try:
            route_index = route.index(waypoint, route_index) + 1
        except ValueError:
            return False
    return True


class SimulationPair:
    def __init__(self, classical: Optional[TraCIController] = None,
                 quantum: Optional[TraCIController] = None):
        self.classical = classical or TraCIController(label="classical", simulation_id="")
        self.quantum = quantum or TraCIController(label="quantum", simulation_id="")
        self.scenario_id = ""
        self.settings: dict[str, Any] = {}
        self.run_id = ""
        self.last_optimization_experiment: dict[str, Any] | None = None

    def start(self, scenario: str = "normal_day", density: Optional[dict[str, int]] = None,
              inputs: Optional[dict[str, Any]] = None) -> bool:
        shared_density = validate_density(density, scenario)
        shared_inputs = dict(inputs or {})
        validate_scenario_routes(scenario)
        # Use the same SUMO RNG seed for the baseline and optimized run so their
        # initial conditions are reproducible and comparison noise is reduced.
        shared_inputs.setdefault("seed", secrets.randbelow(2_000_000_000) + 1)
        run_id = f"pair_{uuid.uuid4().hex[:12]}"
        self.classical.simulation_id = f"{run_id}_classical"
        self.quantum.simulation_id = f"{run_id}_quantum"
        self.scenario_id = scenario
        self.settings = {"scenario": scenario, "density": shared_density, **shared_inputs}
        self.run_id = run_id

        first_started = self.classical.start(scenario, shared_density, shared_inputs)
        if not first_started:
            return False
        try:
            second_started = self.quantum.start(scenario, shared_density, shared_inputs)
        except Exception:
            # Keep the pair transactional if the second demand preflight or
            # TraCI startup fails after Classical has already started.
            self.classical.close()
            raise
        if not second_started:
            self.classical.close()
            return False
        return True

    def restart(self) -> bool:
        return self.start(self.scenario_id or "normal_day", self.settings.get("density"),
                          {k: v for k, v in self.settings.items() if k not in {"scenario", "density"}})

    def set_scenario(self, scenario: str) -> bool:
        return self.start(scenario, self.settings.get("density"),
                          {k: v for k, v in self.settings.items() if k not in {"scenario", "density"}})

    def pause(self) -> None:
        self.classical.pause()
        self.quantum.pause()

    def resume(self) -> None:
        self.classical.resume()
        self.quantum.resume()

    def set_speed(self, multiplier: float) -> None:
        self.classical.set_speed(multiplier)
        self.quantum.set_speed(multiplier)

    def close(self) -> None:
        self.classical.close()
        self.quantum.close()

    def stop(self) -> None:
        self.classical.stop()
        self.quantum.stop()

    @property
    def lifecycle_state(self) -> str:
        states = (self.classical.lifecycle_state, self.quantum.lifecycle_state)
        if "ERROR" in states:
            return "ERROR" if states == ("ERROR", "ERROR") else "DEGRADED"
        if states == ("STOPPED", "STOPPED"):
            return "STOPPED"
        if states == ("PAUSED", "PAUSED"):
            return "PAUSED"
        if states == ("RUNNING", "RUNNING"):
            return "RUNNING"
        if "STARTING" in states:
            return "STARTING"
        return "DEGRADED"

    def synchronization(self, time_tolerance_s: float = 1.0) -> dict[str, Any]:
        classical = self.classical.latest_state or {}
        quantum = self.quantum.latest_state or {}
        if not classical or not quantum:
            return {"status": "SYNCING", "synchronized": False, "reason": "waiting_for_both_snapshots"}
        checks = {
            "same_pair": self.classical.simulation_id.startswith(self.run_id)
                         and self.quantum.simulation_id.startswith(self.run_id),
            "same_scenario": classical.get("scenario_id") == quantum.get("scenario_id") == self.scenario_id,
            "same_config": bool(classical.get("config_hash"))
                           and classical.get("config_hash") == quantum.get("config_hash"),
            "same_network": bool(classical.get("network_hash"))
                            and classical.get("network_hash") == quantum.get("network_hash"),
        }
        c_time, q_time = classical.get("time"), quantum.get("time")
        delta = abs(float(c_time) - float(q_time)) if c_time is not None and q_time is not None else math.inf
        checks["time_within_tolerance"] = delta <= time_tolerance_s
        valid = all(checks.values())
        if valid:
            status = "SYNCHRONIZED"
        elif not all(checks[key] for key in ("same_pair", "same_scenario", "same_config", "same_network")):
            status = "DESYNCHRONIZED"
        else:
            status = "SYNCING" if delta <= time_tolerance_s * 2 else "DESYNCHRONIZED"
        return {"status": status, "synchronized": valid, "checks": checks,
                "time_delta_s": None if not math.isfinite(delta) else round(delta, 3),
                "time_tolerance_s": time_tolerance_s,
                "classical_simulation_id": classical.get("simulation_id"),
                "quantum_simulation_id": quantum.get("simulation_id"),
                "scenario_id": self.scenario_id,
                "config_hash": classical.get("config_hash"),
                "network_hash": classical.get("network_hash")}

    def snapshot(self) -> dict[str, Any]:
        return {
            "pair_id": self.run_id or None,
            "scenario_id": self.scenario_id or None,
            "classical": self.classical.latest_state or {},
            "quantum": self.quantum.latest_state or {},
            "connected": self.classical.running and self.quantum.running,
            "lifecycle_state": self.lifecycle_state,
            "synchronization": self.synchronization(),
            "shared_inputs": self.settings,
            "last_optimization_experiment": self.last_optimization_experiment,
        }

    def apply_route_control(self, source: str, alternative: Optional[str] = None,
                            diversion_percent: int = 0, blocked: bool = False) -> dict[str, Any]:
        # Preflight scheduled-flow conflicts in both sessions before the first
        # live mutation, then retain exact state snapshots for pair rollback.
        if blocked:
            from .integration.id_mapper import CORRIDOR_MAP
            mapping = CORRIDOR_MAP.get(source)
            if mapping is None:
                raise ValueError(f"Unknown source corridor: {source}")
            requested_edges = set(mapping.primary_sumo_edges + mapping.reverse_sumo_edges)
            for side, controller in (("classical", self.classical), ("quantum", self.quantum)):
                conflict = sorted(requested_edges & controller.flow_route_edges)
                if conflict:
                    raise ValueError(f"Cannot safely close {source} on {side}: scheduled flows traverse {conflict}; no SUMO mutation was made")
        from .integration.id_mapper import CORRIDOR_MAP
        from .scenario_inputs import operator_profiles
        requested_edges = set(CORRIDOR_MAP[source].primary_sumo_edges + CORRIDOR_MAP[source].reverse_sumo_edges)
        if alternative:
            requested_edges.update(CORRIDOR_MAP[alternative].primary_sumo_edges +
                                   CORRIDOR_MAP[alternative].reverse_sumo_edges)
        for side, active_controller in (("classical", self.classical), ("quantum", self.quantum)):
            # Lightweight controller doubles used by unit tests do not expose
            # a live TraCI session; production controllers always do.
            if not hasattr(active_controller, "traci_session"):
                continue
            with active_controller.traci_session():
                active_routes = set()
                for vehicle_id in traci.vehicle.getIDList():
                    active_routes.update(traci.vehicle.getRoute(vehicle_id))
                if blocked:
                    commands = [DigitalTwinCommand(action_type="operator_edge_control",
                        logical_target=source, canonical_target=source, sumo_target_id=edge_id,
                        parameters={"blocked": True}) for edge_id in requested_edges
                        if edge_id in set(CORRIDOR_MAP[source].primary_sumo_edges +
                                          CORRIDOR_MAP[source].reverse_sumo_edges)]
                else:
                    factor = operator_profiles()["optimization"]["route_priority_multiplier"]
                    commands = [DigitalTwinCommand(action_type="route_diversion",
                        logical_target=source, canonical_target=source, sumo_target_id=edge_id,
                        parameters={"priority_multiplier": factor}) for edge_id in requested_edges]
                validation = ConstraintEngine.validate_batch(commands, {
                    "edge_ids": set(traci.edge.getIDList()),
                    "tls_ids": set(traci.trafficlight.getIDList()),
                    "flow_route_edges": active_controller.flow_route_edges,
                    "active_route_edges": active_routes,
                })
                if not validation["valid"]:
                    reasons = "; ".join(item["message"] for item in validation["errors"])
                    raise ValueError(f"{side} ConstraintEngine preflight rejected request: {reasons}")
        snapshots = {
            "classical": self.classical.snapshot_route_operation(source, alternative),
            "quantum": self.quantum.snapshot_route_operation(source, alternative),
        }
        try:
            result = {
                "classical": self.classical.apply_route_control(source, alternative, diversion_percent, blocked),
                "quantum": self.quantum.apply_route_control(source, alternative, diversion_percent, blocked),
            }
            invalid = [side for side, value in result.items()
                       if (not value.get("readback_confirmed") or value.get("errors")
                           or value.get("failed") or (blocked and not value.get("new_entries_blocked")))]
            if invalid:
                raise RuntimeError(f"Paired route operation failed readback on: {invalid}")
            return result
        except Exception as ex:
            rollback = {side: controller.restore_route_operation(snapshots[side])
                        for side, controller in (("classical", self.classical), ("quantum", self.quantum))}
            rollback_failures = {side: errors for side, errors in rollback.items() if errors}
            suffix = f"; rollback failures: {rollback_failures}" if rollback_failures else "; both SUMO sessions were restored"
            raise RuntimeError(f"Paired route operation rejected: {ex}{suffix}") from ex

    def restore_operator_route_operation(self, original: dict[str, Any]) -> dict[str, Any]:
        """Constraint-check, restore, and read back the saved paired corridor state."""
        from .integration.id_mapper import CORRIDOR_MAP
        source, alternative = original.get("source_corridor_id"), original.get("alternative_corridor_id")
        if source not in CORRIDOR_MAP or alternative not in CORRIDOR_MAP:
            raise ValueError("Saved route-control corridors are no longer available")
        controllers = {"classical": self.classical, "quantum": self.quantum}
        current = {side: controller.snapshot_route_operation(source, alternative)
                   for side, controller in controllers.items()}
        for side, active in controllers.items():
            saved = original.get("snapshots", {}).get(side)
            if not isinstance(saved, dict):
                raise ValueError(f"Saved {side} route-control state is unavailable")
            with active.traci_session():
                context = active.optimizer_constraint_context()
                valid_edges = set(traci.edge.getIDList())
                route_service = NetworkRoutingService(active)
                validated_routes: set[tuple[str, ...]] = set()
                commands = [{"action_type": "route_diversion", "sumo_target_id": edge,
                             "parameters": {"priority_multiplier": 1.0}}
                            for edge in saved.get("costs", {})]
                for lane_id, lane_state in saved.get("lanes", {}).items():
                    try:
                        edge_id = traci.lane.getEdgeID(lane_id)
                        changed = (list(traci.lane.getAllowed(lane_id)) != list(lane_state["allowed"])
                                   or list(traci.lane.getDisallowed(lane_id)) != list(lane_state["disallowed"]))
                    except Exception as exc:
                        raise ValueError(f"{side}: could not preflight saved lane permissions for {lane_id}") from exc
                    if changed:
                        commands.append({"action_type": "operator_edge_control", "sumo_target_id": edge_id,
                            "parameters": {"blocked": bool(lane_state["disallowed"])}})
                for vehicle_id, route in saved.get("vehicles", {}).items():
                    if vehicle_id not in traci.vehicle.getIDList() or not route:
                        continue
                    edge = str(traci.vehicle.getRoadID(vehicle_id))
                    if not edge or edge.startswith(":") or edge == route[-1]:
                        continue
                    vtype = traci.vehicle.getTypeID(vehicle_id)
                    vclass = traci.vehicletype.getVehicleClass(vtype)
                    candidate = tuple(getattr(traci.simulation.findRoute(edge, route[-1], vType=vtype), "edges", ()) or ())
                    if not candidate or candidate[0] != edge or candidate[-1] != route[-1]:
                        raise ValueError(f"{side}: saved destination for vehicle {vehicle_id} is no longer reachable")
                    commands.append({"action_type": "vehicle_reroute", "sumo_target_id": vehicle_id,
                        "parameters": {"vehicle_id": vehicle_id, "route": candidate,
                                       "source_edge": edge, "destination_edge": route[-1]}})
                    if not route_service.validate_route(candidate, vclass, context.get("blocked_edges", ())).get("valid"):
                        raise ValueError(f"{side}: safe restoration route for vehicle {vehicle_id} failed live validation")
                    validated_routes.add(candidate)
                context["route_validator"] = lambda route: tuple(route) in validated_routes
                context.update({"edge_ids": valid_edges, "tls_ids": set(traci.trafficlight.getIDList()),
                                "vehicle_ids": set(traci.vehicle.getIDList())})
                gate = ConstraintEngine.validate_batch(commands, context)
                if not gate["valid"]:
                    raise ValueError(f"{side} ConstraintEngine rejected route-control restoration: "
                                     + "; ".join(error["message"] for error in gate["errors"]))
        failures = {}
        try:
            for side, active in controllers.items():
                errors = active.restore_route_operation(original["snapshots"][side])
                if errors:
                    failures[side] = errors
            if failures:
                raise RuntimeError(str(failures))
            return {"readback_verified": True, "restored": True}
        except Exception as exc:
            rollback = {side: active.restore_route_operation(current[side])
                        for side, active in controllers.items()}
            raise RuntimeError(f"Route-control restore failed: {exc}; recovery rollback: {rollback}") from exc

    def apply_operator_route_operation(self, source: str, alternative: str,
                                       diversion_share: float, block_new_entry: bool = False) -> dict[str, Any]:
        """Plan, validate, apply and verify a live diversion atomically across both SUMO contexts."""
        from .integration.id_mapper import CORRIDOR_MAP
        from .scenario_inputs import operator_profiles
        if source not in CORRIDOR_MAP or alternative not in CORRIDOR_MAP or source == alternative:
            raise ValueError("Choose two different discovered corridors")
        settings = operator_profiles()["route_operations"]
        minimum, maximum, step = (float(settings[key]) for key in
                                  ("diversion_min", "diversion_max", "diversion_step"))
        if isinstance(diversion_share, bool) or not isinstance(diversion_share, (int, float)) or not minimum <= float(diversion_share) <= maximum:
            raise ValueError(f"Diversion share must be between {minimum:g}% and {maximum:g}%")
        if step > 0 and abs((float(diversion_share) - minimum) / step - round((float(diversion_share) - minimum) / step)) > 1e-7:
            raise ValueError(f"Diversion share must use configured {step:g}% steps")
        share = float(diversion_share)
        source_edges = set(CORRIDOR_MAP[source].primary_sumo_edges + CORRIDOR_MAP[source].reverse_sumo_edges)
        alternative_edges = set(CORRIDOR_MAP[alternative].primary_sumo_edges + CORRIDOR_MAP[alternative].reverse_sumo_edges)
        classes = set(settings["eligible_vehicle_classes"])
        controllers = {"classical": self.classical, "quantum": self.quantum}
        plans: dict[str, list[dict[str, Any]]] = {}
        eligible_counts: dict[str, int] = {}
        flow_conflicts: dict[str, list[str]] = {}
        lane_permissions: dict[str, dict[str, dict[str, list[str]]]] = {}
        # Complete preflight and path planning in both contexts before any mutation.
        for side, active_controller in controllers.items():
            service = NetworkRoutingService(active_controller)
            with active_controller.traci_session():
                network_edges = set(traci.edge.getIDList())
                if not source_edges.issubset(network_edges) or not alternative_edges.issubset(network_edges):
                    raise ValueError(f"{side}: selected corridor is not fully present in the running SUMO network")
                lane_permissions[side] = {}
                for edge_id in source_edges:
                    for lane_index in range(traci.edge.getLaneNumber(edge_id)):
                        lane_id = f"{edge_id}_{lane_index}"
                        lane_permissions[side][lane_id] = {"allowed": list(traci.lane.getAllowed(lane_id)),
                                                           "disallowed": list(traci.lane.getDisallowed(lane_id))}
                flow_conflicts[side] = sorted(source_edges & set(active_controller.flow_route_edges))
                ids = list(traci.vehicle.getIDList())
                eligible: list[dict[str, Any]] = []
                for vehicle_id in ids:
                    try:
                        route = tuple(traci.vehicle.getRoute(vehicle_id))
                        if not route:
                            continue
                        index = max(0, min(int(traci.vehicle.getRouteIndex(vehicle_id)), len(route) - 1))
                        current = str(traci.vehicle.getRoadID(vehicle_id))
                        # SUMO cannot change a vehicle's route while it is on an
                        # internal junction edge; wait until it reaches a road.
                        if not _route_position_is_reroutable(route, index, current) or current not in source_edges:
                            continue
                        vtype = traci.vehicle.getTypeID(vehicle_id)
                        vclass = traci.vehicletype.getVehicleClass(vtype)
                        if vclass not in classes:
                            continue
                        try:
                            stop_edges = tuple(dict.fromkeys(
                                traci.lane.getEdgeID(stop[0])
                                for stop in traci.vehicle.getNextStops(vehicle_id)
                                if stop and stop[0]
                            ))
                        except Exception:
                            # If a vehicle has stops but the itinerary cannot be inspected,
                            # keep it out of an operation whose safety cannot be verified.
                            if vclass == "bus":
                                continue
                            stop_edges = ()
                        if any(edge in source_edges and edge != current for edge in stop_edges):
                            continue
                        destination = route[-1]
                        remaining = len(route) - index - 1
                        if remaining <= int(settings["near_destination_remaining_edges"]):
                            continue
                        eligible.append({"vehicle_id": vehicle_id, "current_edge": current,
                                         "destination": destination, "vehicle_type": vtype,
                                         "vehicle_class": vclass, "route": route,
                                         "route_index": index, "stop_edges": stop_edges})
                    except Exception:
                        continue
                context = active_controller.optimizer_constraint_context()
                context.update({"edge_ids": network_edges, "tls_ids": set(traci.trafficlight.getIDList()),
                                "vehicle_ids": set(ids)})
                feasible = []
                for item in eligible:
                    candidate = ()
                    # Route through an actual alternative edge while retaining
                    # the ordered live stop itinerary (including bus stops).
                    for waypoint in sorted(alternative_edges):
                        for insertion in range(len(item["stop_edges"]) + 1):
                            ordered_stops = (item["stop_edges"][:insertion] + (waypoint,)
                                             + item["stop_edges"][insertion:])
                            try:
                                merged = service.get_route(item["current_edge"], item["destination"],
                                                           item["vehicle_type"], ordered_stops)
                            except Exception:
                                continue
                            if (merged and merged[0] == item["current_edge"]
                                    and merged[-1] == item["destination"]
                                    and set(merged) & alternative_edges
                                    and not any(edge in source_edges for edge in merged[1:])):
                                checked = service.validate_route(merged, item["vehicle_class"], context.get("blocked_edges", ()))
                                if checked.get("valid"):
                                    candidate = merged
                                    break
                        if candidate:
                            break
                    if not candidate:
                        continue
                    context["route_validator"] = lambda route, cls=item["vehicle_class"]: service.validate_route(
                        route, cls, context.get("blocked_edges", ())).get("valid", False)
                    gate = ConstraintEngine.validate_batch([{"action_type": "vehicle_reroute",
                        "sumo_target_id": item["vehicle_id"], "parameters": {
                            "vehicle_id": item["vehicle_id"], "route": candidate,
                            "source_edge": item["current_edge"], "destination_edge": item["destination"]}}], context)
                    if not gate["valid"]:
                        continue
                    feasible.append({**item, "new_route": tuple(candidate)})
                eligible_counts[side] = len(feasible)
                # Stable ordering ensures the requested approximate share is reproducible.
                count = _diversion_target_count(len(feasible), share)
                side_plans = feasible[:count]
                if block_new_entry:
                    # ConstraintEngine validates the complete proposed entry block after feasible diversions are known.
                    selected_ids = {p["vehicle_id"] for p in side_plans}
                    active_conflict_edges = set()
                    for vehicle_id in ids:
                        current_route = tuple(traci.vehicle.getRoute(vehicle_id))
                        index = max(0, int(traci.vehicle.getRouteIndex(vehicle_id)))
                        if vehicle_id not in selected_ids:
                            active_conflict_edges.update(set(current_route[index + 1:]) & source_edges)
                    commands = [{"action_type": "operator_entry_block", "sumo_target_id": edge_id,
                        "parameters": {"blocked": True,
                            "scheduled_flow_conflict": edge_id in set(flow_conflicts[side]),
                            "active_route_conflict": edge_id in active_conflict_edges}}
                        for edge_id in source_edges]
                    block_gate = ConstraintEngine.validate_batch(commands, context)
                    if not block_gate["valid"]:
                        reasons = "; ".join(error["message"] for error in block_gate["errors"])
                        raise ValueError(f"New-entry block rejected in {side}: {reasons}")
                plans[side] = side_plans
                if not feasible and not block_new_entry:
                    # A zero-eligible operation is reported explicitly by the API without mutating SUMO.
                    pass
        if not any(eligible_counts.values()) and not block_new_entry:
            raise ValueError("No eligible active vehicles have a safe route through the selected alternative corridor.")
        snapshots = {side: [(item["vehicle_id"], item["route"], item["route_index"]) for item in items]
                     for side, items in plans.items()}
        applied: dict[str, list[str]] = {side: [] for side in controllers}
        try:
            # Freeze both TraCI sessions across final preflight and mutation so
            # a simulation step cannot move a planned vehicle into a junction.
            with TRACI_SESSION_LOCK:
                for side, active_controller in controllers.items():
                    with active_controller.traci_session():
                        live_ids = set(traci.vehicle.getIDList())
                        for plan in plans[side]:
                            vehicle_id = plan["vehicle_id"]
                            if vehicle_id not in live_ids:
                                raise RuntimeError(f"Vehicle {vehicle_id} is no longer active")
                            live_route = tuple(traci.vehicle.getRoute(vehicle_id))
                            live_edge = str(traci.vehicle.getRoadID(vehicle_id))
                            if (live_route != plan["route"] or not live_route
                                    or live_route[-1] != plan["destination"]
                                    or live_edge.startswith(":") or live_edge != plan["current_edge"]):
                                raise RuntimeError(f"Vehicle {vehicle_id} moved or changed route before the paired operation; retry after it leaves the junction")
                for side, active_controller in controllers.items():
                    with active_controller.traci_session():
                        for plan in plans[side]:
                            vehicle_id = plan["vehicle_id"]
                            if vehicle_id not in set(traci.vehicle.getIDList()):
                                raise RuntimeError(f"Vehicle {vehicle_id} is no longer active")
                            current_route = tuple(traci.vehicle.getRoute(vehicle_id))
                            if current_route != plan["route"] or current_route[-1] != plan["destination"]:
                                raise RuntimeError(f"Vehicle {vehicle_id} changed before route mutation")
                            traci.vehicle.setRoute(vehicle_id, list(plan["new_route"]))
                            actual = tuple(traci.vehicle.getRoute(vehicle_id))
                            index = max(0, min(int(traci.vehicle.getRouteIndex(vehicle_id)), max(0, len(actual) - 1)))
                            actual_edge = str(traci.vehicle.getRoadID(vehicle_id))
                            live_valid = NetworkRoutingService(active_controller).validate_route(
                                actual, plan["vehicle_class"]).get("valid", False)
                            if (not actual or actual[-1] != plan["destination"] or not live_valid
                                    or actual_edge.startswith(":") or actual[index] != actual_edge
                                    or not (set(actual[index:]) & alternative_edges)
                                    or any(edge in source_edges for edge in actual[index + 1:])
                                    or not _ordered_edges_in_route(actual, plan["stop_edges"], index)):
                                raise RuntimeError(f"SUMO route readback did not preserve the destination, alternative corridor, stop sequence, and connectivity for {vehicle_id}: got {list(actual)}")
                            applied[side].append(vehicle_id)
                        if block_new_entry:
                            for edge_id in source_edges:
                                for lane_index in range(traci.edge.getLaneNumber(edge_id)):
                                    lane_id = f"{edge_id}_{lane_index}"
                                    vehicle_classes = sorted({traci.vehicletype.getVehicleClass(vtype)
                                        for vtype in traci.vehicletype.getIDList()} - {""})
                                    traci.lane.setDisallowed(lane_id, vehicle_classes)
                                    if not set(vehicle_classes).issubset(set(traci.lane.getDisallowed(lane_id))):
                                        raise RuntimeError(f"SUMO did not verify the new-entry block on {lane_id}")
            return {side: {"eligible_vehicle_count": eligible_counts[side],
                           "rerouted_vehicle_count": len(applied[side]),
                           "actual_diversion_share": (100.0 * len(applied[side]) / eligible_counts[side]) if eligible_counts[side] else 0.0,
                           "vehicles": applied[side], "destination_preserved": True,
                           "readback_verified": True, "block_new_entry": bool(block_new_entry),
                           "flow_conflicts": flow_conflicts[side]} for side in controllers}
        except Exception as exc:
            rollback_errors = {}
            for side, active_controller in controllers.items():
                errors = []
                with active_controller.traci_session():
                    for vehicle_id, old_route, old_index in snapshots[side]:
                        try:
                            if vehicle_id in set(traci.vehicle.getIDList()) and tuple(traci.vehicle.getRoute(vehicle_id)) != old_route:
                                current_edge = str(traci.vehicle.getRoadID(vehicle_id))
                                candidates = [index for index in range(min(old_index, len(old_route)), len(old_route))
                                              if old_route[index] == current_edge]
                                restore_from = candidates[0] if candidates else None
                                restore_route = old_route[restore_from:] if restore_from is not None else ()
                                if not restore_route:
                                    vtype = traci.vehicle.getTypeID(vehicle_id)
                                    restore_route = tuple(traci.simulation.findRoute(
                                        current_edge, old_route[-1], vType=vtype).edges)
                                if not restore_route or restore_route[0] != current_edge:
                                    raise RuntimeError("could not reconstruct the original route from the live edge")
                                traci.vehicle.setRoute(vehicle_id, list(restore_route))
                                if tuple(traci.vehicle.getRoute(vehicle_id))[-1:] != old_route[-1:]:
                                    raise RuntimeError("destination readback mismatch")
                        except Exception as rollback_error:
                            errors.append({"vehicle_id": vehicle_id, "error": str(rollback_error)})
                    if block_new_entry:
                        for lane_id, permission in lane_permissions[side].items():
                            try:
                                traci.lane.setAllowed(lane_id, permission["allowed"])
                                traci.lane.setDisallowed(lane_id, permission["disallowed"])
                            except Exception as rollback_error:
                                errors.append({"lane_id": lane_id, "error": str(rollback_error)})
                if errors:
                    rollback_errors[side] = errors
            suffix = f"; rollback errors: {rollback_errors}" if rollback_errors else "; both contexts were restored"
            raise RuntimeError(f"Route operation failed and was rolled back: {exc}{suffix}") from exc

    def apply_operator_signal_timing(self, tls_id: str, phase: int | None, duration: float,
                                     signal_state: str | None = None) -> dict[str, Any]:
        """Resolve a human RED/GREEN request against live phase states, then mutate both contexts."""
        controllers = {"classical": self.classical, "quantum": self.quantum}
        before: dict[str, dict[str, Any]] = {}
        for side, active_controller in controllers.items():
            with active_controller.traci_session():
                signals = active_controller.network_signals()
                item = next((signal for signal in signals if signal["tls_id"] == tls_id), None)
                if item is None:
                    raise ValueError(f"Signal {tls_id} is not available in {side}")
                resolved_phase = phase
                if signal_state is not None:
                    requested = str(signal_state).upper()
                    if requested not in {"RED", "GREEN"}:
                        raise ValueError("Signal state must be RED or GREEN")
                    def supports(entry: dict[str, Any]) -> bool:
                        state = str(entry.get("state", ""))
                        if not state or any(char in state for char in "yY"):
                            return False
                        if requested == "GREEN":
                            return any(char in state for char in "gG")
                        return all(char in "rR" for char in state)
                    phase_info = next((entry for entry in item["phases"] if supports(entry)), None)
                    if phase_info is None:
                        raise ValueError(f"{requested} signal state control is unsupported by the active program in {side}")
                    resolved_phase = int(phase_info["phase"])
                if not isinstance(resolved_phase, int) or isinstance(resolved_phase, bool):
                    raise ValueError("Select a discovered supported signal state")
                phase_info = next((entry for entry in item["phases"] if entry["phase"] == resolved_phase), None)
                if phase_info is None:
                    raise ValueError(f"Selected phase is not available in {side}")
                context = active_controller.optimizer_constraint_context()
                gate = ConstraintEngine.validate_batch([{"action_type": "signal_state" if signal_state is not None else "signal_timing",
                    "sumo_target_id": tls_id, "parameters": {"phase": resolved_phase,
                        "duration_s": duration, **({"state": str(signal_state).upper()} if signal_state is not None else {})}}], context)
                if not gate["valid"]:
                    raise ValueError("; ".join(error["message"] for error in gate["errors"]))
                before[side] = {"duration": phase_info["duration_s"],
                                "active_duration": item["current_phase_duration_s"],
                                "phase": item["current_phase"],
                                "target_phase": resolved_phase}
        phases = {record["target_phase"] for record in before.values()}
        if len(phases) != 1:
            raise ValueError("Classical and Quantum do not expose the same supported signal state")
        phase = phases.pop()
        applied = []
        signal_reads: dict[str, dict[str, Any]] = {}
        try:
            for side, active_controller in controllers.items():
                result = active_controller.set_signal_phase_duration(tls_id, phase, duration,
                    activate=signal_state is not None,
                    requested_state=str(signal_state).upper() if signal_state is not None else None)
                if not result.get("verified") or abs(float(result["actual_duration_s"]) - float(duration)) > 1e-5:
                    raise RuntimeError(f"{side} signal timing readback did not match")
                signal_reads[side] = result
                applied.append(side)
            def classify(raw: str) -> str:
                return "TRANSITION" if any(char in raw for char in "yY") else "GREEN" if any(char in raw for char in "gG") else "RED"
            actual_states = {side: classify(str(signal_reads[side].get("signal_state", ""))) for side in controllers}
            if signal_state is not None and any(value != str(signal_state).upper() for value in actual_states.values()):
                raise RuntimeError("SUMO signal-state readback did not match the requested RED/GREEN state")
            return {"status": "APPLIED", "tls_id": tls_id, "phase": phase,
                    "signal_state": str(signal_state).upper() if signal_state else None,
                    "requested_duration_s": float(duration), "readback_verified": True,
                    "actual_duration_s": float(duration),
                    "current_state": {side: actual_states[side] for side in controllers},
                    "next_switch": {side: signal_reads[side].get("next_switch") for side in controllers},
                    "contexts": {side: {"previous_duration_s": before[side]["duration"],
                        "actual_duration_s": float(duration), "current_phase": signal_reads[side].get("current_phase"),
                        "signal_state": signal_reads[side].get("signal_state"),
                        "next_switch": signal_reads[side].get("next_switch"), "readback_verified": True}
                        for side in controllers}}
        except Exception as exc:
            rollback_errors = {}
            for side, active_controller in controllers.items():
                try:
                    active_controller.restore_signal_snapshot(tls_id, phase,
                        before[side]["duration"], before[side]["phase"], before[side]["active_duration"])
                except Exception as rollback_error:
                    rollback_errors[side] = str(rollback_error)
            suffix = f"; rollback errors: {rollback_errors}" if rollback_errors else "; both contexts were restored"
            raise RuntimeError(f"Signal timing failed and was rolled back: {exc}{suffix}") from exc

    def apply_edge_closure(self, edge_ids: list[str], closed: bool) -> dict[str, Any]:
        """Safely close/restore arbitrary live edges in both SUMO contexts.

        The entire pair is planned before the first mutation. Active vehicles
        with a future path through a target edge are rerouted from their live
        position when possible. Vehicles already on a target edge and loaded
        future flows are rejected because they cannot be diverted safely.
        """
        if not isinstance(closed, bool):
            raise ValueError("closed must be a boolean")
        if not isinstance(edge_ids, list) or not edge_ids or any(not isinstance(edge, str) or not edge for edge in edge_ids):
            raise ValueError("edges must be a non-empty list of SUMO edge IDs")
        edge_ids = list(dict.fromkeys(edge_ids))
        controllers = {"classical": self.classical, "quantum": self.quantum}
        services = {side: NetworkRoutingService(current) for side, current in controllers.items()}
        plans: dict[str, list[dict[str, Any]]] = {side: [] for side in controllers}
        with TRACI_SESSION_LOCK:
            for side, current in controllers.items():
                if not current.running:
                    return {"success": False, "status": "rejected", "operation": "edge_closure",
                            "side": side, "reason_code": "SUMO_NOT_RUNNING",
                            "message": f"{side} SUMO session is not running", "mutations": 0}
                with current.traci_session():
                    context = current.optimizer_constraint_context()
                    commands = [{"action_type": "operator_edge_control", "sumo_target_id": edge,
                                 "parameters": {"blocked": closed}} for edge in edge_ids]
                    # Loaded future flows are a hard stop. They cannot be
                    # rewritten by the supported runtime APIs in this model.
                    validation_context = dict(context)
                    validation_context["active_route_edges"] = set()
                    validation = ConstraintEngine.validate_batch(commands, validation_context)
                    if not validation["valid"]:
                        return {"success": False, "status": "rejected", "operation": "edge_closure",
                                "side": side, "validation": validation, "mutations": 0}
                    if closed:
                        targets = set(edge_ids)
                        projected_active: set[str] = set()
                        for vehicle_id in sorted(context["vehicle_ids"]):
                            try:
                                route = tuple(traci.vehicle.getRoute(vehicle_id))
                                index = int(traci.vehicle.getRouteIndex(vehicle_id))
                            except Exception:
                                return {"success": False, "status": "rejected", "operation": "edge_closure",
                                        "side": side, "reason_code": "VEHICLE_PREFLIGHT_UNAVAILABLE",
                                        "vehicle_id": vehicle_id,
                                        "message": "Could not read an active vehicle route before closure.",
                                        "mutations": 0}
                            live_route = route[max(0, index):]
                            affected = targets.intersection(live_route)
                            if not affected:
                                projected_active.update(live_route)
                                continue
                            current_edge = live_route[0] if live_route else None
                            if current_edge in targets:
                                return {"success": False, "status": "rejected", "operation": "edge_closure",
                                        "side": side, "reason_code": "VEHICLE_ON_TARGET_EDGE",
                                        "vehicle_id": vehicle_id,
                                        "message": "A vehicle is already on a requested edge; allow it to exit before closure.",
                                        "mutations": 0}
                            plan = services[side].get_alternative_route(vehicle_id, edge_ids)
                            if not plan.get("success"):
                                return {"success": False, "status": "rejected", "operation": "edge_closure",
                                        "side": side, "reason_code": "NO_SAFE_VEHICLE_ALTERNATIVE",
                                        "vehicle_id": vehicle_id, "route_plan": plan, "mutations": 0}
                            plans[side].append(plan)
                            projected_active.update(plan["route"])

                        projected = dict(context)
                        projected["active_route_edges"] = projected_active
                        final_validation = ConstraintEngine.validate_batch(commands, projected)
                        if not final_validation["valid"]:
                            return {"success": False, "status": "rejected", "operation": "edge_closure",
                                    "side": side, "validation": final_validation, "mutations": 0}

            # All flow conflicts, route alternatives, endpoint/access rules,
            # target IDs, and projected closure constraints are known before
            # the first route or permission mutation.
            applied_routes: list[tuple[str, str, tuple[str, ...]]] = []

            def rollback_routes() -> list[dict[str, str]]:
                failures: list[dict[str, str]] = []
                for side, vehicle_id, old_route in reversed(applied_routes):
                    current = controllers[side]
                    try:
                        with current.traci_session():
                            error = current._restore_vehicle_destination(vehicle_id, old_route)
                            if error:
                                raise RuntimeError(error)
                    except Exception as ex:
                        failures.append({"side": side, "vehicle_id": vehicle_id, "error": str(ex)})
                return failures

            reroute_readbacks: list[dict[str, Any]] = []
            if closed:
                for side, current in controllers.items():
                    for plan in plans[side]:
                        vehicle_id = plan["vehicle"]["vehicle_id"]
                        before_route = tuple(plan["vehicle"]["route"])
                        result = services[side].apply_route_plan(plan, edge_ids)
                        reroute_readbacks.append({"side": side, **result})
                        if not result.get("success"):
                            failures = rollback_routes()
                            return {"success": False, "status": "partial" if failures else "rejected",
                                    "operation": "edge_closure", "reason_code": "REROUTE_APPLY_FAILED",
                                    "reroutes": reroute_readbacks, "rollback_errors": failures,
                                    "mutations": len(applied_routes)}
                        applied_routes.append((side, vehicle_id, before_route))

            results = {}
            for side, current in controllers.items():
                result = current.block_edges(edge_ids) if closed else current.restore_edges(edge_ids)
                results[side] = result
                if not result.get("success"):
                    rollback = {}
                    for previous_side, previous_controller in controllers.items():
                        if previous_side not in results or not results[previous_side].get("success"):
                            continue
                        # Reverse the already-committed side to preserve paired
                        # state if either closure or restore readback fails.
                        rollback[previous_side] = (previous_controller.restore_edges(edge_ids) if closed
                                                   else previous_controller.block_edges(edge_ids))
                    rollback_ok = (all(value.get("success") for value in rollback.values())
                                   and all(not value.get("rollback_errors") for value in results.values()))
                    route_rollback_errors = rollback_routes() if closed else []
                    rollback_ok = rollback_ok and not route_rollback_errors
                    return {"success": False, "status": "rejected" if rollback_ok else "partial",
                            "operation": "edge_closure",
                            "reason_code": "PAIR_APPLY_FAILED", "contexts": results,
                            "rollback": rollback, "rollback_errors": route_rollback_errors,
                            "rollback_confirmed": rollback_ok, "reroutes": reroute_readbacks,
                            "mutations": len(applied_routes) + sum(x.get("mutations", 0) for x in results.values())}
            return {"success": True, "status": "success", "operation": "edge_closure" if closed else "edge_restore",
                    "edges": edge_ids, "contexts": results,
                    "reroutes": reroute_readbacks,
                    "mutations": len(applied_routes) + sum(x.get("mutations", 0) for x in results.values())}

    def block_edges(self, edge_ids: list[str]) -> dict[str, Any]:
        return self.apply_edge_closure(edge_ids, True)

    def restore_edges(self, edge_ids: list[str]) -> dict[str, Any]:
        return self.apply_edge_closure(edge_ids, False)

    def reroute_vehicle(self, vehicle_id: str,
                        forbidden_edges: Optional[list[str]] = None) -> dict[str, Any]:
        """Plan on both live instances, then apply/read back as one pair operation."""
        with TRACI_SESSION_LOCK:
            return self._reroute_vehicle_locked(vehicle_id, forbidden_edges)

    def _reroute_vehicle_locked(self, vehicle_id: str,
                                forbidden_edges: Optional[list[str]] = None) -> dict[str, Any]:
        forbidden_edges = forbidden_edges or []
        controllers = {"classical": self.classical, "quantum": self.quantum}
        services = {key: NetworkRoutingService(controller) for key, controller in controllers.items()}
        plans = {key: services[key].get_alternative_route(vehicle_id, forbidden_edges)
                 for key in controllers}
        rejected = [key for key, value in plans.items() if not value.get("success")]
        if rejected:
            return {"success": False, "reason_code": "PAIR_PREFLIGHT_REJECTED",
                    "reason": f"No valid alternative route in: {', '.join(rejected)}",
                    "contexts": plans, "mutations": 0}
        destinations = {value["vehicle"]["destination"] for value in plans.values()}
        if len(destinations) != 1:
            return {"success": False, "reason_code": "PAIR_DESTINATION_MISMATCH",
                    "reason": "The paired vehicles do not share a destination", "contexts": plans,
                    "mutations": 0}

        before = {key: tuple(value["vehicle"]["route"]) for key, value in plans.items()}
        results: dict[str, Any] = {}
        for key in controllers:
            results[key] = services[key].apply_route_plan(plans[key], forbidden_edges)
            if not results[key].get("success"):
                rollback_errors = {}
                for applied_key in controllers:
                    if applied_key not in results or not results[applied_key].get("success"):
                        continue
                    controller = controllers[applied_key]
                    try:
                        with controller.traci_session():
                            if vehicle_id in set(traci.vehicle.getIDList()):
                                traci.vehicle.setRoute(vehicle_id, list(before[applied_key]))
                                if tuple(traci.vehicle.getRoute(vehicle_id)) != before[applied_key]:
                                    raise RuntimeError("route restoration readback mismatch")
                    except Exception as ex:
                        rollback_errors[applied_key] = str(ex)
                return {"success": False, "reason_code": "PAIR_APPLY_ROLLED_BACK",
                        "contexts": results, "rollback_errors": rollback_errors}
        return {"success": True, "vehicle_id": vehicle_id,
                "destination": next(iter(destinations)), "contexts": results}
