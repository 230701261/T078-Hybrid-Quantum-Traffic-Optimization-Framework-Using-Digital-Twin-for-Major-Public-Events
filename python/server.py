import asyncio
import json
import math
import copy
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Set, Dict, Any, Optional

from .config import UI_DIR
from .traci_controller import TraCIController
from .network_exporter import get_network_geometry
from .integration import OptimizationJobManager, SupabaseRepository
from .integration.id_mapper import CORRIDOR_MAP, JUNCTION_MAP
from .scenario_inputs import default_density, validate_density, operator_profiles
from .simulation_pair import SimulationPair
from .comparison import compare_measurements, measured_delta
from .input_validation import validate_message_id

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
    job_manager.latest_plan = None


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
    simulation_pair.start("normal_day", default_density("normal_day"), {"constraints": {"weather": "clear"}})
    record_event("system", "Synchronized baseline and optimized simulations started")
    asyncio.create_task(broadcast_simulation_stream())

@app.on_event("shutdown")
def shutdown_event():
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

            # Attach latest quantum optimization summary to live state stream
            if job_manager.latest_plan:
                state_data["quantum_optimization"] = {
                    "optimizer_used": job_manager.latest_plan.optimizer_used,
                    "bitstring": job_manager.latest_plan.bitstring,
                    "benefits": job_manager.latest_plan.benefits.dict(),
                    "status": job_manager.latest_plan.status,
                    "applied": job_manager.latest_plan.applied_to_sumo
                }
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
        success = await asyncio.to_thread(simulation_pair.start, scenario, density, inputs)
        action = "started"
        if success:
            clear_current_optimization()
    if success:
        record_event("traffic", f"Simulation pair {action}", {"scenario": scenario})
    return {"status": "ok" if success else "error", "running": success,
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
    return {"routes": routes,
            "corridors": [{"id": name, "canonical_id": item.canonical_id,
                           "edges": item.primary_sumo_edges + item.reverse_sumo_edges}
                          for name, item in CORRIDOR_MAP.items()],
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
            "readback": {"classical": controller.operator_readback,
                         "quantum": quantum_controller.operator_readback}}


@app.get("/api/operator/state")
async def get_operator_state():
    return {"pair_id": simulation_pair.run_id, "scenario_id": simulation_pair.scenario_id,
            "lifecycle_state": simulation_pair.lifecycle_state,
            "density": simulation_pair.settings.get("density"),
            "speed_multiplier": controller.speed_multiplier,
            "constraints": copy.deepcopy(simulation_pair.settings.get("constraints", {})),
            "route_modifications": copy.deepcopy(simulation_pair.settings.get("route_modifications", {})),
            "operator_readback": {"classical": controller.operator_readback,
                                  "quantum": quantum_controller.operator_readback},
            "timestamp": datetime.now(timezone.utc).isoformat()}


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


@app.post("/api/traffic/configure")
async def configure_traffic(request_body: Dict[str, Any]):
    scenario = request_body.get("scenario", simulation_pair.scenario_id or "normal_day")
    try:
        density = validate_density(request_body.get("density"), scenario)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=str(ex)) from ex
    result = await apply_scenario({"scenario": scenario, "density": density,
                                    "constraints": request_body.get("constraints", simulation_pair.settings.get("constraints", {})),
                                    "signal_timings": simulation_pair.settings.get("signal_timings", {}),
                                    "route_modifications": simulation_pair.settings.get("route_modifications", {})})
    record_event("traffic", "TRAFFIC_CONFIG_UPDATED" if result["success"] else "TRAFFIC_CONFIG_REJECTED", result)
    return {"success": result["success"], "operation": "traffic_configure",
            "outcome": "success" if result["success"] else "partial" if result.get("status") == "partial" else "rejected",
            "requested": {"scenario": scenario, "density": density},
            "applied": {"scenario": result["scenario_id"], "density": result["density"]},
            "readback": result["operator_readback"],
            "reason": result.get("limitations") if not result["success"] else None,
            "timestamp": datetime.now(timezone.utc).isoformat(), "pair_id": result["pair_id"]}


