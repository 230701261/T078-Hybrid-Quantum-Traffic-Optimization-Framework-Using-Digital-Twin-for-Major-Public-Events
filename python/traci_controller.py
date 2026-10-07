import os
import sys
import time
import threading
import contextlib
import tempfile
import hashlib
import json
import copy
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from pathlib import Path
import traci
from typing import Dict, Any, Optional

from .config import NORMAL_CFG, EVENT_CFG, SIM_STEP_LENGTH
from .traffic_light_manager import TrafficLightManager
from .scenario_manager import ScenarioManager
from .metrics_collector import MetricsCollector
from .scenario_inputs import RouteValidationError, make_route_variant, validate_density, operator_profiles
from .integration.id_mapper import CORRIDOR_MAP, JUNCTION_MAP
from .integration.constraint_engine import ConstraintEngine
from .traci_session import TRACI_SESSION_LOCK

class TraCIController:
    def __init__(self, label: str = "default", simulation_id: Optional[str] = None):
        self.label = label
        self.simulation_id = simulation_id or f"sim_{label}"
        self.lock = threading.Lock()
        self.start_lock = threading.Lock()
        self.running = False
        self.paused = False
        self.lifecycle_state = "STOPPED"
        self.last_error: Optional[str] = None
        self.last_error_code: Optional[str] = None
        self.speed_multiplier = 1.0
        self.current_scenario = "normal_day"
        self.sim_time = 0.0
        
        self.traffic_lights = TrafficLightManager()
        self.scenario_mgr = ScenarioManager()
        self.metrics = MetricsCollector()
        
        self.thread: Optional[threading.Thread] = None
        self.latest_state: Dict[str, Any] = {}
        self.edge_speed_limits = {}
        self.lane_base_speed_limits: Dict[str, float] = {}
        self.base_lane_permissions: Dict[str, list[str]] = {}
        self.base_lane_disallowed: Dict[str, list[str]] = {}
        self.blocked_corridors: Dict[str, list[str]] = {}
        # Original live permissions retained only for edges closed through the
        # runtime operator API. They are scoped to this SUMO process lifetime.
        self.edge_closure_snapshots: Dict[str, list[dict[str, Any]]] = {}
        self.route_origin_edges: set[str] = set()
        self.flow_route_edges: set[str] = set()
        self.adapted_edge_costs: Dict[str, float] = {}
        self.base_edge_travel_times: Dict[str, float] = {}
        self.departure_times: Dict[str, float] = {}
        self.waiting_by_vehicle: Dict[str, float] = {}
        self.completed_trip_times: list[float] = []
        self.completed_waiting_times: list[float] = []
        self.departed_vehicle_count = 0
        self.arrived_vehicle_count = 0
        self.loaded_vehicle_ids: set[str] = set()
        self.departed_by_type: Dict[str, int] = {}
        self._last_rate_wall = time.monotonic()
        self._last_rate_sim = 0.0
        self.effective_speed_multiplier: Optional[float] = None
        self.last_snapshot_wall = 0.0
        self.telemetry_interval_seconds = 0.5
        self.operator_readback: Dict[str, Any] = {}
        self.network_hash = self._network_digest()
        self.route_variant: Optional[Path] = None
        self.scenario_inputs: Dict[str, Any] = {}
        self.density = None
        self.demand_summary: Dict[str, Any] = {}
        self.simulation_started_at: Optional[str] = None

    @contextlib.contextmanager
    def traci_session(self):
        """Select this controller's labeled TraCI session under the shared lock."""
        with TRACI_SESSION_LOCK:
            traci.switch(self.label)
            yield

    def start(self, scenario: str = "normal_day", density: Optional[Dict[str, int]] = None,
              inputs: Optional[Dict[str, Any]] = None):
        with self.start_lock:
            # Parse, scale, and validate demand before stopping the existing
            # worker or closing its TraCI session. Invalid input is a safe
            # rejection, not a destructive restart attempt.
            selected_density = validate_density(density, scenario)
            next_route_variant = make_route_variant(scenario, selected_density)

            # Stop and join the previous worker before touching its route file or
            # starting a replacement; SUMO keeps the route file open on Windows.
            with self.lock:
                self.running = False
            old_thread = self.thread
            if old_thread and old_thread.is_alive() and old_thread is not threading.current_thread():
                old_thread.join(timeout=3.0)

            with self.lock:
                self.current_scenario = scenario
                self.lifecycle_state = "STARTING"
                self.last_error = None
                self.last_error_code = None
                self.scenario_mgr.set_scenario(scenario)
                self.metrics.reset()
                self.paused = False
                self.scenario_inputs = dict(inputs or {})
                # Permission snapshots belong to a particular live SUMO
                # process and must never be restored into a restarted one.
                self.edge_closure_snapshots.clear()
                self.blocked_corridors.clear()
                self.density = selected_density
                self.departure_times.clear()
                self.waiting_by_vehicle.clear()
                self.completed_trip_times.clear()
                self.completed_waiting_times.clear()
                self.departed_vehicle_count = 0
                self.arrived_vehicle_count = 0
                self.loaded_vehicle_ids.clear()
                self.departed_by_type = {}
                self.sim_time = 0.0
                self.latest_state = {}

                with TRACI_SESSION_LOCK:
                    try:
                        try:
                            traci.switch(self.label)
                            traci.close()
                        except Exception:
                            pass
                        if self.route_variant:
                            self.route_variant.unlink(missing_ok=True)
                        self.route_variant = next_route_variant
                        self.route_origin_edges = self._route_flow_origin_edges(self.route_variant)
                        self.flow_route_edges = self._route_flow_edges(self.route_variant)
                        cfg_file = EVENT_CFG if scenario == "event_day" else NORMAL_CFG
                        self.demand_summary = self._summarize_demand(self.route_variant, cfg_file)
                        self.scenario_mgr.set_demand_end_time(self.demand_summary["simulation_end_s"])
                        self.simulation_started_at = datetime.now(timezone.utc).isoformat()
                        print(
                            f"[Demand] {self.label}: {self.demand_summary['vehicle_demand_definitions']} vehicle demand definitions, "
                            f"{self.demand_summary['flow_count']} flows, "
                            f"~{self.demand_summary['estimated_vehicle_demand']} expected vehicles; "
                            f"simulation window 0–{self.demand_summary['simulation_end_s']:.0f}s"
                        )
                        sumo_cmd = [
                            "sumo", "-c", cfg_file,
                            "--route-files", str(self.route_variant),
                            "--seed", str(self.scenario_inputs.get("seed", 1)),
                            "--step-length", str(SIM_STEP_LENGTH),
                            "--no-step-log", "true", "--no-warnings", "true"
                        ]
                        traci.start(sumo_cmd, label=self.label, doSwitch=True)
                        traci.switch(self.label)
                        self.traffic_lights.initialize()
                        self._cache_edge_speed_limits()
                        self._apply_initial_inputs()
                        self.running = True
                        self.lifecycle_state = "RUNNING"
                    except Exception as ex:
                        route_failure = (isinstance(ex, RouteValidationError) or
                                         "no valid route" in str(ex).lower() or
                                         "no connection between edge" in str(ex).lower())
                        code = "ROUTE_INVALID" if route_failure else "SUMO_START_FAILED"
                        print(f"[{code}] Failed to start SUMO ({self.label}): {ex}")
                        try:
                            traci.switch(self.label)
                            traci.close()
                        except Exception:
                            # Preserve the original startup failure; this only
                            # releases a partially opened TraCI session.
                            pass
                        self.running = False
                        self.lifecycle_state = "ERROR"
                        self.last_error = str(ex)
                        self.last_error_code = code
                        if self.route_variant:
                            self.route_variant.unlink(missing_ok=True)
                            self.route_variant = None
                        return False

            self.thread = threading.Thread(target=self._simulation_loop, daemon=True)
            self.thread.start()
            return True

    def _cache_edge_speed_limits(self):
        self.edge_speed_limits = {}
        self.lane_base_speed_limits = {}
        self.base_lane_permissions = {}
        self.base_lane_disallowed = {}
        self.base_edge_travel_times = {}
        try:
            for edge_id in traci.edge.getIDList():
                try:
                    self.base_edge_travel_times[edge_id] = float(traci.edge.getTraveltime(edge_id))
                    lane_0 = f"{edge_id}_0"
                    self.edge_speed_limits[edge_id] = traci.lane.getMaxSpeed(lane_0)
                except Exception:
                    self.edge_speed_limits[edge_id] = 13.89
                for lane_idx in range(traci.edge.getLaneNumber(edge_id)):
                    lane_id = f"{edge_id}_{lane_idx}"
                    try:
                        self.lane_base_speed_limits[lane_id] = traci.lane.getMaxSpeed(lane_id)
                    except Exception:
                        self.lane_base_speed_limits[lane_id] = self.edge_speed_limits[edge_id]
                    try:
                        self.base_lane_permissions[lane_id] = list(traci.lane.getAllowed(lane_id))
                    except Exception:
                        self.base_lane_permissions[lane_id] = []
                    try:
                        self.base_lane_disallowed[lane_id] = list(traci.lane.getDisallowed(lane_id))
                    except Exception:
                        self.base_lane_disallowed[lane_id] = []
        except Exception:
            pass

    def pause(self):
        with self.lock:
            self.paused = True
            if self.running:
                self.lifecycle_state = "PAUSED"

    def resume(self):
        with self.lock:
            self.paused = False
            if self.running:
                self.lifecycle_state = "RUNNING"

    def reset(self):
        self.start(self.current_scenario, self.density, self.scenario_inputs)

    def set_speed(self, multiplier: float):
        with self.lock:
            self.speed_multiplier = max(0.2, min(20.0, float(multiplier)))

    def set_scenario(self, scenario: str):
        if scenario in ["normal_day", "event_day"]:
            self.start(scenario)

    def _simulation_loop(self):
        next_step_due = time.monotonic()
        while self.running:
            if self.paused:
                time.sleep(0.05)
                next_step_due = time.monotonic()
                continue
            step_started = time.monotonic()
            try:
                with self.lock, TRACI_SESSION_LOCK:
                    traci.switch(self.label)
                    traci.simulationStep()
                    self.sim_time = float(traci.simulation.getTime())
                    try:
                        self.loaded_vehicle_ids.update(traci.simulation.getLoadedIDList())
                    except Exception:
                        pass
                    for vehicle_id in traci.simulation.getDepartedIDList():
                        self.departed_vehicle_count += 1
                        try:
                            type_id = traci.vehicle.getTypeID(vehicle_id).lower()
                            mode = ("buses" if "bus" in type_id else
                                    "two_wheelers" if "bike" in type_id or "motorcycle" in type_id else
                                    "local_trains" if "train" in type_id else "cars")
                            self.departed_by_type[mode] = self.departed_by_type.get(mode, 0) + 1
                            self.departure_times[vehicle_id] = float(traci.vehicle.getDeparture(vehicle_id))
                        except Exception as ex:
                            print(f"[TraCI Departure Readback] vehicle={vehicle_id} error={ex}")
                    arrived_ids = traci.simulation.getArrivedIDList()
                    self.arrived_vehicle_count += len(arrived_ids)
                    for vehicle_id in arrived_ids:
                        departure = self.departure_times.pop(vehicle_id, None)
                        if departure is not None:
                            self.completed_trip_times.append(max(0.0, self.sim_time - departure))
                        waiting = self.waiting_by_vehicle.pop(vehicle_id, None)
                        if waiting is not None:
                            self.completed_waiting_times.append(waiting)
                    self.scenario_mgr.step(self.sim_time)
                    now = time.monotonic()
                    if now - self._last_rate_wall >= 1.0:
                        elapsed = now - self._last_rate_wall
                        self.effective_speed_multiplier = ((self.sim_time - self._last_rate_sim) / elapsed
                                                           / SIM_STEP_LENGTH)
                        self._last_rate_wall = now
                        self._last_rate_sim = self.sim_time
                    if now - self.last_snapshot_wall >= self.telemetry_interval_seconds:
                        self.latest_state = self._extract_snapshot()
                        self.last_snapshot_wall = now
            except traci.exceptions.FatalTraCIError as ex:
                print(f"[TraCI] Simulation ended ({self.label}): {ex}")
                self.running = False
                self.lifecycle_state = "STOPPED"
                break
            except Exception as ex:
                self.last_error = str(ex)
                self.lifecycle_state = "ERROR"
                print(f"[TraCI Step Error] label={self.label} sim_time={self.sim_time}: {ex}")
                time.sleep(0.05)
                continue

            target_interval = SIM_STEP_LENGTH / max(0.2, self.speed_multiplier)
            next_step_due += target_interval
            remaining = next_step_due - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            else:
                # Do not accumulate schedule debt and spin at full CPU after a
                # telemetry-heavy step; continue at the best sustainable rate.
                next_step_due = time.monotonic()

    def _extract_snapshot(self) -> Dict[str, Any]:
        sim_time = self.sim_time
        
        # 1. Vehicles
        vehicles = []
        try:
            veh_ids = traci.vehicle.getIDList()
            for v_id in veh_ids:
                try:
                    pos = traci.vehicle.getPosition(v_id)
                    try:
                        elevation = float(traci.vehicle.getPosition3D(v_id)[2])
                    except Exception:
                        elevation = 0.0
                    angle = traci.vehicle.getAngle(v_id)
                    speed = traci.vehicle.getSpeed(v_id)
                    v_type = traci.vehicle.getTypeID(v_id)
                    lane_id = traci.vehicle.getLaneID(v_id)
                    road_id = traci.vehicle.getRoadID(v_id)
                    waiting_time = traci.vehicle.getWaitingTime(v_id)
                    accumulated_waiting_time = traci.vehicle.getAccumulatedWaitingTime(v_id)
                    length = traci.vehicle.getLength(v_id)
                    width = traci.vehicle.getWidth(v_id)
                    
                    # Normalize category
                    cat = "car"
                    if "bike" in v_type or "motorcycle" in v_type:
                        cat = "motorcycle"
                    elif "bus" in v_type:
                        cat = "bus"
                    elif "emergency" in v_type:
                        cat = "emergency"
                    elif "train" in v_type:
                        cat = "train"
                    elif "taxi" in v_type:
                        cat = "taxi"

                    vehicles.append({
                        "id": v_id,
                        "type": cat,
                        "vType": v_type,
                        "x": round(pos[0], 2),
                        "y": round(pos[1], 2),
                        "z": round(elevation, 2),
                        "angle": round(angle, 1),
                        "speed": round(speed, 2),
                        "speed_kmh": round(speed * 3.6, 1),
                        "lane_id": lane_id,
                        "road_id": road_id,
                        "waiting_time": round(waiting_time, 1),
                        "accumulated_waiting_time": round(accumulated_waiting_time, 1),
                        "length": round(length, 1),
                        "width": round(width, 1)
                    })
                except Exception:
                    self.waiting_by_vehicle.pop(v_id, None)
                    continue
        except Exception:
            pass

        # 2. Pedestrians (Persons)
        pedestrians = []
        try:
            person_ids = traci.person.getIDList()
            for p_id in person_ids:
                try:
                    pos = traci.person.getPosition(p_id)
                    angle = traci.person.getAngle(p_id)
                    speed = traci.person.getSpeed(p_id)
                    p_type = traci.person.getTypeID(p_id)
                    road_id = traci.person.getRoadID(p_id)
                    
                    # Classify destination flow
                    dest_flow = "local"
                    if "stadium" in p_id or "stad" in p_type:
                        dest_flow = "stadium"
                    elif "beach" in p_id or "beach" in p_type:
                        dest_flow = "beach"

                    pedestrians.append({
                        "id": p_id,
                        "type": p_type,
                        "dest_flow": dest_flow,
                        "x": round(pos[0], 2),
                        "y": round(pos[1], 2),
                        "angle": round(angle, 1),
                        "speed": round(speed, 2),
                        "edge_id": road_id
                    })
                except Exception:
                    continue
        except Exception:
            pass

        active_pedestrian_count = len(pedestrians)
        try:
            pending_vehicle_ids = list(traci.simulation.getPendingVehicles())
        except Exception:
            pending_vehicle_ids = []
        estimated_remaining = max(
            0, int(round(self.demand_summary.get("estimated_vehicle_demand", 0)
                         - self.departed_vehicle_count))
        )
        pending_vehicle_count = max(len(pending_vehicle_ids), estimated_remaining)
        if vehicles:
            vehicle_demand_status = "ACTIVE"
        elif pending_vehicle_count:
            vehicle_demand_status = "VEHICLES_PENDING"
        elif sim_time >= self.demand_summary.get("vehicle_demand_end_s", float("inf")):
            vehicle_demand_status = "SIMULATION_RUNNING_NO_ACTIVE_VEHICLES"
        else:
            vehicle_demand_status = "WAITING_FOR_DEPARTURES"

        # 3. Traffic Lights
        tls_states = self.traffic_lights.get_all_states()

        # 4. Road Edge Congestion Levels
        edges_congestion = {}
        try:
            for edge_id in traci.edge.getIDList():
                if edge_id.startswith(":"):
                    continue
                try:
                    mean_speed = traci.edge.getLastStepMeanSpeed(edge_id)
                    occupancy = traci.edge.getLastStepOccupancy(edge_id)
                    halting = traci.edge.getLastStepHaltingNumber(edge_id)
                    max_speed = self.edge_speed_limits.get(edge_id, 13.89)
                    
                    speed_ratio = mean_speed / max_speed if max_speed > 0 else 1.0
                    queue_m = halting * 6.5
                    
                    # Congestion classification
                    if occupancy > 0.40 or (halting >= 3 and speed_ratio < 0.3):
                        level = "red"
                    elif occupancy > 0.15 or speed_ratio < 0.6:
                        level = "yellow"
                    else:
                        level = "green"

                    edges_congestion[edge_id] = {
                        "speed_ratio": round(speed_ratio, 2),
                        "occupancy": round(occupancy, 2),
                        "queue_len": round(queue_m, 1),
                        "level": level
                    }
                except Exception:
                    continue
        except Exception:
            pass

        # 5. Bus Stops
        bus_stops = []
        try:
            for bs_id in traci.busstop.getIDList():
                try:
                    p_count = traci.busstop.getPersonCount(bs_id)
                    veh_ids = traci.busstop.getVehicleIDs(bs_id)
                    bus_stops.append({
                        "id": bs_id,
                        "waiting": p_count,
                        "active_buses": list(veh_ids)
                    })
                except Exception:
                    continue
        except Exception:
            pass

        # 6. Update KPIs in Metrics Collector
        for vehicle in vehicles:
            self.waiting_by_vehicle[vehicle["id"]] = vehicle["accumulated_waiting_time"]
        self.metrics.update(sim_time, vehicles, pedestrians, edges_congestion, self.current_scenario,
                            self.completed_trip_times, self.completed_waiting_times)
        self.completed_trip_times.clear()
        self.completed_waiting_times.clear()
        settings = {"scenario": self.current_scenario, "density": self.density, **self.scenario_inputs}
        config_hash = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()

        return {
            "time": round(sim_time, 1),
            "scenario": self.current_scenario,
            "simulation_id": self.simulation_id,
            "connection_status": "CONNECTED" if self.running else "DISCONNECTED",
            "lifecycle_state": self.lifecycle_state,
            "last_error": self.last_error,
            "network_hash": self.network_hash,
            "config_hash": config_hash,
            "scenario_id": self.current_scenario,
            "scenario_inputs": self.scenario_inputs,
            "configured_demand_per_hour": self.density,
            "generated_vehicles": self.departed_vehicle_count,
            "generated_vehicles_by_mode": dict(self.departed_by_type),
            "simulation_started_at": self.simulation_started_at,
            "simulation_window": {"start_s": 0.0,
                                  "end_s": self.demand_summary.get("simulation_end_s")},
            "demand": {
                **self.demand_summary,
                "loaded_vehicle_count": len(self.loaded_vehicle_ids),
                "loaded_vehicle_ids_sample": sorted(self.loaded_vehicle_ids)[:20],
                "active_vehicle_count": len(vehicles),
                "departed_vehicle_count": self.departed_vehicle_count,
                "arrived_vehicle_count": self.arrived_vehicle_count,
                "pending_vehicle_count": pending_vehicle_count,
                "pending_insertion_count": len(pending_vehicle_ids),
                "expected_vehicles_remaining_estimate": estimated_remaining,
                "active_pedestrian_count": active_pedestrian_count,
                "vehicle_demand_status": vehicle_demand_status,
            },
            "scenario_inputs": self.scenario_inputs,
            "event_phase": self.scenario_mgr.get_event_phase(sim_time),
            "paused": self.paused,
            "speed_multiplier": self.speed_multiplier,
            "effective_speed_multiplier": self.effective_speed_multiplier,
            "telemetry_timestamp": time.time(),
            "operator_readback": self.operator_readback,
            "vehicles": vehicles,
            "pedestrians": pedestrians,
            "traffic_lights": tls_states,
            "edges_congestion": edges_congestion,
            # The renderer only marks a closure after the operator mutation
            # verified its live lane-permission readback.
            "closed_edges": sorted(self.edge_closure_snapshots),
            "bus_stops": bus_stops,
            "kpis": self.metrics.live_kpis,
            "chart_data": self.metrics.get_chart_data()
        }

    @staticmethod
    def _summarize_demand(route_file: Path, config_file: str) -> Dict[str, Any]:
        """Summarize configured demand without treating flow estimates as counts."""
        route_root = ET.parse(route_file).getroot()
        config_root = ET.parse(config_file).getroot()
        end_node = config_root.find("./time/end")
        configured_end = float(end_node.get("value", "3600")) if end_node is not None else 3600.0
        routes = {node.get("id") for node in route_root.findall("route")}
        vehicle_definitions = 0
        flow_count = 0
        vehicle_flow_count = 0
        pedestrian_flow_count = 0
        route_demand_count = 0
        expected_vehicles = 0.0
        vehicle_demand_end = 0.0
        for node in route_root:
            if node.tag == "vehicle":
                vehicle_definitions += 1
                route_demand_count += 1
                expected_vehicles += 1.0
                vehicle_demand_end = max(vehicle_demand_end, float(node.get("depart", "0")))
            elif node.tag == "flow":
                flow_count += 1
                vehicle_flow_count += 1
                route_demand_count += 1
                begin = float(node.get("begin", "0"))
                end = min(configured_end, float(node.get("end", str(configured_end))))
                duration = max(0.0, end - begin)
                vehicle_demand_end = max(vehicle_demand_end, end)
                if node.get("number") is not None:
                    expected_vehicles += float(node.get("number", "0"))
                elif node.get("vehsPerHour") is not None:
                    expected_vehicles += duration * float(node.get("vehsPerHour", "0")) / 3600.0
                elif node.get("period") is not None and duration > 0:
                    expected_vehicles += max(0, int((duration - 1e-9) // float(node.get("period", "1"))) + 1)
                if node.get("route") and node.get("route") not in routes:
                    raise ValueError(f"Demand flow {node.get('id')} references missing route {node.get('route')}")
            elif node.tag == "personFlow":
                flow_count += 1
                pedestrian_flow_count += 1
        return {
            "route_count": len(routes),
            "route_demand_count": route_demand_count,
            "vehicle_demand_definitions": vehicle_definitions + vehicle_flow_count,
            "vehicle_flow_count": vehicle_flow_count,
            "pedestrian_flow_count": pedestrian_flow_count,
            "flow_count": flow_count,
            "estimated_vehicle_demand": int(round(expected_vehicles)),
            "simulation_end_s": configured_end,
            "vehicle_demand_end_s": vehicle_demand_end,
        }

    def capture_current_state(self) -> Dict[str, Any]:
        """Read a causally ordered TraCI snapshot without advancing simulation time."""
        if not self.running:
            return {}
        with self.lock, TRACI_SESSION_LOCK:
            traci.switch(self.label)
            self.sim_time = float(traci.simulation.getTime())
            state = self._extract_snapshot()
            self.latest_state = state
            self.last_snapshot_wall = time.monotonic()
            return state

    def _stop_sumo(self):
        try:
            traci.switch(self.label)
            traci.close()
        except Exception:
            pass
        self.running = False
        if self.lifecycle_state != "ERROR":
            self.lifecycle_state = "STOPPED"

    def close(self):
        self.lifecycle_state = "STOPPING"
        with self.start_lock:
            with self.lock:
                self.running = False
            old_thread = self.thread
            if old_thread and old_thread.is_alive() and old_thread is not threading.current_thread():
                old_thread.join(timeout=3.0)
            with TRACI_SESSION_LOCK:
                self._stop_sumo()
            if self.route_variant:
                self.route_variant.unlink(missing_ok=True)
                self.route_variant = None

    def stop(self):
        self.close()

    @staticmethod
    def _network_digest() -> str:
        from .config import NET_FILE
        try:
            digest = hashlib.sha256()
            with open(NET_FILE, "rb") as network_file:
                for chunk in iter(lambda: network_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return "unavailable"

    @staticmethod
    def _route_flow_origin_edges(route_file: Path) -> set[str]:
        """Return explicit route origins used by live SUMO flow insertions."""
        root = ET.parse(route_file).getroot()
        route_starts = {node.get("id"): edges[0]
                        for node in root if node.tag == "route"
                        if (edges := node.get("edges", "").split())}
        return {route_starts[node.get("route")] for node in root
                if node.tag in {"flow", "personFlow"} and node.get("route") in route_starts}

    @staticmethod
    def _route_flow_edges(route_file: Path) -> set[str]:
        """Return every edge used by a route assigned to a future flow."""
        root = ET.parse(route_file).getroot()
        route_edges = {node.get("id"): set(node.get("edges", "").split())
                       for node in root if node.tag == "route"}
        flow_routes = {node.get("route") for node in root
                       if node.tag in {"flow", "personFlow"} and node.get("route")}
        return set().union(*(route_edges.get(route_id, set()) for route_id in flow_routes))

    def network_routes(self) -> list[dict[str, Any]]:
        """Describe route definitions and flows from the currently loaded route file."""
        if not self.route_variant or not self.route_variant.exists():
            return []
        root = ET.parse(self.route_variant).getroot()
        route_nodes = {node.get("id"): node for node in root if node.tag == "route"}
        flow_counts: Dict[str, int] = {}
        flow_types: Dict[str, set[str]] = {}
        for node in root:
            route_id = node.get("route")
            if node.tag in {"flow", "personFlow"} and route_id:
                flow_counts[route_id] = flow_counts.get(route_id, 0) + 1
                flow_types.setdefault(route_id, set()).add(node.get("type", "unknown"))
        try:
            with self.traci_session():
                active_routes: Dict[str, int] = {}
                type_classes = {type_id: traci.vehicletype.getVehicleClass(type_id)
                                for type_id in traci.vehicletype.getIDList()}
                for vehicle_id in traci.vehicle.getIDList():
                    route_id = traci.vehicle.getRouteID(vehicle_id)
                    active_routes[route_id] = active_routes.get(route_id, 0) + 1
        except Exception:
            active_routes = {}
            type_classes = {}
        result = []
        for route_id, node in route_nodes.items():
            edges = node.get("edges", "").split()
            if not edges:
                continue
            types = flow_types.get(route_id, set())
            classes = sorted({type_classes.get(type_id) for type_id in types if type_classes.get(type_id)})
            lanes = []
            try:
                with self.traci_session():
                    for index in range(traci.edge.getLaneNumber(edges[0])):
                        lanes.append({"speed": float(traci.lane.getMaxSpeed(f"{edges[0]}_{index}")),
                                      "disallowed": list(traci.lane.getDisallowed(f"{edges[0]}_{index}"))})
            except Exception:
                pass
            result.append({"route_id": route_id, "route_name": node.get("name"),
                           "edges": edges, "origin": edges[0], "destination": edges[-1],
                           "vehicle_types": sorted(types), "vehicle_classes": classes,
                           "active_flow_count": flow_counts.get(route_id, 0),
                           "active_vehicle_count": active_routes.get(route_id, 0),
                           "blocked": bool(lanes) and all(lane["disallowed"] for lane in lanes),
                           "restricted": bool(lanes) and any(lane["disallowed"] for lane in lanes),
                           "alternative_routes": []})
        for route in result:
            route["alternative_routes"] = [candidate["route_id"] for candidate in result
                                           if candidate["route_id"] != route["route_id"]
                                           and candidate["origin"] == route["origin"]
                                           and candidate["destination"] == route["destination"]
                                           and not candidate["blocked"]]
        return result

    def network_edges(self) -> list[dict[str, Any]]:
        """Return live SUMO topology and edge/lane restriction state."""
        with self.traci_session():
            output = []
            construction_corridor = self.scenario_inputs.get("constraints", {}).get("construction_corridor")
            construction_edges = set()
            construction_mapping = CORRIDOR_MAP.get(construction_corridor)
            if construction_mapping:
                construction_edges.update(construction_mapping.primary_sumo_edges)
                construction_edges.update(construction_mapping.reverse_sumo_edges)
            for edge_id in traci.edge.getIDList():
                if edge_id.startswith(":"):
                    continue
                lanes = []
                for index in range(traci.edge.getLaneNumber(edge_id)):
                    lane_id = f"{edge_id}_{index}"
                    lanes.append({"lane_id": lane_id,
                                  "max_speed_mps": float(traci.lane.getMaxSpeed(lane_id)),
                                  "allowed": list(traci.lane.getAllowed(lane_id)),
                                  "disallowed": list(traci.lane.getDisallowed(lane_id))})
                from_node = str(traci.edge.getFromJunction(edge_id))
                to_node = str(traci.edge.getToJunction(edge_id))
                lane_classes = set()
                for lane in lanes:
                    lane_classes.update(lane["allowed"])
                if not lane_classes:
                    lane_classes = {"default"}
                motor_classes = {traci.vehicletype.getVehicleClass(vtype)
                                 for vtype in traci.vehicletype.getIDList()}
                motor_classes.discard("")
                blocked = bool(lanes) and all(
                    not any((not lane["allowed"] or vehicle_class in lane["allowed"])
                            and vehicle_class not in lane["disallowed"]
                            for vehicle_class in motor_classes)
                    for lane in lanes
                )
                output.append({"edge_id": edge_id, "lane_count": len(lanes), "lanes": lanes,
                               "from_node": from_node, "to_node": to_node,
                               "speed_mps": min((lane["max_speed_mps"] for lane in lanes), default=None),
                               "allowed_vehicle_classes": sorted(lane_classes),
                               "current_restriction": "CLOSED" if blocked else (
                                   "RESTRICTED" if any(lane["disallowed"] for lane in lanes) else "OPEN"),
                               "construction_status": "ACTIVE" if edge_id in construction_edges else "INACTIVE",
                               "operator_closure": edge_id in self.edge_closure_snapshots,
                               "blocked": blocked})
            return output

    def optimizer_constraint_context(self) -> dict[str, Any]:
        """Build live hard-constraint inputs while this controller is selected."""
        edges = set(traci.edge.getIDList())
        vehicles = set(traci.vehicle.getIDList())
        active_route_edges = set()
        for vehicle_id in vehicles:
            try:
                route = tuple(traci.vehicle.getRoute(vehicle_id))
                index = int(traci.vehicle.getRouteIndex(vehicle_id))
                active_route_edges.update(route[max(0, index):])
            except Exception:
                continue
        blocked = set()
        for edge_id in edges:
            try:
                if ConstraintEngine.edge_is_closed(edge_id):
                    blocked.add(edge_id)
            except Exception:
                # A failed live permission read must fail closed in validation.
                blocked.add(edge_id)
        return {
            "edge_ids": edges,
            "tls_ids": set(traci.trafficlight.getIDList()),
            "vehicle_ids": vehicles,
            "active_route_edges": active_route_edges,
            "flow_route_edges": set(self.flow_route_edges),
            "blocked_edges": blocked,
            "construction_closures": set(),
            "restricted_edges": {edge for edges_ in self.blocked_corridors.values() for edge in edges_},
        }

    def apply_edge_closure(self, edge_ids: list[str], closed: bool) -> dict[str, Any]:
        """Apply/restore lane permissions only after complete live preflight.

        Closure is rejected if any loaded route-backed future demand or active
        vehicle route uses a requested edge; this SUMO demand model has no safe
        runtime flow-route replacement API.
        """
        edge_ids = list(dict.fromkeys(edge_ids))
        if not edge_ids or any(not isinstance(edge, str) for edge in edge_ids):
            raise ValueError("edges must be a non-empty list of SUMO edge IDs")
        with self.traci_session():
            try:
                traci.simulation.getTime()
                traci_alive = True
            except Exception:
                traci_alive = False
            if not self.running or not traci_alive:
                return {"success": False, "status": "rejected", "operation": "edge_closure",
                        "reason_code": "SUMO_NOT_RUNNING", "message": "Live SUMO/TraCI session is unavailable",
                        "sumo_alive": bool(self.running), "traci_alive": traci_alive, "mutations": 0}
            context = self.optimizer_constraint_context()
            commands = [{"action_type": "operator_edge_control", "sumo_target_id": edge,
                         "parameters": {"blocked": closed}} for edge in edge_ids]
            validation = ConstraintEngine.validate_batch(commands, context)
            if not validation["valid"]:
                return {"success": False, "status": "rejected", "operation": "edge_closure",
                        "validation": validation, "mutations": 0}

            lane_ids = [f"{edge}_{index}" for edge in edge_ids
                        for index in range(traci.edge.getLaneNumber(edge))]
            if not lane_ids:
                return {"success": False, "status": "rejected", "operation": "edge_closure",
                        "reason_code": "NO_LANES", "message": "No live lanes found for requested edges",
                        "mutations": 0}
            classes = {traci.vehicletype.getVehicleClass(vtype)
                       for vtype in traci.vehicletype.getIDList()}
            classes.discard("")
            if closed and not classes:
                return {"success": False, "status": "rejected", "operation": "edge_closure",
                        "reason_code": "NO_VEHICLE_CLASSES", "message": "SUMO exposes no vehicle classes to restrict",
                        "mutations": 0}

            if closed:
                already_snapshotted = [edge for edge in edge_ids if edge in self.edge_closure_snapshots]
                if already_snapshotted:
                    return {"success": False, "status": "partial" if rollback_errors else "rejected",
                            "operation": "edge_closure",
                            "reason_code": "ALREADY_CLOSED_BY_OPERATOR",
                            "message": f"Edges already have an operator closure: {already_snapshotted}",
                            "mutations": 0}
                snapshots = {lane_id: {"allowed": list(traci.lane.getAllowed(lane_id)),
                                       "disallowed": list(traci.lane.getDisallowed(lane_id))}
                             for lane_id in lane_ids}
                preclosed = [edge for edge in edge_ids if all(
                    classes.issubset(set(traci.lane.getDisallowed(f"{edge}_{index}")))
                    for index in range(traci.edge.getLaneNumber(edge)))]
                if preclosed:
                    return {"success": False, "status": "rejected", "operation": "edge_closure",
                            "reason_code": "EDGE_ALREADY_RESTRICTED",
                            "message": f"Edges are already inaccessible; refusing to overwrite permission state: {preclosed}",
                            "mutations": 0}
                previous = {edge: self.edge_closure_snapshots.get(edge) for edge in edge_ids}
                try:
                    for lane_id in lane_ids:
                        traci.lane.setDisallowed(lane_id, sorted(classes))
                    readback = {lane_id: list(traci.lane.getDisallowed(lane_id)) for lane_id in lane_ids}
                    verified = all(classes.issubset(set(value)) for value in readback.values())
                    if not verified:
                        raise RuntimeError("Lane permission readback did not deny all loaded vehicle classes")
                    for edge in edge_ids:
                        self.edge_closure_snapshots[edge] = [
                            {"lane_id": lane, **snapshots[lane]}
                            for lane in lane_ids if lane.startswith(f"{edge}_")]
                    return {"success": True, "status": "success", "operation": "edge_closure",
                            "edges": edge_ids, "blocked_classes": sorted(classes),
                            "readback": readback, "sumo_alive": bool(self.running),
                            "traci_alive": True, "mutations": len(lane_ids)}
                except Exception as ex:
                    rollback_errors = []
                    for lane_id, state in snapshots.items():
                        try:
                            traci.lane.setAllowed(lane_id, state["allowed"])
                            traci.lane.setDisallowed(lane_id, state["disallowed"])
                        except Exception as rollback_ex:
                            rollback_errors.append({"lane_id": lane_id, "error": str(rollback_ex)})
                    for edge, state in previous.items():
                        if state is None:
                            self.edge_closure_snapshots.pop(edge, None)
                        else:
                            self.edge_closure_snapshots[edge] = state
                    return {"success": False, "status": "rejected", "operation": "edge_closure",
                            "reason_code": "APPLY_OR_READBACK_FAILED", "message": str(ex),
                            "rollback_errors": rollback_errors, "sumo_alive": bool(self.running),
                            "traci_alive": True, "mutations": len(lane_ids)}

            # Restore is accepted only for a closure created and snapshotted by
            # this controller; no guessed default permissions are applied.
            missing = [edge for edge in edge_ids if edge not in self.edge_closure_snapshots]
            if missing:
                return {"success": False, "status": "partial" if rollback_errors else "rejected",
                        "operation": "edge_restore",
                        "reason_code": "NO_PERMISSION_SNAPSHOT",
                        "message": f"No original live permission snapshot for {missing}", "mutations": 0}
            current = {lane_id: {"allowed": list(traci.lane.getAllowed(lane_id)),
                                 "disallowed": list(traci.lane.getDisallowed(lane_id))}
                       for lane_id in lane_ids}
            snapshots = {entry["lane_id"]: entry for edge in edge_ids
                         for entry in self.edge_closure_snapshots[edge]}
            try:
                for lane_id, state in snapshots.items():
                    traci.lane.setAllowed(lane_id, state["allowed"])
                    traci.lane.setDisallowed(lane_id, state["disallowed"])
                verified = all(list(traci.lane.getAllowed(lane_id)) == state["allowed"]
                               and list(traci.lane.getDisallowed(lane_id)) == state["disallowed"]
                               for lane_id, state in snapshots.items())
                if not verified:
                    raise RuntimeError("Restored lane permissions did not match saved live state")
                for edge in edge_ids:
                    self.edge_closure_snapshots.pop(edge, None)
                return {"success": True, "status": "success", "operation": "edge_restore",
                        "edges": edge_ids, "readback": "original_permissions_restored",
                        "sumo_alive": bool(self.running), "traci_alive": True,
                        "mutations": len(lane_ids)}
            except Exception as ex:
                rollback_errors = []
                for lane_id, state in current.items():
                    try:
                        traci.lane.setAllowed(lane_id, state["allowed"])
                        traci.lane.setDisallowed(lane_id, state["disallowed"])
                    except Exception as rollback_ex:
                        rollback_errors.append({"lane_id": lane_id, "error": str(rollback_ex)})
                return {"success": False, "status": "rejected", "operation": "edge_restore",
                        "reason_code": "RESTORE_OR_READBACK_FAILED", "message": str(ex),
                        "rollback_errors": rollback_errors, "sumo_alive": bool(self.running),
                        "traci_alive": True, "mutations": len(lane_ids)}

    def block_edges(self, edge_ids: list[str]) -> dict[str, Any]:
        """Block runtime entry by changing live lane permissions."""
        return self.apply_edge_closure(edge_ids, True)

    def restore_edges(self, edge_ids: list[str]) -> dict[str, Any]:
        """Restore permissions captured before this controller's live closure."""
        return self.apply_edge_closure(edge_ids, False)

    def network_signals(self) -> list[dict[str, Any]]:
        """Discover live TLS programs, phase classes and controlled links."""
        with self.traci_session():
            output = []
            now = float(traci.simulation.getTime())
            for tls_id in traci.trafficlight.getIDList():
                active_program = str(traci.trafficlight.getProgram(tls_id))
                try:
                    logics = traci.trafficlight.getAllProgramLogics(tls_id)
                except Exception:
                    logics = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
                active_logics = [logic for logic in logics if str(logic.programID) == active_program]
                if not active_logics:
                    active_logics = list(logics)
                phases = []
                for logic in active_logics:
                    for index, phase in enumerate(logic.phases):
                        state = str(phase.state)
                        classes = sorted({"green" if char in "gG" else "yellow" if char in "yY" else "red"
                                          for char in state})
                        min_duration, max_duration = float(phase.minDur), float(phase.maxDur)
                        phases.append({"program_id": str(logic.programID), "phase": index,
                                       "duration_s": float(phase.duration), "state": state,
                                       "signal_classes": classes, "min_duration_s": float(phase.minDur),
                                       "max_duration_s": float(phase.maxDur),
                                       "timing_supported": min_duration > 0 and max_duration > min_duration})
                try:
                    links = traci.trafficlight.getControlledLinks(tls_id)
                    controlled_links = [[{"incoming_lane": link[0], "outgoing_lane": link[1],
                                          "via_lane": link[2]} for link in group] for group in links]
                except Exception:
                    controlled_links = []
                state = traci.trafficlight.getRedYellowGreenState(tls_id)
                current_phase = int(traci.trafficlight.getPhase(tls_id))
                output.append({"tls_id": tls_id,
                               "program_id": active_program,
                               "current_phase": current_phase,
                               "current_phase_duration_s": float(traci.trafficlight.getPhaseDuration(tls_id)),
                               "next_switch": float(traci.trafficlight.getNextSwitch(tls_id)),
                               "seconds_to_switch": max(0.0, float(traci.trafficlight.getNextSwitch(tls_id)) - now),
                               "signal_state": state, "phase_count": len(phases),
                               "phases": phases, "controlled_links": controlled_links,
                               "supported_states": sorted({cls for phase in phases for cls in phase["signal_classes"]})})
            return output

    def set_signal_phase_duration(self, tls_id: str, phase_index: int, duration: float,
                                  activate: bool = False,
                                  requested_state: Optional[str] = None) -> dict[str, Any]:
        """Update one discovered phase duration transactionally and verify live logic."""
        with self.traci_session():
            ids = set(traci.trafficlight.getIDList())
            if tls_id not in ids:
                raise ValueError(f"Unknown traffic-light ID: {tls_id}")
            validation = ConstraintEngine.validate_batch([{
                "action_type": "signal_state" if activate else "signal_timing", "sumo_target_id": tls_id,
                "parameters": {"phase": phase_index, "duration_s": duration,
                               **({"state": requested_state} if activate else {})},
            }], {"tls_ids": ids})
            if not validation["valid"]:
                reasons = "; ".join(error["message"] for error in validation["errors"])
                raise ValueError(reasons)
            if isinstance(phase_index, bool) or not isinstance(phase_index, int) or phase_index < 0:
                raise ValueError("phase must be a non-negative integer")
            timing_config = operator_profiles()["signal_timing"]
            safe_min = float(timing_config["minimum_duration_s"])
            safe_max = float(timing_config["maximum_duration_s"])
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not safe_min <= duration <= safe_max:
                raise ValueError(f"Requested duration must be between {safe_min:g} and {safe_max:g} seconds")
            before = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
            snapshots = [[float(p.duration) for p in logic.phases] for logic in before]
            active_logic_index = next((i for i, logic in enumerate(before)
                                       if str(logic.programID) == str(traci.trafficlight.getProgram(tls_id))), None)
            if active_logic_index is None or phase_index >= len(before[active_logic_index].phases):
                raise ValueError(f"Phase {phase_index} is not present in the active TLS program")
            logic = before[active_logic_index]
            phase = logic.phases[phase_index]
            min_duration, max_duration = float(phase.minDur), float(phase.maxDur)
            fixed = min_duration <= 0 or max_duration <= 0 or abs(max_duration - min_duration) <= 1e-6
            if fixed and abs(float(duration) - float(phase.duration)) > 1e-6:
                raise ValueError("Signal duration is fixed by the active SUMO program")
            if duration < min_duration or duration > max_duration:
                raise ValueError("duration_s is outside the active phase min/max bounds")
            previous = float(phase.duration)
            try:
                phase.duration = float(duration)
                traci.trafficlight.setCompleteRedYellowGreenDefinition(tls_id, logic)
                if activate:
                    traci.trafficlight.setPhase(tls_id, phase_index)
                    traci.trafficlight.setPhaseDuration(tls_id, float(duration))
                actual_logic = next((item for item in traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
                                     if str(item.programID) == str(traci.trafficlight.getProgram(tls_id))), None)
                actual = float(actual_logic.phases[phase_index].duration) if actual_logic else None
                if actual is None or abs(actual - float(duration)) > 1e-5:
                    raise RuntimeError("SUMO readback did not match requested phase duration")
                if activate and (int(traci.trafficlight.getPhase(tls_id)) != phase_index
                                 or abs(float(traci.trafficlight.getPhaseDuration(tls_id)) - float(duration)) > 1e-5):
                    raise RuntimeError("SUMO did not activate and verify the requested signal phase")
            except Exception:
                for old_logic, durations in zip(before, snapshots):
                    for old_phase, old_duration in zip(old_logic.phases, durations):
                        old_phase.duration = old_duration
                    traci.trafficlight.setCompleteRedYellowGreenDefinition(tls_id, old_logic)
                raise
            return {"tls_id": tls_id, "phase": phase_index, "before_duration_s": previous,
                    "requested_duration_s": float(duration), "actual_duration_s": actual,
                    "current_phase": int(traci.trafficlight.getPhase(tls_id)),
                    "next_switch": float(traci.trafficlight.getNextSwitch(tls_id)),
                    "signal_state": traci.trafficlight.getRedYellowGreenState(tls_id),
                    "verified": True}

    def restore_signal_snapshot(self, tls_id: str, changed_phase: int, prior_phase_duration: float,
                                prior_active_phase: int, prior_active_duration: float) -> None:
        """Compensating restore for a paired signal-state transaction."""
        with self.traci_session():
            current_program = str(traci.trafficlight.getProgram(tls_id))
            logics = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
            logic = next((item for item in logics if str(item.programID) == current_program), None)
            if logic is None or changed_phase >= len(logic.phases) or prior_active_phase >= len(logic.phases):
                raise RuntimeError("Active signal program changed before rollback")
            logic.phases[changed_phase].duration = float(prior_phase_duration)
            traci.trafficlight.setCompleteRedYellowGreenDefinition(tls_id, logic)
            traci.trafficlight.setPhase(tls_id, int(prior_active_phase))
            traci.trafficlight.setPhaseDuration(tls_id, float(prior_active_duration))
            if (int(traci.trafficlight.getPhase(tls_id)) != int(prior_active_phase)
                    or abs(float(traci.trafficlight.getPhaseDuration(tls_id)) - float(prior_active_duration)) > 1e-5):
                raise RuntimeError("SUMO did not verify the restored signal phase")

    def snapshot_route_operation(self, source: str, alternative: Optional[str] = None) -> dict[str, Any]:
        names = [source] + ([alternative] if alternative else [])
        edge_ids = set()
        for name in names:
            if name not in CORRIDOR_MAP:
                raise ValueError(f"Unknown corridor: {name}")
            mapping = CORRIDOR_MAP[name]
            edge_ids.update(mapping.primary_sumo_edges + mapping.reverse_sumo_edges)
        with self.traci_session():
            if not edge_ids.issubset(set(traci.edge.getIDList())):
                raise ValueError("Route operation references edges absent from the live SUMO network")
            lanes = {}
            costs = {}
            for edge_id in edge_ids:
                costs[edge_id] = float(traci.edge.getAdaptedTraveltime(edge_id, self.sim_time))
                for index in range(traci.edge.getLaneNumber(edge_id)):
                    lane_id = f"{edge_id}_{index}"
                    lanes[lane_id] = {"allowed": list(traci.lane.getAllowed(lane_id)),
                                      "disallowed": list(traci.lane.getDisallowed(lane_id)),
                                      "speed": float(traci.lane.getMaxSpeed(lane_id))}
            vehicles = {}
            for vehicle_id in traci.vehicle.getIDList():
                try:
                    vehicles[vehicle_id] = tuple(traci.vehicle.getRoute(vehicle_id))
                except Exception:
                    continue
            return {"lanes": lanes, "costs": costs, "vehicles": vehicles,
                    "blocked_corridors": copy.deepcopy(self.blocked_corridors),
                    "adapted_edge_costs": copy.deepcopy(self.adapted_edge_costs)}

    @staticmethod
    def _restore_vehicle_destination(vehicle_id: str, saved_route: tuple[str, ...]) -> Optional[str]:
        """Safely restore a vehicle's destination from its current edge.

        A running SUMO vehicle may advance while its paired simulation is being
        rolled back. Replaying the captured full route can then start behind the
        vehicle (or duplicate its current edge) and SUMO rejects the command.
        Recalculate from the vehicle's live edge to the captured destination.
        """
        if not saved_route:
            return "snapshot route is empty"
        try:
            if vehicle_id not in traci.vehicle.getIDList():
                return None
            current_edge = str(traci.vehicle.getRoadID(vehicle_id))
            if not current_edge or current_edge.startswith(":"):
                # Internal junction lanes are transient. SUMO will continue to
                # the next external edge using the restored lane/cost state.
                return None
            destination = saved_route[-1]
            if current_edge == destination:
                return None
            vtype = traci.vehicle.getTypeID(vehicle_id)
            candidate = traci.simulation.findRoute(current_edge, destination, vType=vtype)
            edges = tuple(getattr(candidate, "edges", ()) or ())
            if not edges or edges[0] != current_edge or edges[-1] != destination:
                return f"no valid current-edge route to captured destination {destination}"
            if len(edges) > 1:
                traci.vehicle.setRoute(vehicle_id, list(edges))
            actual = tuple(traci.vehicle.getRoute(vehicle_id))
            if actual[-1:] != (destination,):
                return f"route readback did not retain destination {destination}"
            return None
        except Exception as ex:
            return str(ex)

    def restore_route_operation(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        failures = []
        with self.traci_session():
            for lane_id, state in snapshot.get("lanes", {}).items():
                try:
                    traci.lane.setAllowed(lane_id, state["allowed"])
                    traci.lane.setDisallowed(lane_id, state["disallowed"])
                    traci.lane.setMaxSpeed(lane_id, state["speed"])
                    if (list(traci.lane.getAllowed(lane_id)) != list(state["allowed"])
                            or list(traci.lane.getDisallowed(lane_id)) != list(state["disallowed"])
                            or abs(float(traci.lane.getMaxSpeed(lane_id)) - float(state["speed"])) > 1e-5):
                        raise RuntimeError("lane-state readback mismatch")
                except Exception as ex:
                    failures.append({"target": lane_id, "error": str(ex)})
            for edge_id, cost in snapshot.get("costs", {}).items():
                try:
                    traci.edge.adaptTraveltime(edge_id, cost)
                    if abs(float(traci.edge.getAdaptedTraveltime(edge_id, self.sim_time)) - float(cost)) > 1e-5:
                        raise RuntimeError("adapted travel-time readback mismatch")
                except Exception as ex:
                    failures.append({"target": edge_id, "error": str(ex)})
            for vehicle_id, route in snapshot.get("vehicles", {}).items():
                try:
                    if vehicle_id in traci.vehicle.getIDList() and tuple(traci.vehicle.getRoute(vehicle_id)) != route:
                        error = self._restore_vehicle_destination(vehicle_id, route)
                        if error:
                            failures.append({"target": vehicle_id, "error": error})
                except Exception as ex:
                    failures.append({"target": vehicle_id, "error": str(ex)})
        self.blocked_corridors = snapshot.get("blocked_corridors", {})
        self.adapted_edge_costs = snapshot.get("adapted_edge_costs", {})
        return failures

    def apply_route_control(self, source: str, alternative: Optional[str] = None,
                            diversion_percent: int = 0, blocked: bool = False) -> dict[str, Any]:
        if source not in CORRIDOR_MAP or (alternative is not None and alternative not in CORRIDOR_MAP):
            raise ValueError("Unknown source or alternative corridor")
        if source == alternative:
            raise ValueError("Source and alternative corridors must differ")
        if isinstance(diversion_percent, bool) or not isinstance(diversion_percent, int) or not 0 <= diversion_percent <= 100:
            raise ValueError("diversion_percent must be an integer from 0 to 100")
        source_map = CORRIDOR_MAP[source]
        corridor_edges = list(dict.fromkeys(source_map.primary_sumo_edges + source_map.reverse_sumo_edges))
        conflicting_flows = sorted(set(corridor_edges) & self.flow_route_edges)
        if blocked and conflicting_flows:
            raise ValueError(
                f"Cannot safely close {source}: active SUMO flow routes traverse {conflicting_flows}. "
                "Closing these lanes makes scheduled vehicles invalid and can terminate SUMO. "
                "Use route diversion or a scenario route-file change instead."
            )
        flow_origin_edges = set(corridor_edges) & self.route_origin_edges
        closure_edges = [edge for edge in corridor_edges if not blocked or edge not in flow_origin_edges]
        attempted = successful = failed = 0
        diagnostics = []
        changed_lanes = []
        errors = []

        def detail(item):
            if len(diagnostics) < 50:
                diagnostics.append(item)

        with self.traci_session():
            current_ids = set(traci.edge.getIDList())
            required_edges = set(corridor_edges)
            if alternative:
                alternative_map = CORRIDOR_MAP[alternative]
                required_edges.update(alternative_map.primary_sumo_edges + alternative_map.reverse_sumo_edges)
            missing_edges = sorted(required_edges - current_ids)
            if missing_edges:
                raise ValueError(f"Route operation rejected before mutation; edges are absent from SUMO: {missing_edges}")
            lane_snapshot = {}
            cost_snapshot = {}
            route_snapshot = {}
            for edge_id in required_edges:
                cost_snapshot[edge_id] = self.base_edge_travel_times.get(edge_id, float(traci.edge.getTraveltime(edge_id)))
                for lane_idx in range(traci.edge.getLaneNumber(edge_id)):
                    lane_id = f"{edge_id}_{lane_idx}"
                    lane_snapshot[lane_id] = {
                        "allowed": list(traci.lane.getAllowed(lane_id)),
                        "disallowed": list(traci.lane.getDisallowed(lane_id)),
                        "speed": float(traci.lane.getMaxSpeed(lane_id)),
                    }
            for vehicle_id in traci.vehicle.getIDList():
                try:
                    route_snapshot[vehicle_id] = tuple(traci.vehicle.getRoute(vehicle_id))
                except Exception:
                    continue
            for edge_id in closure_edges:
                for lane_idx in range(traci.edge.getLaneNumber(edge_id)):
                    lane_id = f"{edge_id}_{lane_idx}"
                    try:
                        if blocked:
                            # SUMO lane permissions prevent new entries while
                            # vehicles already on the lane can leave it.
                            classes = {traci.vehicletype.getVehicleClass(vtype)
                                       for vtype in traci.vehicletype.getIDList()}
                            classes.discard("")
                            if not classes:
                                raise RuntimeError("SUMO exposes no vehicle classes to close this lane safely")
                            traci.lane.setDisallowed(lane_id, sorted(classes))
                        else:
                            traci.lane.setAllowed(lane_id, self.base_lane_permissions.get(lane_id, []))
                            traci.lane.setDisallowed(lane_id, self.base_lane_disallowed.get(lane_id, []))
                            base_speed = self.lane_base_speed_limits.get(lane_id, 13.89)
                            constraints = self.scenario_inputs.get("constraints", {})
                            profiles = operator_profiles()
                            weather_profile = profiles["weather"].get(str(constraints.get("weather", "clear")).lower())
                            if weather_profile is None:
                                raise ValueError(f"Weather profile {constraints.get('weather')!r} is not configured")
                            weather_factor = float(weather_profile["speed_factor"])
                            construction = constraints.get("construction_enabled") and constraints.get("construction_corridor") == source
                            cap = float(profiles.get("construction", {})["speed_cap_mps"])
                            traci.lane.setMaxSpeed(lane_id, min(base_speed * weather_factor, cap) if construction else base_speed * weather_factor)
                        changed_lanes.append(lane_id)
                    except Exception as ex:
                        errors.append({"lane_id": lane_id, "error": str(ex)})

            edge_set = set(corridor_edges)
            self.blocked_corridors[source] = sorted(set(closure_edges)) if blocked else []
            for edge_id in corridor_edges:
                if edge_id not in current_ids:
                    continue
                try:
                    # Full blocking is represented by actual lane permissions
                    # above; route-cost inflation is not a closure mechanism.
                    if blocked:
                        continue
                    elif alternative:
                        cost = max(1.0, float(traci.edge.getTraveltime(edge_id)) *
                                   (1.0 + diversion_percent / 100.0))
                    else:
                        cost = self.base_edge_travel_times.get(edge_id, float(traci.edge.getTraveltime(edge_id)))
                        constraints = self.scenario_inputs.get("constraints", {})
                        if constraints.get("construction_enabled") and constraints.get("construction_corridor") == source:
                            cost *= float(operator_profiles().get("construction", {})["travel_time_factor"])
                        if constraints.get("vip_enabled") and constraints.get("vip_corridor") == source:
                            cost = max(1.0, cost * float(operator_profiles().get("vip", {})["travel_time_factor"]))
                    traci.edge.adaptTraveltime(edge_id, cost)
                    self.adapted_edge_costs[edge_id] = cost
                except Exception as ex:
                    errors.append({"edge_id": edge_id, "error": str(ex)})

            alternative_edges = set()
            if alternative:
                target_map = CORRIDOR_MAP[alternative]
                alternative_edges = set(target_map.primary_sumo_edges + target_map.reverse_sumo_edges)
                for edge_id in alternative_edges:
                    try:
                        base = float(traci.edge.getTraveltime(edge_id))
                        cost = max(1.0, base * max(0.35, 1.0 - diversion_percent / 100.0))
                        traci.edge.adaptTraveltime(edge_id, cost)
                        self.adapted_edge_costs[edge_id] = cost
                    except Exception as ex:
                        errors.append({"edge_id": edge_id, "error": str(ex)})

            # Vehicles on a closed segment are allowed to leave, but their
            # next route is recalculated against the new lane permissions and
            # high corridor travel cost.
            source_edges = edge_set
            for vehicle_id in traci.vehicle.getIDList():
                try:
                    current_edge = traci.vehicle.getRoadID(vehicle_id)
                except Exception as ex:
                    attempted += 1
                    failed += 1
                    detail({"vehicle_id": vehicle_id, "source_edge": None,
                            "target_route": alternative, "candidate_alternative": None,
                            "success": False, "failure_reason": str(ex)})
                    continue
                eligible = (current_edge in source_edges) if blocked else (current_edge in source_edges and diversion_percent > 0)
                if not eligible:
                    continue
                if not blocked and sum(ord(ch) for ch in vehicle_id) % 100 >= diversion_percent:
                    continue
                attempted += 1
                try:
                    old_route = tuple(traci.vehicle.getRoute(vehicle_id))
                    traci.vehicle.rerouteTraveltime(vehicle_id, True)
                    new_route = tuple(traci.vehicle.getRoute(vehicle_id))
                    route_left_source = any(edge in source_edges for edge in old_route) and not any(
                        edge in source_edges for edge in new_route[1:]
                    )
                    alt_candidate = any(edge in alternative_edges for edge in new_route) if alternative_edges else None
                    changed = new_route != old_route
                    if blocked:
                        success = (changed and route_left_source) or not any(edge in source_edges for edge in new_route[1:])
                    else:
                        success = changed and (alt_candidate if alternative_edges else True)
                    if success:
                        successful += 1
                    else:
                        failed += 1
                    detail({"vehicle_id": vehicle_id, "source_edge": current_edge,
                            "target_route": alternative, "candidate_alternative": alt_candidate,
                            "success": success,
                            "failure_reason": None if success else "SUMO retained the existing route or found no qualifying alternative"})
                except Exception as ex:
                    failed += 1
                    detail({"vehicle_id": vehicle_id, "source_edge": current_edge,
                            "target_route": alternative, "candidate_alternative": None,
                            "success": False, "failure_reason": str(ex)})

            expected_classes = {traci.vehicletype.getVehicleClass(vtype)
                                for vtype in traci.vehicletype.getIDList()}
            expected_classes.discard("")
            if blocked:
                readback_blocked = bool(changed_lanes) and all(
                    expected_classes.issubset(set(traci.lane.getDisallowed(lane_id)))
                    for lane_id in changed_lanes
                )
            else:
                readback_blocked = bool(changed_lanes) and all(
                    list(traci.lane.getDisallowed(lane_id)) == self.base_lane_disallowed.get(lane_id, [])
                    for lane_id in changed_lanes
                )

            rollback = bool(errors or failed or not readback_blocked)
            if rollback:
                rollback_errors = []
                for lane_id, previous in lane_snapshot.items():
                    try:
                        traci.lane.setAllowed(lane_id, previous["allowed"])
                        traci.lane.setDisallowed(lane_id, previous["disallowed"])
                        traci.lane.setMaxSpeed(lane_id, previous["speed"])
                    except Exception as ex:
                        rollback_errors.append({"lane_id": lane_id, "error": str(ex)})
                for edge_id, previous in cost_snapshot.items():
                    try:
                        traci.edge.adaptTraveltime(edge_id, previous)
                    except Exception as ex:
                        rollback_errors.append({"edge_id": edge_id, "error": str(ex)})
                for vehicle_id, previous_route in route_snapshot.items():
                    try:
                        if tuple(traci.vehicle.getRoute(vehicle_id)) != previous_route:
                            error = self._restore_vehicle_destination(vehicle_id, previous_route)
                            if error:
                                rollback_errors.append({"vehicle_id": vehicle_id, "error": error})
                    except Exception as ex:
                        rollback_errors.append({"vehicle_id": vehicle_id, "error": str(ex)})
                errors.extend({"rollback": item} for item in rollback_errors)
                self.blocked_corridors[source] = []
                changed_lanes = []
                readback_blocked = False

        self.operator_readback["route_restriction"] = {
            "corridor": source, "blocked": bool(blocked),
            "sumo_readback_confirmed": readback_blocked,
            "lanes": changed_lanes,
            "protected_flow_origin_edges": sorted(flow_origin_edges) if blocked else [],
        }
        return {"source": source, "alternative": alternative, "blocked": blocked,
                "restriction_mode": ("partial_lane_closure_protecting_scheduled_departures"
                                      if blocked and flow_origin_edges else
                                      "lane_entry_prohibited" if blocked else "lane_permissions_restored"),
                "lanes_updated": len(changed_lanes), "attempted": attempted,
                "successful": successful, "failed": failed, "diagnostics": diagnostics,
                "errors": errors, "readback_confirmed": readback_blocked,
                "rolled_back": rollback,
                "new_entries_blocked": bool(blocked and readback_blocked and not flow_origin_edges),
                "protected_flow_origin_edges": sorted(flow_origin_edges) if blocked else []}

    def _apply_initial_inputs(self):
        """Apply shared operator inputs to this real SUMO connection at start."""
        constraints = self.scenario_inputs.get("constraints", {})
        profiles = operator_profiles()
        weather_profile = profiles["weather"].get(str(constraints.get("weather", "clear")).lower())
        if weather_profile is None:
            raise ValueError(f"Weather profile {constraints.get('weather')!r} is not configured")
        weather_factor = float(weather_profile["speed_factor"])
        weather_readback = []
        for edge_id, speed in self.edge_speed_limits.items():
            for lane_idx in range(traci.edge.getLaneNumber(edge_id)):
                lane_id = f"{edge_id}_{lane_idx}"
                expected = self.lane_base_speed_limits.get(lane_id, speed) * weather_factor
                traci.lane.setMaxSpeed(lane_id, expected)
                if len(weather_readback) < 20:
                    weather_readback.append({"lane_id": lane_id, "expected_mps": expected,
                                             "actual_mps": float(traci.lane.getMaxSpeed(lane_id))})
        self.operator_readback = {
            "weather": {"input": constraints.get("weather", "clear"),
                        "speed_factor": weather_factor, "lanes": weather_readback,
                        "verified": all(abs(x["actual_mps"] - x["expected_mps"]) < 1e-5 for x in weather_readback)}
        }

        if constraints.get("construction_enabled"):
            corridor = constraints.get("construction_corridor")
            mapping = CORRIDOR_MAP.get(corridor)
            if mapping:
                changed = []
                costs = []
                construction_config = profiles.get("construction", {})
                for edge_id in mapping.primary_sumo_edges + mapping.reverse_sumo_edges:
                    if edge_id not in self.edge_speed_limits:
                        raise ValueError(f"Construction edge {edge_id} is not present in SUMO")
                    for lane_idx in range(traci.edge.getLaneNumber(edge_id)):
                        lane_id = f"{edge_id}_{lane_idx}"
                        base = self.lane_base_speed_limits.get(lane_id, self.edge_speed_limits.get(edge_id, 13.89))
                        expected = min(base * weather_factor, float(construction_config["speed_cap_mps"]))
                        traci.lane.setMaxSpeed(lane_id, expected)
                        changed.append({"lane_id": lane_id, "expected_mps": expected,
                                        "actual_mps": float(traci.lane.getMaxSpeed(lane_id))})
                    base_cost = self.base_edge_travel_times.get(edge_id, float(traci.edge.getTraveltime(edge_id)))
                    expected_cost = base_cost * float(construction_config["travel_time_factor"])
                    traci.edge.adaptTraveltime(edge_id, expected_cost)
                    costs.append({"edge_id": edge_id, "expected_s": expected_cost,
                                  "actual_s": float(traci.edge.getAdaptedTraveltime(edge_id, self.sim_time))})
                self.operator_readback["construction"] = {
                    "enabled": True, "corridor": corridor, "lanes": changed,
                    "edge_costs": costs,
                    "verified": bool(changed) and all(abs(x["actual_mps"] - x["expected_mps"]) < 1e-5 for x in changed)
                    and all(abs(x["actual_s"] - x["expected_s"]) < 1e-3 for x in costs)}
            else:
                raise ValueError(f"Construction corridor {corridor!r} is not mapped")
        else:
            self.operator_readback["construction"] = {"enabled": False, "verified": True}

        vip_corridor = constraints.get("vip_corridor") if constraints.get("vip_enabled") else None
        vip_mapping = CORRIDOR_MAP.get(vip_corridor)
        if vip_mapping:
            # A lower adapted travel-time cost marks the selected VIP corridor
            # as preferred in SUMO's routing cost table for both synchronized runs.
            costs = []
            for edge_id in vip_mapping.primary_sumo_edges:
                if edge_id not in self.edge_speed_limits:
                    raise ValueError(f"VIP corridor edge {edge_id} is not present in SUMO")
                base = self.base_edge_travel_times.get(edge_id, float(traci.edge.getTraveltime(edge_id)))
                expected = max(1.0, base * float(profiles.get("vip", {})["travel_time_factor"]))
                traci.edge.adaptTraveltime(edge_id, expected)
                actual = float(traci.edge.getAdaptedTraveltime(edge_id, self.sim_time))
                costs.append({"edge_id": edge_id, "before_s": base, "expected_s": expected, "actual_s": actual})
            self.operator_readback["vip"] = {"enabled": True, "corridor": vip_corridor,
                                                "edges": costs,
                                                "verified": bool(costs) and all(abs(x["actual_s"] - x["expected_s"]) < 1e-3 for x in costs)}
        else:
            self.operator_readback["vip"] = {"enabled": False, "verified": True}

        for junction, timing in self.scenario_inputs.get("signal_timings", {}).items():
            mapping = JUNCTION_MAP[junction]
            tls_id = mapping.sumo_tls_id
            try:
                logics = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
                before = [[float(phase.duration) for phase in logic.phases] for logic in logics]
                represented = set()
                for logic in logics:
                    for phase in logic.phases:
                        state = phase.state.lower()
                        if "g" in state:
                            represented.add("green")
                            phase.duration = float(timing["green"])
                        elif "y" in state:
                            represented.add("yellow")
                            phase.duration = float(timing["yellow"])
                        else:
                            represented.add("red")
                            phase.duration = float(timing["red"])
                    traci.trafficlight.setCompleteRedYellowGreenDefinition(tls_id, logic)
                actual_logics = traci.trafficlight.getCompleteRedYellowGreenDefinition(tls_id)
                actual = [[float(phase.duration) for phase in logic.phases] for logic in actual_logics]
                expected = [[float(phase.duration) for phase in logic.phases] for logic in logics]
                self.operator_readback.setdefault("signals", {})[junction] = {
                    "sumo_id": tls_id, "before_phase_durations_s": before,
                    "requested": timing, "actual_phase_durations_s": actual,
                    "represented_phase_classes": sorted(represented),
                    "unsupported_timings": sorted(set(timing) - represented),
                    "verified": actual == expected and set(timing).issubset(represented)}
            except Exception as ex:
                raise ValueError(f"Could not configure signal {junction} ({tls_id}): {ex}") from ex
