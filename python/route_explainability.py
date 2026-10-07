"""Translate real optimizer output into constraint-aware, non-executing advice."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from .integration.id_mapper import CORRIDOR_MAP, JUNCTION_MAP


def load_variable_definitions() -> list[dict[str, str]]:
    quantum_root = Path(__file__).resolve().parent.parent.parent / "quantum_module" / "Quantum-main"
    source = quantum_root / "optimization" / "decision_variables.py"
    if not source.is_file():
        return []
    spec = importlib.util.spec_from_file_location("chepauk_quantum_decision_variables", source)
    if not spec or not spec.loader:
        return []
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return [{"id": item.id, "category": item.category, "target": item.target,
                 "description": item.description} for item in module.generate_variables()]
    except Exception:
        return []


def explain_plan(plan: Any, classical: dict[str, Any] | None, quantum: dict[str, Any] | None,
                 variable_definitions: list[dict[str, str]] | None = None,
                 constraint_checks: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if plan is None:
        return {"status": "WAITING", "message": "No optimizer result is available yet.", "corridors": []}
    plan_data = plan if isinstance(plan, dict) else plan.dict()
    optimizer = str(plan_data.get("optimizer_used") or "Unknown")
    if "failed" in str(plan_data.get("status", "")).lower() or "none" in optimizer.lower():
        return {"status": "UNAVAILABLE", "source": optimizer, "message": "No valid optimizer decision is available.", "corridors": []}
    definitions = variable_definitions if variable_definitions is not None else load_variable_definitions()
    by_variable = {item["id"]: item for item in definitions}
    bits = str(plan_data.get("bitstring") or "")
    decoded = {}
    decoded_variables = []
    if len(bits) == len(definitions) and set(bits) <= {"0", "1"}:
        decoded_variables = [{**item, "selected": bits[index] == "1"}
                             for index, item in enumerate(definitions)]
        decoded = {item["target"]: bits[index] == "1" for index, item in enumerate(definitions)
                   if item["category"] == "route_diversion"}
    returned = {item.get("corridor"): item for item in plan_data.get("corridors", [])}
    corridor_cards = []
    for name, mapping in CORRIDOR_MAP.items():
        action = returned.get(name)
        check = (constraint_checks or {}).get(f"route:{name}",
                 (constraint_checks or {}).get(name, {"valid": None, "errors": []}))
        bit = decoded.get(name)
        if action is None and bit is None:
            corridor_cards.append({"corridor": name, "decision": "NO_ACTION_RETURNED", "status": "NOT_EVALUATED",
                                  "recommendation": "The optimizer returned no corridor decision for this corridor.",
                                  "source": optimizer, "bit": None, "constraints": check,
                                  "classical": _live_metrics(classical, mapping.primary_sumo_edges + mapping.reverse_sumo_edges),
                                  "quantum": _live_metrics(quantum, mapping.primary_sumo_edges + mapping.reverse_sumo_edges)})
            continue
        selected = bool(action.get("enabled")) if action is not None else bool(bit)
        mismatch = bit is not None and action is not None and selected != bit
        status = ("REVIEW_REQUIRED" if mismatch else "CONSTRAINED" if check.get("valid") is False
                  else "NOT_VALIDATED" if selected and check.get("valid") is None
                  else "APPLICABLE" if selected else "NO_ACTION")
        if mismatch:
            recommendation = "Optimizer action and decoded decision bit disagree; no route recommendation is issued."
        elif selected:
            recommendation = (f"The optimizer selected {name}, but live constraint validation is unavailable; recommendation withheld.") if check.get("valid") is None else (
                f"The optimizer selected {name}, but live constraints reject applicability; recommendation withheld.") if check.get("valid") is False else (
                (f"Consider prioritizing {name} for route diversion. Optimizer output estimates "
                 f"{action.get('rerouted', 'N/A')} vehicles rerouted and "
                 f"{action.get('remaining_queue', 'N/A')} queue remaining. Operator decision required.") if action else f"The decoded optimizer decision selects {name}; no action detail was returned. Operator review required.")
        else:
            recommendation = f"No diversion was selected for {name} in this optimizer result."
        corridor_cards.append({"corridor": name, "decision": "DIVERSION_SELECTED" if selected else "NO_DIVERSION",
                               "status": status, "recommendation": recommendation, "source": optimizer,
                               "bit": bit, "optimizer_action": action, "constraints": check,
                               "classical": _live_metrics(classical, mapping.primary_sumo_edges + mapping.reverse_sumo_edges),
                               "quantum": _live_metrics(quantum, mapping.primary_sumo_edges + mapping.reverse_sumo_edges)})
    signals = []
    for action in plan_data.get("signal_changes", []):
        name = action.get("junction")
        mapping = JUNCTION_MAP.get(name)
        tls_id = mapping.sumo_tls_id if mapping else None
        signal_check = (constraint_checks or {}).get(f"signal:{name}", {"valid": None, "errors": []})
        signals.append({"junction": name, "sumo_tls": mapping.sumo_tls_id if mapping else None,
                        "description": mapping.description if mapping else None,
                        "old_green": action.get("old_green"), "new_green": action.get("new_green"),
                        "classical_live": _signal_state(classical, tls_id),
                        "quantum_live": _signal_state(quantum, tls_id),
                        "constraints": signal_check,
                        "status": "CONSTRAINED" if signal_check.get("valid") is False else
                                  "NOT_VALIDATED" if signal_check.get("valid") is None else "RECOMMENDATION_ONLY",
                        "source": optimizer})
    restrictions = []
    for item in plan_data.get("restrictions", []):
        check = (constraint_checks or {}).get(f"restriction:{item.get('corridor')}", {"valid": None, "errors": []})
        restrictions.append({"corridor": item.get("corridor"), "type": item.get("type"),
                             "status": "CONSTRAINED" if check.get("valid") is False else
                                      "NOT_VALIDATED" if check.get("valid") is None else "RECOMMENDATION_ONLY",
                             "constraints": check, "source": optimizer})
    return {"status": "READY", "source": optimizer, "run_id": plan_data.get("run_id"),
            "timestamp": plan_data.get("timestamp") or plan_data.get("created_at"),
            "bitstring": bits, "variable_definitions_available": bool(definitions),
            "decoded_variables": decoded_variables,
            "decoder_note": ("Decision bits decoded from the Quantum module's runtime variable definitions."
                             if decoded_variables else "Variable definitions or bitstring length did not permit decoding; structured optimizer actions are shown as returned."),
            "message": "Recommendations are advisory; only separately verified operations are marked applied.",
            "corridors": corridor_cards, "signals": signals, "restrictions": restrictions,
            "application": plan_data.get("application_result"),
            "applied_to_sumo": bool(plan_data.get("applied_to_sumo", False))}


def _live_metrics(state: dict[str, Any] | None, edges: list[str]) -> dict[str, Any]:
    if not state:
        return {"available": False}
    congestion = state.get("edges_congestion") or {}
    existing = [congestion[edge] for edge in edges if edge in congestion]
    vehicles = [v for v in state.get("vehicles", []) if v.get("road_id") in set(edges)]
    speeds = [float(v.get("speed_kmh")) for v in vehicles if v.get("speed_kmh") is not None]
    occupancies = [float(x.get("occupancy", 0) or 0) for x in existing]
    return {"available": bool(existing), "queue_length_m": round(sum(float(x.get("queue_len", 0) or 0) for x in existing), 1),
            "vehicles": len(vehicles), "mean_occupancy": round(sum(occupancies) / len(occupancies), 3) if occupancies else None,
            "average_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "congestion_levels": sorted({str(x.get("level", "unknown")) for x in existing})}


def _signal_state(state: dict[str, Any] | None, tls_id: str | None) -> dict[str, Any] | None:
    signals = (state or {}).get("traffic_lights", {})
    return signals.get(tls_id) if tls_id and isinstance(signals, dict) else None
