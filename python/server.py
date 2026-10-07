import asyncio
import ipaddress
import json
import math
import copy
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import traci
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Set, Dict, Any, Optional

from .config import UI_DIR, QUANTUM_HEALTH_TIMEOUT_SECONDS
from .traci_controller import TraCIController
from .network_exporter import get_network_geometry
from .integration import OptimizationJobManager, SupabaseRepository
from .integration.constraint_engine import ConstraintEngine
from .integration.id_mapper import CORRIDOR_MAP, JUNCTION_MAP
from .scenario_inputs import (RouteValidationError, default_density, validate_density,
                              validate_scenario_routes, operator_profiles)
from .simulation_pair import SimulationPair
from .comparison import compare_measurements, measured_delta
from .input_validation import validate_message_id
from .operator_expiry import OperatorExpiryManager
from .route_explainability import explain_plan, load_variable_definitions

app = FastAPI(
    title="SUMO TraCI + Quantum Traffic Digital Twin Server",
    version="2.0.0",
    description="Integrated Microscopic Traffic Digital Twin with Quantum QAOA / Classical Optimization & Supabase."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

controller = TraCIController(label="classical", simulation_id="classical")
quantum_controller = TraCIController(label="quantum", simulation_id="quantum")
simulation_pair = SimulationPair(classical=controller, quantum=quantum_controller)
job_manager = OptimizationJobManager(traci_context=quantum_controller.traci_session,
                                     constraint_context=quantum_controller.optimizer_constraint_context)
active_connections: Set[WebSocket] = set()
operation_events = deque(maxlen=500)
optimization_status: Dict[str, Any] = {"stage": "IDLE", "message_id": None, "run_id": None}
latest_explainability: Optional[Dict[str, Any]] = None
operator_expiry: OperatorExpiryManager


def record_event(category: str, message: str, details: Optional[Dict[str, Any]] = None):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sim_time": round(controller.sim_time, 1),
        "scenario_id": simulation_pair.scenario_id,
        "pair_id": simulation_pair.run_id,
        "category": category,
        "message": message,
        "details": details or {},
    }
    operation_events.append(event)
    return event


def clear_current_optimization():
    """A new paired SUMO run has not received actions from the prior run."""
    global latest_explainability
    job_manager.latest_plan = None
    latest_explainability = None


def on_optimization_status(event: Dict[str, Any]):
    optimization_status.clear()
    optimization_status.update(event)
    record_event("optimization", f"Optimization {event['stage']}", event)


job_manager.status_callback = on_optimization_status

# Pre-cached static network vector geometry
CACHED_GEOMETRY = None

