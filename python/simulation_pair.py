"""Coordinates two actual SUMO/TraCI instances with identical scenario inputs."""

from __future__ import annotations

import uuid
import secrets
import math
import time
from typing import Any, Optional

from .traci_controller import TraCIController
from .scenario_inputs import validate_density
from .network_routing_service import NetworkRoutingService
from .integration.constraint_engine import ConstraintEngine
from .integration.schemas import DigitalTwinCommand
import traci
from .traci_session import TRACI_SESSION_LOCK


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
        second_started = self.quantum.start(scenario, shared_density, shared_inputs)
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
