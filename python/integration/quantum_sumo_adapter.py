"""
quantum_sumo_adapter.py

Dedicated adapter layer transforming Quantum Optimization results into
concrete, executable Digital Twin TraCI commands.

Architecture:
  Quantum Result
        ↓
  QuantumResultValidator
        ↓
  QuantumToTrafficMapper
        ↓
  List[DigitalTwinCommand]
        ↓
  TraCIAdapter (Safe execution into SUMO)
"""

from typing import Dict, List, Any, Optional
from ..traci_session import TRACI_SESSION_LOCK
import traci
from .schemas import OptimizationResponse, DigitalTwinCommand
from .constraint_engine import ConstraintEngine
from ..scenario_inputs import operator_profiles
from .id_mapper import (
    map_quantum_corridor_to_sumo,
    map_quantum_junction_to_sumo_tls,
    get_canonical_corridor_id,
    get_canonical_junction_id
)

class QuantumResultValidator:
    """Validates structure, bitstring, constraints, and bounds of quantum optimization output."""

    @staticmethod
    def validate(response: OptimizationResponse) -> bool:
        if not response.bitstring or len(response.bitstring) != 18:
            raise ValueError(f"Invalid bitstring length ({len(response.bitstring)}). Must be exactly 18 bits.")
        
        if not all(c in "01" for c in response.bitstring):
            raise ValueError(f"Invalid bitstring characters in '{response.bitstring}'. Only 0 and 1 allowed.")

        bits = [int(c) for c in response.bitstring]
        
        # Check standard problem constraints:
        # Bits 0..3: max 2 route diversions
        active_routes = sum(bits[0:4])
        if active_routes > 2:
            print(f"[Validator Warning] Route diversions ({active_routes}) exceeds recommended bound of 2.")

        # Bits 4..13: max 5 signal extensions
        active_signals = sum(bits[4:14])
        if active_signals > 5:
            print(f"[Validator Warning] Signal extensions ({active_signals}) exceeds recommended bound of 5.")

        # Bits 14..17: max 1 restriction
        active_restrictions = sum(bits[14:18])
        if active_restrictions > 1:
            print(f"[Validator Warning] Restrictions ({active_restrictions}) exceeds recommended bound of 1.")

        return True

class QuantumToTrafficMapper:
    """Translates Quantum decision objects into canonical DigitalTwinCommand objects."""

    @staticmethod
    def map_response_to_commands(response: OptimizationResponse) -> List[DigitalTwinCommand]:
        QuantumResultValidator.validate(response)
        profiles = operator_profiles()
        # Validate the complete decision set before constructing any commands.
        # Unknown IDs must reject the result, not silently drop an action.
        for corridor in response.corridors:
            get_canonical_corridor_id(corridor.corridor)
        for signal in response.signal_changes:
            get_canonical_junction_id(signal.junction)
        for restriction in response.restrictions:
            get_canonical_corridor_id(restriction.corridor)

        commands: List[DigitalTwinCommand] = []

        # 1. Map Signal Timing Changes
        for sig in response.signal_changes:
            junction_q = sig.junction
            tls_id = map_quantum_junction_to_sumo_tls(junction_q)
            canonical_id = get_canonical_junction_id(junction_q)
            
            commands.append(
                DigitalTwinCommand(
                    action_type="signal_extension",
                    logical_target=junction_q,
                    canonical_target=canonical_id,
                    sumo_target_id=tls_id,
                    parameters={
                        "old_green": sig.old_green,
                        "new_green": sig.new_green,
                        "extra_green": sig.extra_green,
                        "target_phase_duration": sig.new_green
                    }
                )
            )

        # 2. Map Route Diversions (Capacity / Priority boost on designated corridors)
        for corr in response.corridors:
            if corr.enabled:
                q_name = corr.corridor
                sumo_edges = map_quantum_corridor_to_sumo(q_name)
                canonical_id = get_canonical_corridor_id(q_name)

                for edge_id in sumo_edges:
                    commands.append(
                        DigitalTwinCommand(
                            action_type="route_diversion",
                            logical_target=q_name,
                            canonical_target=canonical_id,
                            sumo_target_id=edge_id,
                            parameters={
                                "rerouted_vehicles": corr.rerouted,
                                "demand": corr.demand,
                                "capacity": corr.capacity,
                                "priority_multiplier": profiles["optimization"]["route_priority_multiplier"]
                            }
                        )
                        )

        # 3. Map Temporary Road Restrictions
        for restr in response.restrictions:
            q_name = restr.corridor
            sumo_edges = map_quantum_corridor_to_sumo(q_name)
            canonical_id = get_canonical_corridor_id(q_name)

            for edge_id in sumo_edges:
                commands.append(
                    DigitalTwinCommand(
                        action_type="temporary_restriction",
                        logical_target=q_name,
                        canonical_target=canonical_id,
                        sumo_target_id=edge_id,
                        parameters={
                            "restriction_type": "speed_reduction",
                            "speed_factor": profiles["optimization"]["restriction_speed_factor"]
                        }
                    )
                    )

        return commands