def _json_safe(value):
    """Replace non-finite telemetry numbers with JSON null before streaming."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def live_intersection_loads(vehicles, available_tls):
    """Aggregate current vehicle positions on configured approaches for the Q model."""
    vehicles_by_edge: Dict[str, int] = {}
    for vehicle in vehicles or []:
        edge_id = vehicle.get("road_id") or vehicle.get("edge_id")
        if edge_id:
            vehicles_by_edge[edge_id] = vehicles_by_edge.get(edge_id, 0) + 1
    return {
        logical_id: sum(vehicles_by_edge.get(edge_id, 0) for edge_id in mapping.associated_edges)
        for logical_id, mapping in JUNCTION_MAP.items()
        if mapping.sumo_tls_id in available_tls
    }

@app.on_event("startup")
async def startup_event():
    global CACHED_GEOMETRY
    CACHED_GEOMETRY = get_network_geometry()
    # Start two real, isolated SUMO/TraCI runs with identical inputs.
    try:
        validate_scenario_routes("normal_day")
    except RouteValidationError as ex:
        print(f"[ROUTE_INVALID] {ex}")
        raise RuntimeError(f"[ROUTE_INVALID] {ex}") from ex
    print("[SUMO] Starting Classical and Quantum simulation contexts...")
    operator_expiry.start()
    started = simulation_pair.start("normal_day", default_density("normal_day"), {"constraints": {"weather": "clear"}})
    if not started:
        errors = {
            "classical": controller.last_error,
            "quantum": quantum_controller.last_error,
        }
        simulation_pair.close()
        print(f"[SUMO_START_FAILED] Paired simulation startup failed: {errors}")
        raise RuntimeError(f"[SUMO_START_FAILED] Paired simulation startup failed: {errors}")
    record_event("system", "Synchronized baseline and optimized simulations started")
    print("[SUMO] Classical and Quantum TraCI contexts connected.")
    asyncio.create_task(broadcast_simulation_stream())


@app.get("/api/health")
async def health():
    """Stable local identity endpoint used only to detect duplicate launchers."""
    return {"service_id": "traffic-digital-twin", "status": "running",
            "simulation_state": simulation_pair.lifecycle_state}

@app.on_event("shutdown")
async def shutdown_event():
    await operator_expiry.stop()
    simulation_pair.close()

async def broadcast_simulation_stream():
    """Streams live TraCI simulation state to all connected UI clients."""
    while True:
        if active_connections and controller.latest_state:
            state_data = dict(controller.latest_state)
            state_data["simulations"] = {
                "classical": controller.latest_state,
                "quantum": quantum_controller.latest_state,
            }
            state_data["pair"] = simulation_pair.snapshot()
            state_data["events"] = list(operation_events)[-40:]
            state_data["operator_timers"] = operator_expiry.snapshot()
            if latest_explainability:
                state_data["route_explainability"] = latest_explainability

            # Attach latest quantum optimization summary to live state stream
            if job_manager.latest_plan:
                state_data["quantum_optimization"] = job_manager.latest_plan.dict()
            state_data["optimization_status"] = dict(optimization_status)

            msg = json.dumps(_json_safe(state_data), allow_nan=False)
            dead_sockets = set()
            for ws in list(active_connections):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead_sockets.add(ws)
            active_connections.difference_update(dead_sockets)
        await asyncio.sleep(0.1)  # 10 Hz for two real simulation snapshots

# ==============================================================================
# REST ENDPOINTS: NETWORK & SIMULATION CONTROL
# ==============================================================================

@app.get("/api/network/geometry")
async def get_geometry():
    global CACHED_GEOMETRY
    if CACHED_GEOMETRY is None:
        CACHED_GEOMETRY = get_network_geometry()
    return JSONResponse(content=CACHED_GEOMETRY)

@app.get("/api/comparison")
async def get_comparison():
    classical = controller.latest_state or {}
    quantum = quantum_controller.latest_state or {}
    ck = classical.get("kpis", {})
    qk = quantum.get("kpis", {})
    def congested(state):
        return sum(1 for edge in state.get("edges_congestion", {}).values()
                   if edge.get("level") in {"yellow", "red"})
    sync = simulation_pair.synchronization()
    def delta(a, b):
        return measured_delta(a, b, sync["synchronized"])
    def metrics(kpis, state):
        return {
            "simulation_time_s": state.get("time"),
            "active_vehicles": kpis.get("active_vehicles"),
            "active_pedestrians": kpis.get("active_pedestrians"),
            "avg_speed_kmh": kpis.get("avg_speed_kmh"),
            "queue_length_m": kpis.get("total_queue_length_m"),
            "congested_edges": congested(state),
            "avg_completed_travel_time_s": kpis.get("avg_completed_travel_time_s"),
            "total_completed_travel_time_s": kpis.get("total_completed_travel_time_s"),
            "completed_vehicles": kpis.get("completed_vehicles"),
            "avg_waiting_time_s": kpis.get("avg_waiting_time_s"),
            "accumulated_waiting_time_s": kpis.get("accumulated_waiting_time_s"),
            "throughput_vehicles_per_hour": kpis.get("throughput_vehicles_per_hour"),
        }
    classical_metrics, quantum_metrics = metrics(ck, classical), metrics(qk, quantum)
    comparisons = compare_measurements(
        {k: v for k, v in classical_metrics.items() if k != "simulation_time_s"},
        {k: v for k, v in quantum_metrics.items() if k != "simulation_time_s"},
        sync["synchronized"])
    plan_benefits = job_manager.latest_plan.benefits.dict() if job_manager.latest_plan else None
    return JSONResponse(content={
        "pair_id": simulation_pair.run_id,
        "scenario_id": simulation_pair.scenario_id,
        "synchronization": sync,
        "measured": {"basis": "SUMO/TraCI paired snapshot; travel time uses completed vehicle departure-to-arrival durations",
                     "valid": sync["synchronized"], "classical": classical_metrics,
                     "quantum": quantum_metrics, "comparisons": comparisons},
        "model_estimate": plan_benefits,
        # Compatibility aliases are measured only; estimates are never included here.
        "classical": {"avg_speed_kmh": ck.get("avg_speed_kmh"),
                      "avg_travel_time_s": ck.get("avg_completed_travel_time_s"),
                      "queue_m": ck.get("total_queue_length_m"), "congested_roads": congested(classical)},
        "quantum": {"avg_speed_kmh": qk.get("avg_speed_kmh"),
                    "avg_travel_time_s": qk.get("avg_completed_travel_time_s"),
                    "queue_m": qk.get("total_queue_length_m"), "congested_roads": congested(quantum)},
        "delta": {"avg_speed_kmh": delta(ck.get("avg_speed_kmh"), qk.get("avg_speed_kmh")),
                  "avg_travel_time_s": delta(ck.get("avg_completed_travel_time_s"), qk.get("avg_completed_travel_time_s")),
                  "queue_m": delta(ck.get("total_queue_length_m"), qk.get("total_queue_length_m")),
                  "congested_roads": delta(congested(classical), congested(quantum))},
    })

@app.post("/api/control/start")
async def control_start(scenario: str = Query("normal_day", pattern="^(normal_day|event_day)$")):
    state = simulation_pair.lifecycle_state
    if state == "PAUSED":
        simulation_pair.resume()
        success = True
        action = "resumed"
    elif state == "RUNNING":
        success = True
        action = "already_running"
    else:
        density = (simulation_pair.settings.get("density") if simulation_pair.scenario_id == scenario
                   else default_density(scenario))
        inputs = {k: v for k, v in simulation_pair.settings.items() if k not in {"scenario", "density"}}
        if not inputs:
            inputs = {"constraints": {"weather": "clear"}}
        try:
            success = await asyncio.to_thread(simulation_pair.start, scenario, density, inputs)
        except RouteValidationError as ex:
            raise HTTPException(status_code=422, detail={"code": "ROUTE_INVALID", "errors": ex.report.get("errors", [])}) from ex
        action = "started"
        if success:
            clear_current_optimization()
    if success:
        record_event("traffic", f"Simulation pair {action}", {"scenario": scenario})
    startup_errors = {name: {"code": context.last_error_code, "message": context.last_error}
                      for name, context in (("classical", controller), ("quantum", quantum_controller))
                      if context.last_error}
    return {"status": "ok" if success else "error", "code": None if success else "SUMO_START_FAILED",
            "errors": startup_errors, "running": success,
            "lifecycle_state": simulation_pair.lifecycle_state, "action": action,
            "scenario": simulation_pair.scenario_id, "pair_id": simulation_pair.run_id}

@app.post("/api/control/pause")
async def control_pause():
    if not controller.running or not quantum_controller.running:
        raise HTTPException(status_code=409, detail="Cannot pause: simulation pair is not running")
    simulation_pair.pause()
    record_event("traffic", "Both simulations paused")
    return {"status": "ok", "paused": True, "lifecycle_state": simulation_pair.lifecycle_state}

@app.post("/api/control/resume")
async def control_resume():
    if not controller.running or not quantum_controller.running:
        raise HTTPException(status_code=409, detail="Cannot resume a stopped simulation pair; use /api/control/start")
    simulation_pair.resume()
    record_event("traffic", "Both simulations resumed")
    return {"status": "ok", "paused": False, "lifecycle_state": simulation_pair.lifecycle_state}


@app.post("/api/control/stop")
async def control_stop():
    await asyncio.to_thread(simulation_pair.stop)
    record_event("traffic", "Both simulations stopped")
    return {"status": "ok", "lifecycle_state": simulation_pair.lifecycle_state}


@app.post("/api/control/shutdown")
async def control_server_shutdown(request: Request):
    """Gracefully stop this loopback-only server; shutdown hook closes both SUMO sessions."""
    client_host = request.client.host if request.client else ""
    try:
        is_loopback = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        is_loopback = client_host == "testclient"
    if not is_loopback:
        raise HTTPException(status_code=403, detail="Server shutdown is available only from localhost")
    uvicorn_server = getattr(app.state, "uvicorn_server", None)
    if uvicorn_server is None:
        raise HTTPException(status_code=503, detail="This server was not started by python.main")
    uvicorn_server.should_exit = True
    return {"status": "shutdown_requested", "message": "SUMO sessions will close during server shutdown"}

@app.post("/api/control/reset")
async def control_reset():
    success = await asyncio.to_thread(simulation_pair.restart)
    if success:
        clear_current_optimization()
    record_event("traffic", "Both simulations restarted")
    return {"status": "ok" if success else "error", "reset": success,
            "lifecycle_state": simulation_pair.lifecycle_state, "pair_id": simulation_pair.run_id}

@app.post("/api/control/speed")
async def control_speed(multiplier: float = Query(..., ge=0.2, le=20.0)):
    simulation_pair.set_speed(multiplier)
    record_event("traffic", "Simulation speed target changed", {"speed_multiplier": multiplier})
    return {"status": "ok", "speed": multiplier,
            "effective_classical": controller.effective_speed_multiplier,
            "effective_quantum": quantum_controller.effective_speed_multiplier}

@app.post("/api/control/scenario")
async def control_scenario(scenario: str = Query(..., regex="^(normal_day|event_day)$")):
    success = await asyncio.to_thread(simulation_pair.set_scenario, scenario)
    if success:
        clear_current_optimization()
    record_event("traffic", f"Both simulations changed to {scenario}")
    return {"status": "ok", "running": success, "scenario": scenario, "pair_id": simulation_pair.run_id}


@app.get("/api/simulation/config")
async def get_simulation_config(scenario: str = "normal_day"):
    if scenario not in {"normal_day", "event_day"}:
        raise HTTPException(status_code=422, detail="scenario must be normal_day or event_day")
    return {
        "scenario": scenario,
        "density": default_density(scenario),
        "corridors": {name: {"canonical_id": item.canonical_id,
                              "edges": item.primary_sumo_edges + item.reverse_sumo_edges}
                      for name, item in CORRIDOR_MAP.items()},
        "junctions": {name: {"canonical_id": item.canonical_id, "sumo_id": item.sumo_tls_id}
                       for name, item in JUNCTION_MAP.items()},
        "weather_options": sorted(operator_profiles()["weather"]),
        "current_pair_id": simulation_pair.run_id,
        "current_scenario_id": simulation_pair.scenario_id,
    }


@app.get("/api/network/mappings")
async def get_network_mappings():
    return await get_simulation_config(simulation_pair.scenario_id or "normal_day")


@app.get("/api/network/routes")
async def get_network_routes():
    routes = quantum_controller.network_routes()
    corridors = []
    if controller.running and quantum_controller.running:
        live_edges = []
        for active_controller in (controller, quantum_controller):
            with active_controller.traci_session():
                live_edges.append(set(traci.edge.getIDList()))
        traffic_edges = (quantum_controller.latest_state or {}).get("edges_congestion", {})
        for name, item in CORRIDOR_MAP.items():
            edges = list(dict.fromkeys(item.primary_sumo_edges + item.reverse_sumo_edges))
            if not all(set(edges).issubset(edge_set) for edge_set in live_edges):
                continue
            alternatives = []
            for other_name, other in CORRIDOR_MAP.items():
                if other_name == name:
                    continue
                targets = other.primary_sumo_edges + other.reverse_sumo_edges
                connected_both = True
                for active_controller in (controller, quantum_controller):
                    with active_controller.traci_session():
                        vehicle_types = traci.vehicletype.getIDList()
                        candidate_type = next((vtype for vtype in vehicle_types
                            if traci.vehicletype.getVehicleClass(vtype) in {"passenger", "taxi"}), None)
                        connected = False
                        if candidate_type:
                            for source_edge in item.primary_sumo_edges + item.reverse_sumo_edges:
                                for target_edge in targets:
                                    try:
                                        if traci.simulation.findRoute(source_edge, target_edge, vType=candidate_type).edges:
                                            connected = True
                                            break
                                    except Exception:
                                        pass
                                if connected:
                                    break
                        connected_both = connected_both and connected
                if connected_both:
                    alternatives.append(other_name)
            states = [traffic_edges.get(edge, {}).get("level") for edge in edges]
            states = [state for state in states if state]
            severity = {"FREE": 0, "LOW": 0, "MODERATE": 1, "MEDIUM": 1, "HEAVY": 2, "HIGH": 2, "SEVERE": 3}
            traffic_state = max(states, key=lambda value: severity.get(str(value).upper(), -1), default="UNKNOWN")
            corridors.append({"id": name, "display_name": item.description, "canonical_id": item.canonical_id,
                "edges": edges, "eligible_vehicle_edges": edges,
                "entry_edges": [item.primary_sumo_edges[0], item.reverse_sumo_edges[0]],
                "exit_edges": [item.primary_sumo_edges[-1], item.reverse_sumo_edges[-1]],
                "alternatives": alternatives, "traffic_state": traffic_state})
    return {"routes": routes, "corridors": corridors,
            "pair_id": simulation_pair.run_id, "scenario_id": simulation_pair.scenario_id,
            "live": bool(quantum_controller.running)}


@app.get("/api/network/edges")
async def get_network_edges():
    edges = quantum_controller.network_edges()
    return {"edges": edges, "pair_id": simulation_pair.run_id,
            "live": bool(quantum_controller.running)}


@app.get("/api/network/signals")
async def get_network_signals():
    classical = controller.network_signals()
    quantum = quantum_controller.network_signals()
    display_by_tls = {item.sumo_tls_id: item.description for item in JUNCTION_MAP.values()}
    for signal in classical + quantum:
        signal["display_name"] = display_by_tls.get(signal["tls_id"], signal["tls_id"])
    return {"classical": classical, "quantum": quantum,
            "pair_id": simulation_pair.run_id,
            "live": controller.running and quantum_controller.running}


@app.get("/api/traffic/config")
async def get_traffic_config(scenario: str = "normal_day"):
    config = await get_simulation_config(scenario)
    routes = default_density(scenario)
    from .scenario_inputs import MODE_TYPES, config_routes_path
    root = ET.parse(config_routes_path(scenario)).getroot()
    configured_types = {node.get("type") for node in root if node.tag in {"flow", "personFlow"}}
    config["capabilities"] = {mode: {"supported": bool(types & configured_types),
                                      "vehicle_types": sorted(types & configured_types),
                                      "demand_per_hour": routes[mode]}
                              for mode, types in MODE_TYPES.items()}
    config["active_density"] = simulation_pair.settings.get("density") if scenario == simulation_pair.scenario_id else None
    config["speed_multiplier"] = controller.speed_multiplier
    return config


@app.get("/api/constraints")
async def get_constraints():
    inputs = simulation_pair.settings
    return {"pair_id": simulation_pair.run_id, "scenario_id": simulation_pair.scenario_id,
            "constraints": copy.deepcopy(inputs.get("constraints", {})),
            "profiles": operator_profiles(),
            "timers": operator_expiry.snapshot(),
            "readback": {"classical": controller.operator_readback,
                         "quantum": quantum_controller.operator_readback}}


@app.get("/api/operator/state")
async def get_operator_state():
    signal_states = await asyncio.to_thread(_discover_signal_states)
    route_timer = operator_expiry.public_record("route_operation")
    weather_values = [controller.operator_readback.get("weather"), quantum_controller.operator_readback.get("weather")]
    active_weather = weather_values[0].get("input") if len(weather_values) == 2 and all(
        isinstance(value, dict) and value.get("verified") is True for value in weather_values
    ) and weather_values[0].get("input") == weather_values[1].get("input") else None
    construction_values = [controller.operator_readback.get("construction"), quantum_controller.operator_readback.get("construction")]
    active_construction = construction_values[0] if len(construction_values) == 2 and all(
        isinstance(value, dict) and value.get("verified") is True for value in construction_values
    ) and construction_values[0].get("enabled") == construction_values[1].get("enabled") and construction_values[0].get("corridor") == construction_values[1].get("corridor") else None
    return {"pair_id": simulation_pair.run_id, "scenario_id": simulation_pair.scenario_id,
            "lifecycle_state": simulation_pair.lifecycle_state,
            "density": simulation_pair.settings.get("density"),
            "speed_multiplier": controller.speed_multiplier,
            "constraints": copy.deepcopy(simulation_pair.settings.get("constraints", {})),
            "route_modifications": copy.deepcopy(simulation_pair.settings.get("route_modifications", {})),
            "operator_readback": {"classical": controller.operator_readback,
                                  "quantum": quantum_controller.operator_readback},
            "active_controls": {"route_operation": route_timer, "weather": active_weather,
                "construction": active_construction,
                "vip": _paired_profile_state("vip")},
            "signal_states": signal_states,
            "timers": operator_expiry.snapshot(),
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _paired_profile_state(profile_key: str) -> dict[str, Any] | None:
    records = [controller.operator_readback.get(profile_key), quantum_controller.operator_readback.get(profile_key)]
    if len(records) == 2 and all(isinstance(value, dict) and value.get("verified") is True for value in records):
        if (records[0].get("enabled") == records[1].get("enabled")
                and records[0].get("corridor") == records[1].get("corridor")):
            return copy.deepcopy(records[0])
    return None


def _discover_signal_states() -> Dict[str, list[dict[str, Any]]]:
    output: Dict[str, list[dict[str, Any]]] = {}
    for side, active in (("classical", controller), ("quantum", quantum_controller)):
        try:
            output[side] = active.network_signals() if active.running else []
        except Exception:
            output[side] = []
    return output


def _explainability_checks(plan_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    checks: Dict[str, Dict[str, Any]] = {}
    if not quantum_controller.running:
        return {key: {"valid": None, "errors": [{"code": "LIVE_PREFLIGHT_UNAVAILABLE",
                                                   "message": "Quantum SUMO is not running"}]}
                for key in CORRIDOR_MAP}
    try:
        with quantum_controller.traci_session():
            context = quantum_controller.optimizer_constraint_context()
            for action in plan_data.get("corridors", []):
                name = action.get("corridor")
                mapping = CORRIDOR_MAP.get(name)
                if not mapping or not action.get("enabled"):
                    continue
                commands = [{"action_type": "route_diversion", "sumo_target_id": edge,
                             "parameters": {"priority_multiplier": operator_profiles()["optimization"]["route_priority_multiplier"]}}
                            for edge in mapping.primary_sumo_edges + mapping.reverse_sumo_edges]
                validation = ConstraintEngine.validate_batch(commands, context)
                checks[f"route:{name}"] = {"valid": validation["valid"], "errors": validation["errors"]}
            for action in plan_data.get("restrictions", []):
                mapping = CORRIDOR_MAP.get(action.get("corridor"))
                if not mapping:
                    continue
                commands = [{"action_type": "temporary_restriction", "sumo_target_id": edge,
                             "parameters": {"speed_factor": operator_profiles()["optimization"]["restriction_speed_factor"]}}
                            for edge in mapping.primary_sumo_edges + mapping.reverse_sumo_edges]
                validation = ConstraintEngine.validate_batch(commands, context)
                checks[f"restriction:{action['corridor']}"] = {"valid": validation["valid"], "errors": validation["errors"]}
            for action in plan_data.get("signal_changes", []):
                mapping = JUNCTION_MAP.get(action.get("junction"))
                if not mapping:
                    continue
                command = {"action_type": "signal_extension", "sumo_target_id": mapping.sumo_tls_id,
                           "parameters": {"extra_green": action.get("extra_green")}}
                validation = ConstraintEngine.validate_batch([command], context)
                checks[f"signal:{action['junction']}"] = {"valid": validation["valid"], "errors": validation["errors"]}
    except Exception as exc:
        return {key: {"valid": None, "errors": [{"code": "LIVE_PREFLIGHT_UNAVAILABLE", "message": str(exc)}]}
                for key in CORRIDOR_MAP}
    return checks


@app.get("/api/operator/route-explainability")
async def get_route_explainability():
    global latest_explainability
    plan = job_manager.latest_plan
    if plan is None:
        def check_quantum_health():
            url = f"{job_manager.client.service_url.rstrip('/')}/health"
            try:
                with urllib.request.urlopen(url, timeout=QUANTUM_HEALTH_TIMEOUT_SECONDS) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    healthy = response.status == 200 and str(payload.get("status", "")).lower() in {"healthy", "ok", "online"}
                    return "ONLINE" if healthy else "ERROR"
            except Exception:
                return "QUANTUM_OFFLINE"
        health = await asyncio.to_thread(check_quantum_health)
        status = "WAITING" if health == "ONLINE" else health
        message = "No optimizer result is available yet." if status == "WAITING" else (
            "Quantum API is offline; Classical fallback remains available. Run optimization to request a fallback result."
            if status == "QUANTUM_OFFLINE" else "Quantum health endpoint returned an invalid response.")
        return {"status": status, "message": message, "corridors": []}
    plan_data = plan.dict()
    if str(plan_data.get("status", "")).lower() in {"failed", "rejected"}:
        return {"status": "UNAVAILABLE", "source": plan_data.get("optimizer_used"),
                "message": plan_data.get("error") or "Optimizer did not produce a valid decision.", "corridors": []}
    checks = await asyncio.to_thread(_explainability_checks, plan_data)
    latest_explainability = _json_safe(explain_plan(plan_data, controller.latest_state, quantum_controller.latest_state,
                                                     load_variable_definitions(), checks))
    return latest_explainability


async def _apply_constraint_update(constraint_patch: Dict[str, Any], operation: str):
    current = copy.deepcopy(simulation_pair.settings.get("constraints", {}))
    current.update(constraint_patch)
    scenario = simulation_pair.scenario_id or "normal_day"
    density = simulation_pair.settings.get("density") or default_density(scenario)
    body = {"scenario": scenario, "density": density, "constraints": current,
            "signal_timings": simulation_pair.settings.get("signal_timings", {}),
            "route_modifications": simulation_pair.settings.get("route_modifications", {})}
    result = await apply_scenario(body)
    applied = result.get("success") is True
    record_event("traffic" if applied else "system", f"{operation} {'applied' if applied else 'rejected'}",
                 {"requested": constraint_patch, "applied": applied,
                  "readback": result.get("operator_readback"), "reason": result.get("limitations")})
    return {"success": applied, "operation": operation, "requested": constraint_patch,
            "outcome": "success" if applied else "rejected",
            "applied": result.get("constraints"), "readback": result.get("operator_readback"),
            "reason": result.get("limitations") or (None if applied else "TraCI readback did not verify the request"),
            "timestamp": datetime.now(timezone.utc).isoformat(), "pair_id": result.get("pair_id")}


async def _restore_expired_operator(key: str, original: Dict[str, Any], expired: bool = True):
    try:
        if key == "route_operation":
            result = await asyncio.to_thread(_restore_route_operation_snapshots, original)
            if not result.get("readback_verified"):
                raise RuntimeError(result.get("reason") or "Route-control restoration readback failed")
        elif key in {"vip", "construction_profile"}:
            result = await _apply_constraint_update(original, f"{key.upper()}_EXPIRED_RESTORED")
            if not result.get("success"):
                raise RuntimeError(result.get("reason") or "SUMO readback rejected restoration")
        elif key == "construction_closure":
            newly_closed = original.get("newly_closed_edges", [])
            if newly_closed:
                result = await asyncio.to_thread(simulation_pair.restore_edges, newly_closed)
                if not result.get("success"):
                    raise RuntimeError(f"Could not restore construction closure: {result}")
            constraints = original.get("constraints", {})
            if constraints:
                result = await _apply_constraint_update(constraints, "CONSTRUCTION_EXPIRED_RESTORED")
                if not result.get("success"):
                    raise RuntimeError(result.get("reason") or "Constraint restoration failed")
    except Exception as exc:
        event = {"route_operation": "ROUTE_OPERATION_RESTORE_ERROR",
                 "construction_profile": "CONSTRUCTION_RESTORE_ERROR",
                 "construction_closure": "CONSTRUCTION_RESTORE_ERROR"}.get(key, f"{key.upper()}_RESTORATION_ERROR")
        record_event("system", event, {"error": str(exc)})
        raise
    event = ({"route_operation": "ROUTE_OPERATION_EXPIRED",
              "construction_profile": "CONSTRUCTION_EXPIRED",
              "construction_closure": "CONSTRUCTION_EXPIRED"}.get(key, f"{key.upper()}_TIMER_EXPIRED")
             if expired else {"construction_profile": "CONSTRUCTION_CLEARED",
                             "construction_closure": "CONSTRUCTION_CLEARED"}.get(key, f"{key.upper()}_CLEARED"))
    record_event("traffic", event, {"restored": True,
        "source_corridor_id": original.get("source_corridor_id"),
        "alternative_corridor_id": original.get("alternative_corridor_id"),
        "requested_diversion_share": original.get("requested_diversion_share"),
        "block_new_entry": original.get("block_new_entry")})


operator_expiry = OperatorExpiryManager(_restore_expired_operator)


def _duration_seconds(request_body: Dict[str, Any], group: str) -> float:
    configured = operator_profiles()[group]["default_duration_seconds"]
    duration = request_body.get(f"{group}_duration_seconds", request_body.get("duration_seconds", configured))
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or duration <= 0:
        raise HTTPException(status_code=422, detail="duration_seconds must be a positive finite number")
    options = operator_profiles()[group].get("duration_options", [])
    if options and float(duration) not in {float(option) for option in options}:
        raise HTTPException(status_code=422, detail={"reason": "Choose a configured duration.",
            "duration_options": options})
    return float(duration)


def _capture_actual_profile_states() -> Dict[str, Dict[str, Any]]:
    """Read verified prior operator states from both live SUMO contexts."""
    readbacks = {"classical": controller.operator_readback,
                 "quantum": quantum_controller.operator_readback}
    captured = {}
    for profile_key, enabled_field, corridor_field in (
            ("vip", "vip_enabled", "vip_corridor"),
            ("construction", "construction_enabled", "construction_corridor")):
        values = [side.get(profile_key) for side in readbacks.values()]
        if any(not isinstance(value, dict) or value.get("verified") is not True for value in values):
            raise HTTPException(status_code=503, detail={"code": "OPERATOR_STATE_UNAVAILABLE",
                "message": f"Verified {profile_key} state is not available from both SUMO contexts."})
        actual_pairs = [(bool(value.get("enabled")), value.get("corridor") if value.get("enabled") else None)
                        for value in values]
        if actual_pairs[0] != actual_pairs[1]:
            raise HTTPException(status_code=409, detail={"code": "OPERATOR_STATE_DIVERGED",
                "message": f"Classical and Quantum {profile_key} readbacks do not match."})
        captured[profile_key] = {enabled_field: actual_pairs[0][0], corridor_field: actual_pairs[0][1]}
    return captured


@app.post("/api/traffic/configure")
async def configure_traffic(request_body: Dict[str, Any]):
    scenario = request_body.get("scenario", simulation_pair.scenario_id or "normal_day")
    try:
        density = validate_density(request_body.get("density"), scenario)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex
    constraints = request_body.get("constraints") or copy.deepcopy(simulation_pair.settings.get("constraints", {}))
    previous_constraints = _capture_actual_profile_states()
    vip_duration = _duration_seconds(request_body, "vip") if constraints.get("vip_enabled") else None
    construction_duration = _duration_seconds(request_body, "construction") if constraints.get("construction_enabled") else None
    result = await apply_scenario({"scenario": scenario, "density": density,
                                    "constraints": constraints,
                                    "signal_timings": simulation_pair.settings.get("signal_timings", {}),
                                    "route_modifications": simulation_pair.settings.get("route_modifications", {})})
    if result.get("success"):
        result["timers"] = {}
        for key, enabled_field, corridor_field, duration in (
                ("vip", "vip_enabled", "vip_corridor", vip_duration),
                ("construction_profile", "construction_enabled", "construction_corridor", construction_duration)):
            if constraints.get(enabled_field):
                baseline_key = "vip" if key == "vip" else "construction"
                original = operator_expiry.original_state(key) or copy.deepcopy(previous_constraints[baseline_key])
                result["timers"][key] = operator_expiry.activate(key, duration, original)
            else:
                operator_expiry.cancel(key)
    record_event("traffic", "TRAFFIC_CONFIG_UPDATED" if result["success"] else "TRAFFIC_CONFIG_REJECTED", result)
    return {"success": result["success"], "operation": "traffic_configure",
            "outcome": "success" if result["success"] else "partial" if result.get("status") == "partial" else "rejected",
            "requested": {"scenario": scenario, "density": density},
            "applied": {"scenario": result["scenario_id"], "density": result["density"]},
            "readback": result["operator_readback"],
            "timers": result.get("timers", operator_expiry.snapshot()),
            "reason": result.get("limitations") if not result["success"] else None,
            "timestamp": datetime.now(timezone.utc).isoformat(), "pair_id": result["pair_id"]}


@app.post("/api/constraints/weather")
async def configure_weather(request_body: Dict[str, Any]):
    weather = str(request_body.get("weather", "")).lower()
    if weather not in operator_profiles()["weather"]:
        raise HTTPException(status_code=422, detail=f"Unsupported configured weather profile: {weather}")
    result = await _apply_constraint_update({"weather": weather}, "WEATHER_APPLIED")
    if result.get("success"):
        record_event("traffic", "WEATHER_APPLIED", result)
    return result


@app.post("/api/constraints/weather/reset")
async def reset_weather():
    profiles = operator_profiles()["weather"]
    baseline = next((name for name, profile in profiles.items() if profile.get("baseline") is True), None)
    if baseline is None:
        baseline = next((name for name, profile in profiles.items() if profile.get("speed_factor") == 1.0), None)
    if baseline is None:
        raise HTTPException(status_code=409, detail="No baseline weather profile is configured")
    result = await _apply_constraint_update({"weather": baseline}, "WEATHER_CLEARED")
    if result.get("success"):
        record_event("traffic", "WEATHER_CLEARED", {"baseline_profile": baseline,
            "readback_verified": True})
    return result


@app.post("/api/constraints/vip")
async def configure_vip(request_body: Dict[str, Any]):
    enabled = request_body.get("enabled")
    corridor = request_body.get("corridor")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    if enabled and corridor not in CORRIDOR_MAP:
        raise HTTPException(status_code=422, detail="Select a known configured VIP corridor")
    duration = _duration_seconds(request_body, "vip") if enabled else None
    key = "vip"
    prior = operator_expiry.original_state(key)
    actual_before = _capture_actual_profile_states()["vip"]
    patch = {"vip_enabled": enabled, "vip_corridor": corridor if enabled else None}
    result = await _apply_constraint_update(patch, "VIP_UPDATED")
    if result.get("success"):
        if enabled:
            original = prior or actual_before
            timer = operator_expiry.activate(key, duration, original)
            result["timer"] = timer
        else:
            operator_expiry.cancel(key)
    return result


@app.post("/api/constraints/construction")
async def configure_construction(request_body: Dict[str, Any]):
    enabled = request_body.get("enabled")
    corridor = request_body.get("corridor")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    if enabled and corridor not in CORRIDOR_MAP:
        raise HTTPException(status_code=422, detail="Select a known configured construction corridor")
    duration = _configured_duration(request_body.get("duration_seconds", request_body.get("construction_duration_seconds")),
        operator_profiles()["construction"].get("duration_options", []),
        operator_profiles()["construction"].get("default_duration_seconds")) if enabled else None
    key = "construction_profile"
    prior = operator_expiry.original_state(key)
    actual_before = _capture_actual_profile_states()["construction"]
    patch = {"construction_enabled": enabled,
             "construction_corridor": corridor if enabled else None}
    result = await _apply_constraint_update(patch, "CONSTRUCTION_UPDATED")
    if result.get("success"):
        if enabled:
            original = prior or actual_before
            result["timer"] = operator_expiry.activate(key, duration, original)
        else:
            operator_expiry.cancel(key)
        record_event("traffic", "CONSTRUCTION_APPLIED" if enabled else "CONSTRUCTION_CLEARED",
                     {"corridor": corridor if enabled else None, "mode": "profile",
                      "timer": result.get("timer"), "readback_verified": True})
    return result


@app.get("/api/operator/capabilities")
async def operator_capabilities():
    """Describe implemented operator controls without implying live support."""
    signals = await asyncio.to_thread(_discover_signal_states)
    route_discovery = await get_network_routes()
    signal_limits = operator_profiles()["signal_timing"]
    common_signal_states = {}
    for tls in signals["classical"]:
        twin = next((entry for entry in signals["quantum"] if entry["tls_id"] == tls["tls_id"]), None)
        if not twin:
            continue
        states = []
        for name, predicate in (("GREEN", lambda state: any(c in state for c in "gG") and not any(c in state for c in "yY")),
                                ("RED", lambda state: bool(state) and all(c in "rR" for c in state))):
            phases_c = [p for p in tls["phases"] if predicate(str(p.get("state", "")))]
            phases_q = [p for p in twin["phases"] if predicate(str(p.get("state", "")))]
            if phases_c and phases_q and phases_c[0]["phase"] == phases_q[0]["phase"]:
                pc, pq = phases_c[0], phases_q[0]
                fixed_c = pc.get("timing_supported") is not True
                fixed_q = pq.get("timing_supported") is not True
                c_low, c_high = ((pc["duration_s"], pc["duration_s"]) if fixed_c else
                                 (pc["min_duration_s"], pc["max_duration_s"]))
                q_low, q_high = ((pq["duration_s"], pq["duration_s"]) if fixed_q else
                                 (pq["min_duration_s"], pq["max_duration_s"]))
                common_low = max(c_low, q_low, float(signal_limits["minimum_duration_s"]))
                common_high = min(c_high, q_high, float(signal_limits["maximum_duration_s"]))
                if common_low <= common_high and (not fixed_c or not fixed_q or abs(pc["duration_s"] - pq["duration_s"]) <= 1e-6):
                    states.append({"state": name, "phase": pc["phase"],
                        "duration_s": min(common_high, max(common_low, pc["duration_s"])),
                        "min_duration_s": common_low, "max_duration_s": common_high})
        mapping = next((entry for entry in JUNCTION_MAP.values() if entry.sumo_tls_id == tls["tls_id"]), None)
        common_signal_states[tls["tls_id"]] = {"display_name": mapping.description if mapping else "Signalized junction",
            "current_phase": tls["current_phase"], "signal_state": tls["signal_state"],
            "duration_s": tls["current_phase_duration_s"], "next_switch": tls["next_switch"],
            "remaining_seconds": tls.get("seconds_to_switch"),
            "states": states}
    profiles = operator_profiles()
    return {
        "corridors": [{**item, "corridor_id": item["id"]}
                      for item in route_discovery.get("corridors", [])],
        "route_operations": {**operator_profiles()["route_operations"],
            "status": "available", "mode": "live_vehicle_reroute"},
        "weather_profiles": profiles["weather"],
        "signal_controls": common_signal_states,
        "decision_variables": load_variable_definitions(),
        "construction_profiles": {"speed_cost_profile": profiles["construction"],
            "duration_options": profiles["construction"].get("duration_options", []),
            "supported_modes": profiles["construction"].get("supported_modes", [])},
        "route_operation_timing": {"duration_options": profiles["route_operations"].get("duration_options", []),
            "default_duration_seconds": profiles["route_operations"].get("default_duration_seconds")},
        "construction_profile": {"status": "available", "mode": "speed_cost_profile",
                                  "default_duration_seconds": profiles["construction"]["default_duration_seconds"]},
        "construction_closure": {"status": "conditional",
            "default_duration_seconds": operator_profiles()["construction"]["default_duration_seconds"],
            "message": "Live edge closure is accepted only when no active route or loaded future flow uses the edge."},
        "scheduled_flow_diversion": {"status": "unavailable",
            "message": "Loaded route-backed flows cannot be reassigned through the current runtime TraCI interface."},
        "vip_corridor_preference": {"status": "available", "mode": "routing_cost_preference",
                                     "default_duration_seconds": operator_profiles()["vip"]["default_duration_seconds"],
                                     "duration_options": operator_profiles()["vip"].get("duration_options", [])},
        "vip_entity_assignment": {"status": "unavailable",
            "message": "No VIP vehicle type or VIP demand entity is defined in the loaded SUMO demand."},
        "signal_timing": {"status": "dynamic",
            "message": "Only RED/GREEN states discovered in the active programs are offered; fixed durations remain read-only."},
    }


@app.post("/api/operator/route-operation")
async def operator_route_operation(request_body: Dict[str, Any]):
    source = request_body.get("source_corridor_id")
    alternative = request_body.get("alternative_corridor_id")
    share = request_body.get("diversion_share")
    block = request_body.get("block_new_entry", False)
    profile = operator_profiles()["route_operations"]
    current_route_control = operator_expiry.public_record("route_operation")
    if current_route_control and current_route_control.get("status") in {"ACTIVE", "RESTORATION_ERROR"}:
        raise HTTPException(status_code=409, detail="A route control is already active. Clear it and verify restoration before applying another.")
    lo, hi = profile["diversion_min"], profile["diversion_max"]
    if source not in CORRIDOR_MAP or alternative not in CORRIDOR_MAP or source == alternative:
        raise HTTPException(status_code=422, detail="Choose a discovered source and a different connected alternative corridor.")
    if isinstance(block, bool) is False:
        raise HTTPException(status_code=422, detail="Block new entry must be enabled or disabled.")
    if isinstance(share, bool) or not isinstance(share, (int, float)) or not lo <= share <= hi:
        raise HTTPException(status_code=422, detail=f"Diversion share must be between {lo:g}% and {hi:g}%.")
    discovery = await get_network_routes()
    discovered = {item["id"]: item for item in discovery.get("corridors", [])}
    if source not in discovered or alternative not in discovered.get(source, {}).get("alternatives", []):
        raise HTTPException(status_code=422, detail="That corridor pair is not connected in both live simulations.")
    duration = _configured_duration(request_body.get("duration_seconds"),
        profile.get("duration_options", []), profile.get("default_duration_seconds"))
    snapshots = {"classical": controller.snapshot_route_operation(source, alternative),
                 "quantum": quantum_controller.snapshot_route_operation(source, alternative)}
    try:
        result = await asyncio.to_thread(simulation_pair.apply_operator_route_operation,
                                         source, alternative, float(share), block)
    except Exception as ex:
        message = str(ex)
        rolled_back = "rolled back" in message.lower()
        rollback_incomplete = "rollback errors: {" in message.lower()
        event = "ROUTE_OPERATION_ROLLED_BACK" if rolled_back else "ROUTE_OPERATION_REJECTED"
        record_event("system", event, {"request": request_body, "reason": message})
        raise HTTPException(status_code=422, detail={"status": "PARTIAL" if rollback_incomplete else "ROLLED BACK" if rolled_back else "REJECTED",
            "reason": message, "rollback_performed": rolled_back, "readback_verified": False,
            "contexts": {}}) from ex
    status_value = "APPLIED" if all(value["readback_verified"] for value in result.values()) else "PARTIAL"
    payload = {"status": status_value, "source_corridor": source, "alternative_corridor": alternative,
        "requested_diversion_share": float(share),
        "eligible_vehicle_count": {side: value["eligible_vehicle_count"] for side, value in result.items()},
        "rerouted_vehicle_count": {side: value["rerouted_vehicle_count"] for side, value in result.items()},
        "actual_diversion_share": {side: value["actual_diversion_share"] for side, value in result.items()},
        "destination_preserved": all(value["destination_preserved"] for value in result.values()),
        "readback_verified": all(value["readback_verified"] for value in result.values()),
        "rollback_performed": False, "contexts": result,
        "timestamp": datetime.now(timezone.utc).isoformat()}
    original = {"snapshots": snapshots, "source_corridor_id": source,
                "alternative_corridor_id": alternative,
                "requested_diversion_share": float(share), "block_new_entry": bool(block)}
    payload["timer"] = operator_expiry.activate("route_operation", duration, original, {
        "source_corridor_id": source, "alternative_corridor_id": alternative,
        "requested_diversion_share": float(share), "block_new_entry": bool(block)})
    record_event("traffic", "ROUTE_OPERATION_APPLIED", payload)
    return payload


def _configured_duration(value: Any, options: list[Any], default: Any) -> float:
    available = [float(option) for option in options if isinstance(option, (int, float)) and not isinstance(option, bool) and float(option) > 0]
    if not available:
        raise HTTPException(status_code=409, detail="No route-operation durations are configured")
    selected = float(default if value is None else value)
    if selected not in available:
        raise HTTPException(status_code=422, detail={"reason": "Select a configured operation duration.", "duration_options": available})
    return selected


def _restore_route_operation_snapshots(original: Dict[str, Any]) -> Dict[str, Any]:
    return simulation_pair.restore_operator_route_operation(original)


@app.post("/api/operator/route-operation/clear")
async def clear_operator_route_operation():
    original = operator_expiry.original_state("route_operation")
    current = operator_expiry.public_record("route_operation")
    if not original or not current:
        return {"status": "INACTIVE", "readback_verified": True}
    if current.get("status") in {"CLEARED", "EXPIRED"}:
        return {"status": current["status"], "readback_verified": True}
    result = await asyncio.to_thread(_restore_route_operation_snapshots, original)
    if not result.get("readback_verified"):
        record_event("system", "ROUTE_OPERATION_RESTORE_ERROR", result)
        raise HTTPException(status_code=409, detail={"status": "RESTORE ERROR", **result})
    operator_expiry.finish("route_operation", "CLEARED")
    record_event("traffic", "ROUTE_OPERATION_CLEARED", {"readback_verified": True})
    return {"status": "CLEARED", "readback_verified": True}


@app.post("/api/operator/signal-timing")
async def operator_signal_timing(request_body: Dict[str, Any]):
    tls_id, phase, duration = request_body.get("tls_id"), request_body.get("phase"), request_body.get("duration")
    signal_state = request_body.get("signal_state")
    if not isinstance(tls_id, str) or not tls_id:
        raise HTTPException(status_code=422, detail="Select a discovered junction.")
    if signal_state is None and (isinstance(phase, bool) or not isinstance(phase, int)):
        raise HTTPException(status_code=422, detail="Select a discovered signal phase.")
    if signal_state is not None and str(signal_state).upper() not in {"RED", "GREEN"}:
        raise HTTPException(status_code=422, detail="Choose a supported RED or GREEN signal state.")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise HTTPException(status_code=422, detail="Enter a valid signal duration in seconds.")
    try:
        result = await asyncio.to_thread(simulation_pair.apply_operator_signal_timing,
                                         tls_id, phase, float(duration), signal_state)
    except Exception as ex:
        message = str(ex)
        rolled_back = "rolled back" in message.lower()
        rollback_incomplete = "rollback errors: {" in message.lower()
        event = "SIGNAL_TIMING_ROLLED_BACK" if rolled_back else "SIGNAL_TIMING_REJECTED"
        record_event("system", event, {"request": request_body, "reason": message})
        raise HTTPException(status_code=422, detail={"status": "PARTIAL" if rollback_incomplete else "ROLLED BACK" if rolled_back else "REJECTED",
            "tls_id": tls_id, "phase": phase, "requested_duration": duration,
            "reason": message, "rollback_performed": rolled_back, "readback_verified": False}) from ex
    record_event("traffic", "SIGNAL_TIMING_APPLIED", result)
    return result


@app.post("/api/operator/edge-closure")
async def operate_edge_closure(request_body: Dict[str, Any]):
    edges = request_body.get("edges")
    closed = request_body.get("closed", True)
    if not isinstance(edges, list) or not edges or any(not isinstance(edge, str) or not edge for edge in edges):
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "edge_closure", "reason_code": "INVALID_EDGES",
            "message": "edges must be a non-empty list of SUMO edge IDs"})
    if not isinstance(closed, bool):
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "edge_closure", "reason_code": "INVALID_CLOSED_FLAG",
            "message": "closed must be a boolean"})
    try:
        operation = simulation_pair.block_edges if closed else simulation_pair.restore_edges
        result = await asyncio.to_thread(operation, edges)
    except Exception:
        result = {"success": False, "status": "rejected", "operation": "edge_closure",
                  "reason_code": "LIVE_PREFLIGHT_FAILED",
                  "message": "Live SUMO preflight failed; no operation was reported as applied.", "mutations": 0}
    record_event("traffic" if result.get("success") else "system",
                 "EDGE_CLOSED" if result.get("success") and closed else
                 "EDGE_RESTORED" if result.get("success") else "EDGE_CLOSURE_REJECTED", result)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/api/operator/construction")
async def configure_construction_mode(request_body: Dict[str, Any]):
    mode = request_body.get("mode")
    if mode == "profile":
        return await configure_construction({"enabled": request_body.get("enabled"),
                                             "corridor": request_body.get("corridor"),
                                             "duration_seconds": request_body.get("duration_seconds"),
                                             "construction_duration_seconds": request_body.get("construction_duration_seconds")})
    if mode != "closure":
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "construction", "reason_code": "INVALID_MODE",
            "message": "mode must be 'profile' or 'closure'"})
    edges = request_body.get("edges")
    if not edges and request_body.get("corridor") in CORRIDOR_MAP:
        mapping = CORRIDOR_MAP[request_body["corridor"]]
        edges = list(mapping.primary_sumo_edges + mapping.reverse_sumo_edges)
    if not isinstance(edges, list) or not edges:
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "construction_closure", "reason_code": "INVALID_EDGES",
            "message": "closure mode requires a non-empty edges list"})
    enabled = request_body.get("enabled", True)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "construction_closure", "reason_code": "INVALID_ENABLED_FLAG",
            "message": "enabled must be a boolean"})
    duration = _configured_duration(request_body.get("duration_seconds"),
        operator_profiles()["construction"].get("duration_options", []),
        operator_profiles()["construction"].get("default_duration_seconds")) if enabled else None
    timer_key = "construction_closure"
    prior = operator_expiry.original_state(timer_key)
    current_constraints = _capture_actual_profile_states()["construction"]
    before_closed = set(controller.edge_closure_snapshots) | set(quantum_controller.edge_closure_snapshots)
    try:
        operation = simulation_pair.block_edges if enabled else simulation_pair.restore_edges
        result = await asyncio.to_thread(operation, edges)
    except Exception:
        result = {"success": False, "status": "rejected", "operation": "construction_closure",
                  "reason_code": "LIVE_PREFLIGHT_FAILED",
                  "message": "Live SUMO preflight failed; no operation was reported as applied.", "mutations": 0}
    record_event("traffic" if result.get("success") else "system",
                 ("CONSTRUCTION_CLOSED" if enabled else "CONSTRUCTION_CLEARED")
                 if result.get("success") else "CONSTRUCTION_CLOSURE_REJECTED", result)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result)
    if enabled:
        newly_closed = [edge for edge in edges if edge not in before_closed]
        original = copy.deepcopy(prior) if prior else {
            "newly_closed_edges": [],
            "constraints": {"construction_enabled": bool(current_constraints.get("construction_enabled", False)),
                            "construction_corridor": current_constraints.get("construction_corridor")}}
        original["newly_closed_edges"] = sorted(set(original.get("newly_closed_edges", [])) | set(newly_closed))
        result["timer"] = operator_expiry.activate(timer_key, duration, original)
    else:
        remaining_edges = set((prior or {}).get("newly_closed_edges", [])) - set(edges)
        remaining_seconds = operator_expiry.remaining_seconds(timer_key)
        if remaining_edges and remaining_seconds:
            updated_original = copy.deepcopy(prior)
            updated_original["newly_closed_edges"] = sorted(remaining_edges)
            result["timer"] = operator_expiry.activate(timer_key, remaining_seconds, updated_original)
        else:
            operator_expiry.cancel(timer_key)
    if result.get("success") and enabled:
        record_event("traffic", "CONSTRUCTION_APPLIED", {"mode": "closure", "edges": edges,
            "timer": result.get("timer"), "readback_verified": True})
    return result


@app.post("/api/operator/construction/clear")
async def clear_operator_construction():
    keys = ("construction_closure", "construction_profile")
    key = next((candidate for candidate in keys
                if operator_expiry.public_record(candidate)
                and operator_expiry.public_record(candidate).get("status") in {"ACTIVE", "RESTORATION_ERROR"}), None)
    if key is None:
        current = _capture_actual_profile_states()["construction"]
        if not current.get("construction_enabled", False):
            return {"status": "INACTIVE", "readback_verified": True}
        raise HTTPException(status_code=409, detail="No saved active construction operation is available to restore safely.")
    original = operator_expiry.original_state(key)
    try:
        await _restore_expired_operator(key, original, expired=False)
    except Exception as exc:
        raise HTTPException(status_code=409, detail={"status": "RESTORE ERROR", "reason": str(exc),
            "readback_verified": False}) from exc
    operator_expiry.finish(key, "CLEARED")
    return {"status": "CLEARED", "readback_verified": True}


@app.post("/api/operator/vip/assign")
async def assign_vip_entity(request_body: Dict[str, Any]):
    # The loaded route files contain no VIP vehicle type/entity. Keep the
    # existing corridor cost preference, but do not synthesize VIP traffic.
    return JSONResponse(status_code=501, content={"success": False, "status": "unsupported",
        "operation": "vip_assignment", "reason_code": "VIP_ENTITY_NOT_CONFIGURED",
        "message": "VIP assignment unavailable: no VIP entity exists in the current SUMO demand model."})


@app.post("/api/signals/configure")
async def configure_signal(request_body: Dict[str, Any]):
    # Compatibility alias for existing dashboard clients; all writes use the
    # paired preflight/readback/rollback transaction below.
    result = await operator_signal_timing({"tls_id": request_body.get("tls_id"),
        "phase": request_body.get("phase"), "duration": request_body.get("duration_s")})
    result["success"] = result.get("status") == "APPLIED" and result.get("readback_verified", False)
    result["operation"] = "signal_configure"
    result["readback"] = result.get("contexts")
    return result


@app.post("/api/simulation/apply")
async def apply_scenario(request_body: Dict[str, Any]):
    scenario = request_body.get("scenario", "normal_day")
    if scenario not in {"normal_day", "event_day"}:
        raise HTTPException(status_code=422, detail="Unknown scenario")
    try:
        density = validate_density(request_body.get("density"), scenario)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex

    constraints = request_body.get("constraints") or {}
    weather = str(constraints.get("weather", "clear")).lower()
    if weather not in operator_profiles()["weather"]:
        raise HTTPException(status_code=422, detail=f"weather must match a configured profile: {sorted(operator_profiles()['weather'])}")
    constraints["weather"] = weather
    for flag in ("vip_enabled", "construction_enabled"):
        if flag in constraints and not isinstance(constraints[flag], bool):
            raise HTTPException(status_code=422, detail=f"{flag} must be a boolean")
    for flag in ("vip_corridor", "construction_corridor"):
        if constraints.get(flag) and constraints[flag] not in CORRIDOR_MAP:
            raise HTTPException(status_code=422, detail=f"Unknown corridor: {constraints[flag]}")
    if constraints.get("vip_enabled") and not constraints.get("vip_corridor"):
        raise HTTPException(status_code=422, detail="Select a corridor for the VIP route")
    if constraints.get("construction_enabled") and not constraints.get("construction_corridor"):
        raise HTTPException(status_code=422, detail="Select a corridor for construction")
    if (constraints.get("vip_enabled") and constraints.get("construction_enabled")
            and constraints.get("vip_corridor") == constraints.get("construction_corridor")):
        raise HTTPException(status_code=422, detail={"success": False,
            "reason": "VIP preferred corridor conflicts with construction restriction; select a different valid corridor."})

    signal_timings = request_body.get("signal_timings") or {}
    for junction, timing in signal_timings.items():
        if junction not in JUNCTION_MAP:
            raise HTTPException(status_code=422, detail=f"Unknown junction: {junction}")
        if set(timing) != {"red", "green", "yellow"}:
            raise HTTPException(status_code=422, detail=f"{junction} requires red, green, and yellow durations")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in timing.values()):
            raise HTTPException(status_code=422, detail=f"Signal timings for {junction} must be numeric")
        if not (1 <= timing["red"] <= 240 and 1 <= timing["green"] <= 240 and 1 <= timing["yellow"] <= 30):
            raise HTTPException(status_code=422, detail=f"Signal timing is outside allowed bounds for {junction}")

    routes = request_body.get("route_modifications") or {}
    if routes:
        raise HTTPException(status_code=422,
            detail="Live corridor changes must use the paired Route Operations control so both SUMO contexts can be read back and rolled back atomically.")

    shared_inputs = {"constraints": constraints, "signal_timings": signal_timings}
    closure_timer = operator_expiry.public_record("construction_closure")
    if closure_timer:
        operator_expiry.cancel("construction_closure")
        record_event("traffic", "CONSTRUCTION_CLOSURE_TIMER_CANCELED_BY_SIMULATION_RESTART",
                     {"timer": closure_timer, "reason": "A new SUMO context clears transient edge permission snapshots."})
    try:
        started = await asyncio.to_thread(simulation_pair.start, scenario, density, shared_inputs)
    except RouteValidationError as ex:
        raise HTTPException(status_code=422, detail={"code": "ROUTE_INVALID", "errors": ex.report.get("errors", [])}) from ex
    if not started:
        raise HTTPException(status_code=503, detail={"code": "SUMO_START_FAILED",
            "simulations": {name: {"code": context.last_error_code, "message": context.last_error}
                            for name, context in (("classical", controller), ("quantum", quantum_controller))}})
    clear_current_optimization()

    simulation_pair.settings["route_modifications"] = routes
    controller.scenario_inputs["route_modifications"] = routes
    quantum_controller.scenario_inputs["route_modifications"] = routes
    route_result = None

    readbacks = {"classical": controller.operator_readback, "quantum": quantum_controller.operator_readback}
    readback_ok = True
    for side in readbacks.values():
        for key, item in side.items():
            if key == "signals":
                readback_ok = readback_ok and all(signal.get("verified", False)
                                                   for signal in item.values())
            else:
                readback_ok = readback_ok and item.get("verified", False)
    route_ok = route_result is None
    apply_status = "applied" if readback_ok and route_ok else "partial"
    signal_limitations = [
        {"junction": junction, "sumo_id": signal.get("sumo_id"),
         "unsupported_timings": signal.get("unsupported_timings", [])}
        for side in readbacks.values()
        for junction, signal in side.get("signals", {}).items()
        if signal.get("unsupported_timings")
    ]
    record_event("traffic", f"Scenario input application {apply_status}",
                 {"scenario": scenario, "density": density, "constraints": constraints,
                  "signal_timings": signal_timings, "pair_id": simulation_pair.run_id,
                  "readback": readbacks})
    return {"status": apply_status, "success": apply_status == "applied", "pair_id": simulation_pair.run_id,
            "scenario_id": scenario, "density": density, "constraints": constraints,
            "signal_timings": signal_timings, "route_result": route_result,
            "operator_readback": readbacks, "limitations": signal_limitations}


@app.post("/api/simulation/routes")
async def update_routes(request_body: Dict[str, Any]):
    result = await operator_route_operation({"source_corridor_id": request_body.get("source"),
        "alternative_corridor_id": request_body.get("alternative"),
        "diversion_share": request_body.get("diversion_percent", 0),
        "block_new_entry": request_body.get("blocked", False)})
    result["success"] = result.get("status") == "APPLIED" and result.get("readback_verified", False)
    result["operation"] = "ROUTE_OPERATION_APPLIED"
    result["readback"] = result.get("contexts")
    return result


@app.get("/api/operations/events")
async def get_operation_events(limit: int = 100):
    return {"events": list(operation_events)[-max(1, min(limit, 500)):], "pair_id": simulation_pair.run_id}


@app.post("/api/simulation/vehicles/{vehicle_id}/reroute", include_in_schema=False)
async def reroute_active_vehicle(vehicle_id: str, request_body: Optional[Dict[str, Any]] = None):
    """Reroute the matching live vehicle in both simulations transactionally."""
    body = request_body or {}
    forbidden = body.get("blocked_edges", [])
    if not isinstance(forbidden, list) or any(not isinstance(edge, str) for edge in forbidden):
        raise HTTPException(status_code=422, detail="blocked_edges must be a list of SUMO edge IDs")
    try:
        result = await asyncio.to_thread(simulation_pair.reroute_vehicle, vehicle_id, forbidden)
    except Exception as ex:
        record_event("system", "VEHICLE_REROUTE_REJECTED", {"vehicle_id": vehicle_id,
                                                              "reason": str(ex)})
        raise HTTPException(status_code=422, detail={"success": False,
            "reason_code": "REROUTE_PREFLIGHT_FAILED", "reason": str(ex)}) from ex
    record_event("traffic" if result.get("success") else "system",
                 "VEHICLE_REROUTED" if result.get("success") else "VEHICLE_REROUTE_REJECTED",
                 result)
    result["outcome"] = "success" if result.get("success") else "rejected"
    return result


@app.get("/api/system/status")
async def get_system_status():
    def quantum_status():
        service_url = job_manager.client.service_url.rstrip("/")
        health_url = f"{service_url}/health"
        try:
            with urllib.request.urlopen(health_url, timeout=QUANTUM_HEALTH_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
                healthy = (response.status == 200 and
                           str(payload.get("status", "")).lower() in {"healthy", "ok", "online"})
                return {"status": "ONLINE" if healthy else "ERROR",
                        "url": health_url,
                        "decision_variables": payload.get("decision_variables"),
                        "detail": None if healthy else f"Health endpoint returned an unhealthy response: {payload}"}
        except urllib.error.HTTPError as ex:
            return {"status": "ERROR", "url": health_url, "decision_variables": None,
                    "detail": f"Health endpoint returned HTTP {ex.code}"}
        except (TimeoutError, asyncio.TimeoutError):
            return {"status": "STARTING", "url": health_url, "decision_variables": None,
                    "detail": "Quantum health check timed out"}
        except urllib.error.URLError as ex:
            reason = getattr(ex, "reason", ex)
            if isinstance(reason, TimeoutError):
                state = "STARTING"
            elif isinstance(reason, ConnectionRefusedError):
                state = "OFFLINE"
            else:
                state = "ERROR"
            return {"status": state, "url": health_url, "decision_variables": None,
                    "detail": str(reason)}
        except Exception:
            return {"status": "ERROR", "url": health_url, "decision_variables": None,
                    "detail": "Unexpected error while checking Quantum API health"}
    quantum = await asyncio.to_thread(quantum_status)
    repository = job_manager.repo
    pair_state = simulation_pair.lifecycle_state
    digital_twin_state = ("DEGRADED" if pair_state == "DEGRADED" else
                          "ERROR" if pair_state == "ERROR" else pair_state)
    def simulation_status(context):
        state = context.latest_state or {}
        demand = state.get("demand", {})
        return {
            "lifecycle_state": context.lifecycle_state,
            "simulation_time_s": state.get("time", context.sim_time),
            "simulation_started_at": context.simulation_started_at,
            "simulation_window": state.get("simulation_window"),
            "active_vehicles": demand.get("active_vehicle_count", len(state.get("vehicles", []))),
            "pending_vehicles": demand.get("pending_vehicle_count"),
            "departed_vehicles": demand.get("departed_vehicle_count", context.departed_vehicle_count),
            "arrived_vehicles": demand.get("arrived_vehicle_count", context.arrived_vehicle_count),
            "loaded_vehicle_count": demand.get("loaded_vehicle_count", len(context.loaded_vehicle_ids)),
            "loaded_vehicle_ids_sample": demand.get("loaded_vehicle_ids_sample",
                                                     sorted(context.loaded_vehicle_ids)[:20]),
            "active_pedestrians": demand.get("active_pedestrian_count",
                                              len(state.get("pedestrians", []))),
            "vehicle_demand_status": demand.get("vehicle_demand_status"),
            "demand": demand,
            "last_error": context.last_error,
        }

    fallback_module = Path(job_manager.client.quantum_module_dir)
    fallback_available = (fallback_module / "optimization" / "classical_optimizer.py").is_file()
    return {
        "sumo_classical": "CONNECTED" if controller.running and controller.lifecycle_state != "ERROR" else
                          "ERROR" if controller.lifecycle_state == "ERROR" else "DISCONNECTED",
        "sumo_quantum": "CONNECTED" if quantum_controller.running and quantum_controller.lifecycle_state != "ERROR" else
                        "ERROR" if quantum_controller.lifecycle_state == "ERROR" else "DISCONNECTED",
        "digital_twin": digital_twin_state,
        "simulation_state": pair_state,
        "paused": pair_state == "PAUSED",
        "quantum_api": quantum,
        "classical_fallback": "AVAILABLE" if fallback_available else "UNAVAILABLE",
        "simulations": {
            "classical": simulation_status(controller),
            "quantum": simulation_status(quantum_controller),
        },
        "supabase": repository.cloud_status,
        "pair_id": simulation_pair.run_id,
        "scenario_id": simulation_pair.scenario_id,
    }


@app.get("/api/simulation/state")
async def get_simulation_state():
    return JSONResponse(content=_json_safe({"pair": simulation_pair.snapshot(),
            "simulations": {"classical": controller.latest_state, "quantum": quantum_controller.latest_state}}))

# ==============================================================================
# REST ENDPOINTS: QUANTUM OPTIMIZATION & SUPABASE INTEGRATION
# ==============================================================================

@app.post("/api/integration/trigger_optimization")
async def trigger_optimization(request_body: Optional[Dict[str, Any]] = None):
    global latest_explainability
    """
    Triggers a scenario-aware Quantum Optimization run, records the lifecycle
    in Supabase, and applies the resulting decisions directly into SUMO TraCI.
    """
    body = request_body or {}
    message_id = body.get("message_id")
    try:
        validate_message_id(message_id)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex
    scenario_id = body.get("scenario_id") or simulation_pair.scenario_id
    if scenario_id != simulation_pair.scenario_id:
        raise HTTPException(
            status_code=409,
            detail=f"Requested scenario '{scenario_id}' does not match active paired SUMO scenario '{simulation_pair.scenario_id}'. Apply the scenario to both simulations first.",
        )
    # Bind each run to the currently active optimized SUMO instance, never to a
    # stale pair id cached by a browser before the latest scenario was applied.
    sim_id = body.get("simulation_id") or quantum_controller.simulation_id
    if sim_id != quantum_controller.simulation_id:
        raise HTTPException(status_code=409, detail="Optimization simulation_id does not match the active Quantum SUMO instance")
    payload = body.get("payload")
    if payload is None:
        current = simulation_pair.settings
        density = current.get("density", default_density(scenario_id if scenario_id in {"normal_day", "event_day"} else "normal_day"))
        constraints = current.get("constraints", {})
        live_quantum = await asyncio.to_thread(quantum_controller.capture_current_state)
        if not live_quantum or not quantum_controller.running:
            raise HTTPException(status_code=503, detail="Live SUMO telemetry is unavailable; optimization was not submitted")
        live_vehicles = live_quantum.get("vehicles", [])
        available_tls = {signal["tls_id"] for signal in quantum_controller.network_signals()}
        intersection_loads = live_intersection_loads(live_vehicles, available_tls)
        if not intersection_loads:
            raise HTTPException(status_code=503, detail="No live mapped junctions are available; optimization was not submitted")
        quantum_weather = {"clear": "Clear", "rain": "Light Rain",
                           "heavy rain": "Heavy Rain", "fog": "Fog"}.get(
                               str(constraints.get("weather", "clear")).lower(), "Clear")
        payload = {
            "event": {"name": scenario_id, "venue": "MA Chidambaram Stadium",
                      "total_vehicles": len(live_vehicles)},
            "constraints": {
                # Quantum scenario profiles use canonical title-cased names.
                "weather": quantum_weather,
                "vip": constraints.get("vip_enabled", False),
                "vip_enabled": constraints.get("vip_enabled", False),
                "vip_corridor": constraints.get("vip_corridor"),
                "construction": constraints.get("construction_enabled", False),
                "construction_enabled": constraints.get("construction_enabled", False),
                "construction_corridor": constraints.get("construction_corridor"),
                "crowd_surge": scenario_id == "event_day",
            },
            "intersections": intersection_loads,
            "density": density,
            "signal_timings": current.get("signal_timings", {}),
            "route_modifications": current.get("route_modifications", {}),
            "solver": body.get("solver", "qaoa"),
            **{
            key: value for key, value in body.items()
            if key not in {"message_id", "simulation_id", "scenario_id", "timestamp", "schema_version"}
            }
        }

    quantum_before = copy.deepcopy(quantum_controller.latest_state or {})
    classical_before = copy.deepcopy(controller.latest_state or {})
    record_event("optimization", "Optimization request accepted", {"message_id": message_id,
                                                                     "scenario_id": scenario_id,
                                                                     "pair_id": simulation_pair.run_id})

    # Run synchronously in threadpool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: job_manager.create_and_run_job(
            simulation_id=sim_id,
            scenario_id=scenario_id,
            payload=payload,
            apply_to_sumo=True,
            message_id=message_id
        )
    )

    quantum_after = await asyncio.to_thread(quantum_controller.capture_current_state)
    classical_after = await asyncio.to_thread(controller.capture_current_state)
    plan_data = response.dict()
    checks = await asyncio.to_thread(_explainability_checks, plan_data)
    latest_explainability = _json_safe(explain_plan(plan_data, classical_after, quantum_after,
                                                    load_variable_definitions(), checks))
    def state_summary(state):
        if not state:
            return None
        return {"simulation_id": state.get("simulation_id"), "scenario_id": state.get("scenario_id"),
                "time_s": state.get("time"), "config_hash": state.get("config_hash"),
                "network_hash": state.get("network_hash"), "kpis": state.get("kpis"),
                "congested_edges": sum(1 for edge in state.get("edges_congestion", {}).values()
                                        if edge.get("level") in {"yellow", "orange", "red"})}
    simulation_pair.last_optimization_experiment = {
        "message_id": response.message_id, "run_id": response.run_id,
        "pair_id": simulation_pair.run_id, "scenario_id": scenario_id,
        "same_initial_config": bool(classical_before and quantum_before and
                                     classical_before.get("config_hash") == quantum_before.get("config_hash") and
                                     classical_before.get("network_hash") == quantum_before.get("network_hash")),
        "classical_before": state_summary(classical_before),
        "quantum_before": state_summary(quantum_before),
        "optimizer_inputs": {"event": payload.get("event"),
                             "density": payload.get("density"),
                             "intersections": payload.get("intersections"),
                             "constraints": payload.get("constraints"),
                             "signal_timings": payload.get("signal_timings"),
                             "route_modifications": payload.get("route_modifications")},
        "optimizer_used": response.optimizer_used, "bitstring": response.bitstring,
        "objective_value": response.objective_value,
        "actions": {"corridors": [x.dict() for x in response.corridors],
                    "signals": [x.dict() for x in response.signal_changes],
                    "restrictions": [x.dict() for x in response.restrictions]},
        "application_result": response.application_result,
        "applied_to_sumo": response.applied_to_sumo,
        "classical_after": state_summary(classical_after),
        "quantum_after": state_summary(quantum_after),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }

    record_event("optimization", f"Optimization result {response.status}: {response.optimizer_used}",
                 {"message_id": response.message_id, "bitstring": response.bitstring,
                  "applied_to_sumo": response.applied_to_sumo,
                  "routes": len(response.corridors), "signals": len(response.signal_changes),
                  "restrictions": len(response.restrictions), "runtime_seconds": response.runtime_seconds})
    recommendation_summary = "; ".join(
        f"{item['corridor']}: {item['status']}" for item in latest_explainability["corridors"])
    record_event("optimization", f"Advisory corridor analysis from {response.optimizer_used}: {recommendation_summary}",
                 {"run_id": response.run_id, "optimizer_used": response.optimizer_used,
                  "recommendations_are_advisory": True,
                  "recommendations": [{"corridor": item["corridor"], "status": item["status"],
                                       "decision": item["decision"]}
                                      for item in latest_explainability["corridors"]]})

    return JSONResponse(content=response.dict())

@app.get("/api/integration/runs")
async def list_optimization_runs(limit: int = 20):
    """Fetches recent optimization runs recorded in Supabase / repository store."""
    runs = job_manager.repo.list_recent_runs(limit=limit)
    return JSONResponse(content={"runs": runs})

@app.get("/api/integration/runs/{run_id}")
async def get_optimization_run(run_id: str):
    """Fetches a specific optimization run, including traffic actions and benefits."""
    run_data = job_manager.repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return JSONResponse(content=run_data)

@app.get("/api/integration/latest_plan")
async def get_latest_plan():
    """Returns the currently active quantum traffic plan."""
    if job_manager.latest_plan:
        return JSONResponse(content=job_manager.latest_plan.dict())
    return JSONResponse(content={"status": "none", "message": "No optimization plan has been executed yet."})

# ==============================================================================
# WEBSOCKET STREAM
# ==============================================================================

@app.websocket("/ws/simulation")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    # Send initial geometry and state immediately
    if CACHED_GEOMETRY:
        await websocket.send_text(json.dumps(
            {"type": "geometry", "data": _json_safe(CACHED_GEOMETRY)}, allow_nan=False
        ))
    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                msg = json.loads(data_text)
                cmd = msg.get("action")
                if cmd == "start":
                    if await asyncio.to_thread(simulation_pair.set_scenario, msg.get("scenario", "normal_day")):
                        clear_current_optimization()
                elif cmd == "pause":
                    simulation_pair.pause()
                elif cmd == "resume":
                    simulation_pair.resume()
                elif cmd == "reset":
                    if await asyncio.to_thread(simulation_pair.restart):
                        clear_current_optimization()
                elif cmd == "set_speed":
                    simulation_pair.set_speed(msg.get("multiplier", 1.0))
                elif cmd == "set_scenario":
                    if await asyncio.to_thread(simulation_pair.set_scenario, msg.get("scenario", "normal_day")):
                        clear_current_optimization()
                elif cmd == "optimize":
                    # Trigger optimization from UI
                    asyncio.create_task(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: job_manager.create_and_run_job(
                                simulation_id=f"sim_{controller.current_scenario}",
                                scenario_id=controller.current_scenario,
                                apply_to_sumo=True,
                                message_id=msg.get("message_id")
                            )
                        )
                    )
            except Exception as e:
                print(f"[WS Command Error]: {e}")
    except WebSocketDisconnect:
        active_connections.discard(websocket)
    except Exception:
        active_connections.discard(websocket)

# Mount UI static files
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