@app.post("/api/constraints/weather")
async def configure_weather(request_body: Dict[str, Any]):
    weather = str(request_body.get("weather", "")).lower()
    if weather not in operator_profiles()["weather"]:
        raise HTTPException(status_code=422, detail=f"Unsupported configured weather profile: {weather}")
    return await _apply_constraint_update({"weather": weather}, "WEATHER_UPDATED")


@app.post("/api/constraints/vip")
async def configure_vip(request_body: Dict[str, Any]):
    enabled = request_body.get("enabled")
    corridor = request_body.get("corridor")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    if enabled and corridor not in CORRIDOR_MAP:
        raise HTTPException(status_code=422, detail="Select a known configured VIP corridor")
    return await _apply_constraint_update({"vip_enabled": enabled, "vip_corridor": corridor if enabled else None},
                                          "VIP_UPDATED")


@app.post("/api/constraints/construction")
async def configure_construction(request_body: Dict[str, Any]):
    enabled = request_body.get("enabled")
    corridor = request_body.get("corridor")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled must be a boolean")
    if enabled and corridor not in CORRIDOR_MAP:
        raise HTTPException(status_code=422, detail="Select a known configured construction corridor")
    return await _apply_constraint_update({"construction_enabled": enabled,
                                           "construction_corridor": corridor if enabled else None},
                                          "CONSTRUCTION_UPDATED")


@app.get("/api/operator/capabilities")
async def operator_capabilities():
    """Describe implemented operator controls without implying live support."""
    return {
        "construction_profile": {"status": "available", "mode": "speed_cost_profile"},
        "construction_closure": {"status": "conditional",
            "message": "Live edge closure is accepted only when no active route or loaded future flow uses the edge."},
        "scheduled_flow_diversion": {"status": "unavailable",
            "message": "Loaded route-backed flows cannot be reassigned through the current runtime TraCI interface."},
        "vip_corridor_preference": {"status": "available", "mode": "routing_cost_preference"},
        "vip_entity_assignment": {"status": "unavailable",
            "message": "No VIP vehicle type or VIP demand entity is defined in the loaded SUMO demand."},
        "signal_timing": {"status": "conditional",
            "message": "Only active TLS phases with mutable min/max bounds accept duration changes."},
    }


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
                                             "corridor": request_body.get("corridor")})
    if mode != "closure":
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "construction", "reason_code": "INVALID_MODE",
            "message": "mode must be 'profile' or 'closure'"})
    edges = request_body.get("edges")
    if not isinstance(edges, list) or not edges:
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "construction_closure", "reason_code": "INVALID_EDGES",
            "message": "closure mode requires a non-empty edges list"})
    enabled = request_body.get("enabled", True)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail={"success": False, "status": "rejected",
            "operation": "construction_closure", "reason_code": "INVALID_ENABLED_FLAG",
            "message": "enabled must be a boolean"})
    try:
        operation = simulation_pair.block_edges if enabled else simulation_pair.restore_edges
        result = await asyncio.to_thread(operation, edges)
    except Exception:
        result = {"success": False, "status": "rejected", "operation": "construction_closure",
                  "reason_code": "LIVE_PREFLIGHT_FAILED",
                  "message": "Live SUMO preflight failed; no operation was reported as applied.", "mutations": 0}
    record_event("traffic" if result.get("success") else "system",
                 "CONSTRUCTION_CLOSED" if result.get("success") else "CONSTRUCTION_CLOSURE_REJECTED", result)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/api/operator/vip/assign")
async def assign_vip_entity(request_body: Dict[str, Any]):
    # The loaded route files contain no VIP vehicle type/entity. Keep the
    # existing corridor cost preference, but do not synthesize VIP traffic.
    return JSONResponse(status_code=501, content={"success": False, "status": "unsupported",
        "operation": "vip_assignment", "reason_code": "VIP_ENTITY_NOT_CONFIGURED",
        "message": "VIP assignment unavailable: no VIP entity exists in the current SUMO demand model."})


