"""Shared live-SUMO hard-constraint gate for mapped optimization actions.

The engine validates the complete command batch before any mutation. Soft
preferences (for example route-cost bias) are not treated as hard closures.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import traci


class ConstraintEngine:
    VEHICLE_CLASSES = ("passenger", "bus", "motorcycle", "rail")

    @classmethod
    def validate_command(cls, command: object, context: dict[str, Any] | None = None,
                         command_index: int = 0) -> list[dict[str, Any]]:
        """Return stable, UI-safe validation errors for one command."""
        context = context or {}
        errors: list[dict[str, Any]] = []

        def add(code: str, message: str) -> None:
            errors.append({"code": code, "message": message, "command_index": command_index})

        try:
            action = command.get("action_type") if isinstance(command, dict) else command.action_type
            target = command.get("sumo_target_id") if isinstance(command, dict) else command.sumo_target_id
            params = command.get("parameters", {}) if isinstance(command, dict) else command.parameters
            edge_ids = context.get("edge_ids")
            tls_ids = context.get("tls_ids")
            if edge_ids is None:
                edge_ids = set(traci.edge.getIDList()) if action in {
                    "route_diversion", "temporary_restriction", "vehicle_reroute", "operator_edge_control"} else set()
            else:
                edge_ids = set(edge_ids)
            if tls_ids is None:
                tls_ids = set(traci.trafficlight.getIDList()) if action in {"signal_extension", "signal_timing"} else set()
            else:
                tls_ids = set(tls_ids)
        except Exception:
            add("LIVE_PREFLIGHT_UNAVAILABLE", "Live SUMO validation data is unavailable")
            return errors
        if not isinstance(action, str) or not isinstance(params, dict):
            add("INVALID_COMMAND", "Command action_type and parameters must be valid")
            return errors
        if not isinstance(target, str):
            add("INVALID_TARGET", "Command SUMO target must be a string identifier")
            return errors

        if action == "signal_extension":
            if target not in tls_ids:
                add("INVALID_TLS", f"Unknown traffic light {target!r}")
            value = params.get("extra_green", 10.0)
            if not cls._positive_finite(value):
                add("INVALID_TIMING", "extra_green must be finite and positive")
        elif action == "signal_timing":
            phase_index = params.get("phase")
            duration = params.get("duration_s")
            if target not in tls_ids:
                add("INVALID_TLS", f"Unknown traffic light {target!r}")
            if isinstance(phase_index, bool) or not isinstance(phase_index, int) or phase_index < 0:
                add("INVALID_TIMING", "phase must be a non-negative integer")
            if not cls._positive_finite(duration):
                add("INVALID_TIMING", "duration_s must be finite and positive")
            if target in tls_ids and isinstance(phase_index, int) and not isinstance(phase_index, bool):
                try:
                    program = traci.trafficlight.getProgram(target)
                    logics = traci.trafficlight.getCompleteRedYellowGreenDefinition(target)
                    logic = next((item for item in logics if str(item.programID) == str(program)), None)
                    if logic is None or phase_index >= len(logic.phases):
                        add("UNSUPPORTED_TLS_PHASE", "Requested phase is absent from the active TLS program")
                    else:
                        phase = logic.phases[phase_index]
                        min_d, max_d = float(phase.minDur), float(phase.maxDur)
                        if min_d > 0 and max_d > 0 and abs(max_d - min_d) <= 1e-6:
                            add("UNSUPPORTED_TLS_TIMING", "Active TLS phase has fixed min/max duration")
                        elif cls._positive_finite(duration) and (
                                (min_d > 0 and duration < min_d) or (max_d > 0 and duration > max_d)):
                            add("INVALID_TIMING", "Requested duration is outside the phase bounds")
                except Exception:
                    add("LIVE_PREFLIGHT_UNAVAILABLE", "Could not inspect the active TLS program")
        elif action == "operator_edge_control":
            if not isinstance(params.get("blocked"), bool):
                add("INVALID_COMMAND", "blocked must be a boolean")
            if target not in edge_ids:
                add("INVALID_EDGE", f"Unknown SUMO edge {target!r}")
            elif params.get("blocked"):
                affected_flows = set(context.get("flow_route_edges", ()))
                affected_active = set(context.get("active_route_edges", ()))
                if target in affected_flows:
                    add("SCHEDULED_FLOW_CONFLICT", f"Loaded future demand uses edge {target!r}")
                if target in affected_active:
                    add("ACTIVE_ROUTE_CONFLICT", f"An active vehicle route uses edge {target!r}")
        elif action in ("route_diversion", "temporary_restriction"):
            if target not in edge_ids:
                add("INVALID_EDGE", f"Unknown SUMO edge {target!r}")
            elif action == "route_diversion":
                if not cls._positive_finite(params.get("priority_multiplier", 0.8)):
                    add("INVALID_PREFERENCE", "priority_multiplier must be finite and positive")
                try:
                    hard_closures = (set(context.get("blocked_edges", ()))
                                     | set(context.get("construction_closures", ()))
                                     | set(context.get("restricted_edges", ())))
                    closed = target in hard_closures or cls.edge_is_closed(target)
                except Exception:
                    add("LIVE_PREFLIGHT_UNAVAILABLE", f"Could not inspect permissions for edge {target!r}")
                    closed = True
                if closed:
                    add("EDGE_CLOSED", f"Edge {target!r} is unavailable under active constraints")
            else:
                if not cls._positive_finite(params.get("speed_factor", 0.6)):
                    add("INVALID_PREFERENCE", "speed_factor must be finite and positive")
                try:
                    hard_closures = (set(context.get("blocked_edges", ()))
                                     | set(context.get("construction_closures", ()))
                                     | set(context.get("restricted_edges", ())))
                    if target in hard_closures or cls.edge_is_closed(target):
                        add("EDGE_CLOSED", f"Edge {target!r} is closed under active constraints")
                except Exception:
                    add("LIVE_PREFLIGHT_UNAVAILABLE", f"Could not inspect permissions for edge {target!r}")
        elif action == "vehicle_reroute":
            vehicle_id = params.get("vehicle_id")
            vehicle_ids = context.get("vehicle_ids")
            if vehicle_ids is None:
                try:
                    vehicle_ids = set(traci.vehicle.getIDList())
                except Exception:
                    vehicle_ids = set()
            if not vehicle_id or vehicle_id not in set(vehicle_ids):
                add("INVALID_VEHICLE", f"Vehicle {vehicle_id!r} is not active")
            route = list(params.get("route", ()))
            hard_closures = (set(context.get("blocked_edges", ()))
                             | set(context.get("construction_closures", ()))
                             | set(context.get("restricted_edges", ())))
            if not route or any(edge not in edge_ids for edge in route):
                add("INVALID_ROUTE", "Candidate route is empty or contains an unknown edge")
            elif any(edge in hard_closures for edge in route):
                add("EDGE_CLOSED", "Candidate route uses a hard-closed edge")
            if route and params.get("source_edge") and route[0] != params["source_edge"]:
                add("INVALID_ROUTE_ORIGIN", "Candidate route does not begin at the vehicle's current edge")
            if route and params.get("destination_edge") and route[-1] != params["destination_edge"]:
                add("INVALID_ROUTE_DESTINATION", "Candidate route changes the requested destination")
            route_validator = context.get("route_validator")
            if not route_validator:
                add("ROUTE_VALIDATOR_REQUIRED", "A live route-access and continuity validator is required")
            elif route and not route_validator(route):
                add("UNREACHABLE_DESTINATION", "Candidate route does not reach its requested destination")
        else:
            add("UNSUPPORTED_COMMAND", f"Unsupported command type {action!r}")

        return errors

    @classmethod
    def validate_batch(cls, commands: Iterable[object],
                       context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate the complete batch before any caller performs mutations."""
        commands = list(commands)
        context = context or {}
        errors: list[dict[str, Any]] = []
        for index, command in enumerate(commands):
            errors.extend(cls.validate_command(command, context, index))

        # Explicit hard/soft conflict preflight. Preferences may not override
        # closure or access constraints.
        closures = (set(context.get("blocked_edges", ()))
                    | set(context.get("construction_closures", ()))
                    | set(context.get("restricted_edges", ())))
        batch_blocks: dict[str, tuple[bool, int]] = {}
        for index, command in enumerate(commands):
            try:
                action = command.get("action_type") if isinstance(command, dict) else command.action_type
                target = command.get("sumo_target_id") if isinstance(command, dict) else command.sumo_target_id
                params = command.get("parameters", {}) if isinstance(command, dict) else command.parameters
                if not isinstance(params, dict):
                    continue
            except Exception:
                continue
            if action == "operator_edge_control" and isinstance(target, str) and isinstance(params.get("blocked"), bool):
                previous = batch_blocks.get(target)
                if previous and previous[0] != params["blocked"]:
                    errors.append({"code": "CONFLICTING_OPERATIONS",
                                   "message": f"Batch requests both closure and restoration for edge {target!r}",
                                   "command_index": index})
                batch_blocks[target] = (params["blocked"], index)
            if (isinstance(target, str) and target in batch_blocks and batch_blocks[target][0]
                    and action in {"route_diversion", "temporary_restriction"}):
                errors.append({"code": "CONFLICTING_OPERATIONS",
                               "message": f"Batch modifies edge {target!r} while closing it",
                               "command_index": index})
            if action == "operator_edge_control" and params.get("blocked") is True and any(
                    (other.get("sumo_target_id") if isinstance(other, dict) else other.sumo_target_id) == target
                    and (other.get("action_type") if isinstance(other, dict) else other.action_type)
                    in {"route_diversion", "temporary_restriction"}
                    for other in commands[:index]):
                errors.append({"code": "CONFLICTING_OPERATIONS",
                               "message": f"Batch modifies edge {target!r} while closing it",
                               "command_index": index})
            raw_preferred = params.get("preferred_edges", ())
            if not isinstance(raw_preferred, (list, tuple, set)) or any(
                    not isinstance(edge, str) for edge in raw_preferred):
                errors.append({"code": "INVALID_PREFERENCE",
                               "message": "preferred_edges must contain SUMO edge IDs",
                               "command_index": index})
                continue
            preferred = set(raw_preferred)
            conflict = preferred & closures
            if conflict:
                errors.append({"code": "CONSTRAINT_CONFLICT",
                               "message": f"Soft route preference conflicts with hard closure: {sorted(conflict)}",
                               "command_index": index})
        return {"valid": not errors, "errors": errors}

    @classmethod
    def validate_commands(cls, commands: Iterable[object]) -> None:
        """Compatibility wrapper for callers expecting an exception."""
        result = cls.validate_batch(commands)
        if not result["valid"]:
            summary = "; ".join(error["message"] for error in result["errors"])
            raise ValueError(summary)

    @classmethod
    def edge_is_closed(cls, edge_id: str) -> bool:
        """True if no lane admits any supported motorized vehicle class."""
        try:
            lanes = traci.edge.getLaneNumber(edge_id)
        except Exception:
            return True
        lane_ids = [f"{edge_id}_{index}" for index in range(lanes)]
        if not lane_ids:
            return True
        try:
            classes = {traci.vehicletype.getVehicleClass(vtype)
                       for vtype in traci.vehicletype.getIDList()}
            classes.discard("")
        except Exception:
            classes = set(cls.VEHICLE_CLASSES)
        if not classes:
            classes = set(cls.VEHICLE_CLASSES)
        for lane_id in lane_ids:
            allowed = set(traci.lane.getAllowed(lane_id))
            disallowed = set(traci.lane.getDisallowed(lane_id))
            for vehicle_class in classes:
                admits = (not allowed or vehicle_class in allowed) and vehicle_class not in disallowed
                if admits:
                    return False
        return True

    @staticmethod
    def _positive_finite(value: object) -> bool:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(float(value)) and float(value) > 0)