class TraCIAdapter:
    """Executes DigitalTwinCommand objects directly and safely into the active SUMO TraCI simulation."""

    @staticmethod
    def apply_commands(commands: List[DigitalTwinCommand],
                       validation_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        commands = list(commands)
        configured_effects = operator_profiles()["optimization"]
        applied_count = 0
        failed_count = 0
        details = []
        mutation_snapshots = []
        # A TraCI command and its readback must be atomic relative to the
        # simulation worker. Otherwise a phase can advance between set/read,
        # making a valid command look like a failed application.
        with TRACI_SESSION_LOCK:
          # This is the final shared boundary for both Quantum results and
          # Classical fallback results. Context is read from the active SUMO
          # session before the first write.
          live_context = dict(validation_context or {})
          live_context.setdefault("edge_ids", set(traci.edge.getIDList()))
          live_context.setdefault("tls_ids", set(traci.trafficlight.getIDList()))
          live_context.setdefault("vehicle_ids", set(traci.vehicle.getIDList()))
          validation = ConstraintEngine.validate_batch(commands, live_context)
          if not validation["valid"]:
            return {
                "total_commands": len(commands),
                "applied_count": 0,
                "failed_count": len(commands),
                "success": False,
                "validation": validation,
                "details": [{"action_type": cmd.action_type,
                             "target": cmd.sumo_target_id,
                             "success": False,
                             "errors": [error for error in validation["errors"]
                                        if error["command_index"] == index],
                             "stage": "constraint_validation"}
                            for index, cmd in enumerate(commands)]
            }
          for cmd in commands:
            try:
                if cmd.action_type == "signal_extension":
                    tls_id = cmd.sumo_target_id
                    extra_green = cmd.parameters.get("extra_green", 10.0)
                    current_phase = traci.trafficlight.getPhase(tls_id)
                    current_duration = max(0.0, float(traci.trafficlight.getNextSwitch(tls_id))
                                           - float(traci.simulation.getTime()))
                    mutation_snapshots.append({"kind": "signal", "target": tls_id,
                                               "phase": current_phase, "duration": current_duration})
                    new_duration = min(float(configured_effects["signal_extension_max_s"]),
                                       current_duration + extra_green)
                    traci.trafficlight.setPhaseDuration(tls_id, new_duration)
                    actual_duration = max(0.0, float(traci.trafficlight.getNextSwitch(tls_id))
                                          - float(traci.simulation.getTime()))
                    if abs(actual_duration - new_duration) > 1e-4:
                        raise RuntimeError(f"TLS readback mismatch expected={new_duration} actual={actual_duration}")
                    cmd.applied = True
                    applied_count += 1
                    details.append({"action_type": cmd.action_type, "target": tls_id,
                                    "before": {"phase": current_phase, "duration_s": current_duration},
                                    "after": {"phase": current_phase, "duration_s": actual_duration},
                                    "success": True})

                elif cmd.action_type == "route_diversion":
                    edge_id = cmd.sumo_target_id
                    priority_mult = cmd.parameters.get(
                        "priority_multiplier", configured_effects["route_priority_multiplier"])
                    
                    before = float(traci.edge.getAdaptedTraveltime(edge_id, traci.simulation.getTime()))
                    if before <= 0:
                        before = float(traci.edge.getTraveltime(edge_id))
                    mutation_snapshots.append({"kind": "edge_cost", "target": edge_id, "value": before})
                    target = before * priority_mult
                    traci.edge.adaptTraveltime(edge_id, target)
                    after = float(traci.edge.getAdaptedTraveltime(edge_id, traci.simulation.getTime()))
                    if abs(after - target) > 1e-3:
                        raise RuntimeError(f"edge travel-time readback mismatch expected={target} actual={after}")
                    cmd.applied = True
                    applied_count += 1
                    details.append({"action_type": cmd.action_type, "target": edge_id,
                                    "before": {"travel_time_s": before},
                                    "after": {"travel_time_s": after}, "success": True})

                elif cmd.action_type == "temporary_restriction":
                    edge_id = cmd.sumo_target_id
                    speed_factor = cmd.parameters.get(
                        "speed_factor", configured_effects["restriction_speed_factor"])
                    
                    lane_0 = f"{edge_id}_0"
                    base_speed = float(traci.lane.getMaxSpeed(lane_0))
                    mutation_snapshots.append({"kind": "lane_speed", "target": lane_0, "value": base_speed})
                    target = base_speed * speed_factor
                    traci.lane.setMaxSpeed(lane_0, target)
                    actual = float(traci.lane.getMaxSpeed(lane_0))
                    if abs(actual - target) > 1e-4:
                        raise RuntimeError(f"lane speed readback mismatch expected={target} actual={actual}")
                    cmd.applied = True
                    applied_count += 1
                    details.append({"action_type": cmd.action_type, "target": edge_id,
                                    "before": {"max_speed_mps": base_speed},
                                    "after": {"max_speed_mps": actual}, "success": True})

            except Exception as ex:
                failed_count += 1
                details.append({"action_type": cmd.action_type, "target": cmd.sumo_target_id,
                                "success": False, "error": str(ex)})
                break

          rollback_errors = []
          if failed_count:
            for snapshot in reversed(mutation_snapshots):
                try:
                    if snapshot["kind"] == "signal":
                        traci.trafficlight.setPhaseDuration(snapshot["target"], snapshot["duration"])
                        actual = max(0.0, float(traci.trafficlight.getNextSwitch(snapshot["target"]))
                                     - float(traci.simulation.getTime()))
                        if abs(actual - snapshot["duration"]) > 1e-4:
                            raise RuntimeError("signal duration rollback readback mismatch")
                    elif snapshot["kind"] == "edge_cost":
                        traci.edge.adaptTraveltime(snapshot["target"], snapshot["value"])
                        actual = float(traci.edge.getAdaptedTraveltime(
                            snapshot["target"], traci.simulation.getTime()))
                        if abs(actual - snapshot["value"]) > 1e-3:
                            raise RuntimeError("edge travel-time rollback readback mismatch")
                    elif snapshot["kind"] == "lane_speed":
                        traci.lane.setMaxSpeed(snapshot["target"], snapshot["value"])
                        actual = float(traci.lane.getMaxSpeed(snapshot["target"]))
                        if abs(actual - snapshot["value"]) > 1e-4:
                            raise RuntimeError("lane speed rollback readback mismatch")
                except Exception as ex:
                    rollback_errors.append({"target": snapshot["target"], "error": str(ex)})
            if not rollback_errors:
                applied_count = 0
                for command in commands:
                    command.applied = False
                for detail in details:
                    if detail.get("success"):
                        detail["rolled_back"] = True

        return {
            "total_commands": len(commands),
            "applied_count": applied_count,
            "failed_count": failed_count,
            "success": failed_count == 0 and applied_count == len(commands),
            "status": "success" if failed_count == 0 and applied_count == len(commands)
                     else "partial" if rollback_errors else "rejected",
            "rolled_back": bool(failed_count and not rollback_errors),
            "rollback_errors": rollback_errors,
            "details": details
        }