@app.post("/api/signals/configure")
async def configure_signal(request_body: Dict[str, Any]):
    tls_id, phase, duration = request_body.get("tls_id"), request_body.get("phase"), request_body.get("duration_s")
    if not isinstance(tls_id, str) or not tls_id:
        raise HTTPException(status_code=422, detail="tls_id is required")
    try:
        before = next((signal for signal in controller.network_signals() if signal["tls_id"] == tls_id), None)
        if before is None:
            raise ValueError(f"Unknown traffic-light ID: {tls_id}")
        phase = int(phase) if isinstance(phase, int) and not isinstance(phase, bool) else phase
        classical = await asyncio.to_thread(controller.set_signal_phase_duration, tls_id, phase, duration)
        try:
            quantum = await asyncio.to_thread(quantum_controller.set_signal_phase_duration, tls_id, phase, duration)
        except Exception:
            await asyncio.to_thread(controller.set_signal_phase_duration, tls_id, phase,
                                     classical["before_duration_s"])
            raise
        applied = classical["verified"] and quantum["verified"]
        record_event("traffic", "SIGNAL_UPDATED" if applied else "SIGNAL_REJECTED",
                     {"requested": request_body, "classical": classical, "quantum": quantum})
        return {"success": applied, "operation": "signal_configure", "requested": request_body,
                "outcome": "success" if applied else "rejected",
                "applied": applied, "readback": {"classical": classical, "quantum": quantum},
                "reason": None if applied else "TraCI phase-duration readback mismatch",
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except (ValueError, TypeError, RuntimeError) as ex:
        record_event("system", "SIGNAL_UNSUPPORTED_OR_REJECTED", {"requested": request_body, "reason": str(ex)})
        raise HTTPException(status_code=422, detail={"success": False, "operation": "signal_configure",
                                                   "requested": request_body, "applied": False,
                                                   "readback": None, "reason": str(ex)}) from ex


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
    route_source = routes.get("source") or routes.get("block_corridor")
    alternative = routes.get("alternative")
    blocked = routes.get("blocked", False)
    percent = routes.get("diversion_percent", 0)
    if routes:
        if route_source not in CORRIDOR_MAP or (alternative and alternative not in CORRIDOR_MAP):
            raise HTTPException(status_code=422, detail="Unknown source or alternative corridor")
        if route_source == alternative:
            raise HTTPException(status_code=422, detail="Source and alternative routes must differ")
        if not isinstance(blocked, bool):
            raise HTTPException(status_code=422, detail="blocked must be a boolean")
        if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
            raise HTTPException(status_code=422, detail="diversion_percent must be an integer from 0 to 100")

    shared_inputs = {"constraints": constraints, "signal_timings": signal_timings}
    started = await asyncio.to_thread(simulation_pair.start, scenario, density, shared_inputs)
    if not started:
        raise HTTPException(status_code=503, detail="One or both SUMO simulations failed to start")
    clear_current_optimization()

    simulation_pair.settings["route_modifications"] = routes
    controller.scenario_inputs["route_modifications"] = routes
    quantum_controller.scenario_inputs["route_modifications"] = routes
    route_result = None
    if routes:
        try:
            route_result = await asyncio.to_thread(simulation_pair.apply_route_control,
                                                    route_source, alternative, percent, blocked)
        except Exception as ex:
            raise HTTPException(status_code=422, detail=f"Route control could not be applied: {ex}") from ex
        record_event("traffic", "Route controls applied to both simulations", route_result)

    readbacks = {"classical": controller.operator_readback, "quantum": quantum_controller.operator_readback}
    readback_ok = True
    for side in readbacks.values():
        for key, item in side.items():
            if key == "signals":
                readback_ok = readback_ok and all(signal.get("verified", False)
                                                   for signal in item.values())
            else:
                readback_ok = readback_ok and item.get("verified", False)
    route_ok = (route_result is None or all(
        result.get("readback_confirmed") and not result.get("errors") and not result.get("failed")
        and (not result.get("blocked") or result.get("new_entries_blocked"))
        and (not alternative or percent <= 0 or result.get("successful", 0) > 0)
        for result in route_result.values()))
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
    source = request_body.get("source")
    alternative = request_body.get("alternative")
    percent = request_body.get("diversion_percent", 0)
    blocked = request_body.get("blocked", False)
    if source not in CORRIDOR_MAP or (alternative and alternative not in CORRIDOR_MAP):
        raise HTTPException(status_code=422, detail="Unknown source or alternative corridor")
    if source == alternative:
        raise HTTPException(status_code=422, detail="Source and alternative routes must differ")
    if isinstance(percent, bool) or not isinstance(percent, int) or not 0 <= percent <= 100:
        raise HTTPException(status_code=422, detail="diversion_percent must be an integer from 0 to 100")
    if not isinstance(blocked, bool):
        raise HTTPException(status_code=422, detail="blocked must be a boolean")
    try:
        result = await asyncio.to_thread(simulation_pair.apply_route_control, source, alternative, percent, blocked)
    except Exception as ex:
        event_type = "ROUTE_BLOCK_REJECTED" if blocked else "ROUTE_OPERATION_REJECTED"
        record_event("system", event_type, {"requested": request_body, "applied": False, "reason": str(ex)})
        raise HTTPException(status_code=422, detail={"success": False, "operation": event_type,
            "requested": request_body, "applied": False, "readback": None, "reason": str(ex),
            "timestamp": datetime.now(timezone.utc).isoformat()}) from ex
    readbacks_ok = all(x.get("readback_confirmed") and
                       (not x.get("blocked") or x.get("new_entries_blocked")) and
                       (not alternative or percent <= 0 or x.get("successful", 0) > 0)
                       for x in result.values())
    any_errors = any(x.get("errors") or x.get("failed", 0) for x in result.values())
    outcome = "applied" if readbacks_ok and not any_errors else "partial"
    route_settings = {"source": source, "alternative": alternative,
                      "diversion_percent": percent, "blocked": blocked}
    operation = "ROUTE_BLOCKED" if blocked and outcome == "applied" else "ROUTE_BLOCK_REJECTED" if blocked else "ROUTE_REROUTED" if alternative else "ROUTE_RESTORED"
    if outcome == "applied":
        simulation_pair.settings["route_modifications"] = route_settings
        controller.scenario_inputs["route_modifications"] = route_settings
        quantum_controller.scenario_inputs["route_modifications"] = route_settings
    record_event("traffic" if outcome == "applied" else "system", operation,
                 {"requested": request_body, "result": result, "success": outcome == "applied"})
    return {"status": outcome, "success": outcome == "applied", "operation": operation,
            "outcome": "success" if outcome == "applied" else "partial",
            "requested": request_body, "applied": outcome == "applied",
            "readback": result, "result": result,
            "reason": None if outcome == "applied" else "TraCI did not confirm every route change; rollback was attempted.",
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/operations/events")
async def get_operation_events(limit: int = 100):
    return {"events": list(operation_events)[-max(1, min(limit, 500)):], "pair_id": simulation_pair.run_id}


@app.post("/api/simulation/vehicles/{vehicle_id}/reroute")
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
        try:
            with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return {"status": "CONNECTED" if response.status == 200 else "OFFLINE",
                        "decision_variables": payload.get("decision_variables")}
        except Exception:
            return {"status": "OFFLINE", "decision_variables": None}
    quantum = await asyncio.to_thread(quantum_status)
    repository = job_manager.repo
    pair_state = simulation_pair.lifecycle_state
    digital_twin_state = ("DEGRADED" if pair_state == "DEGRADED" else
                          "ERROR" if pair_state == "ERROR" else pair_state)
    return {
        "sumo_classical": "CONNECTED" if controller.running and controller.lifecycle_state != "ERROR" else
                          "ERROR" if controller.lifecycle_state == "ERROR" else "DISCONNECTED",
        "sumo_quantum": "CONNECTED" if quantum_controller.running and quantum_controller.lifecycle_state != "ERROR" else
                        "ERROR" if quantum_controller.lifecycle_state == "ERROR" else "DISCONNECTED",
        "digital_twin": digital_twin_state,
        "simulation_state": pair_state,
        "paused": pair_state == "PAUSED",
        "quantum_api": quantum,
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
