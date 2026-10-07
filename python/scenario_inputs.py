"""Validation and SUMO route-file scaling for operator-configured scenarios."""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
import math
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import EVENT_CFG, NET_FILE, NORMAL_CFG

MODE_TYPES = {
    "cars": {"car", "taxi"},
    "buses": {"bus"},
    "two_wheelers": {"motorcycle"},
    "local_trains": {"train"},
    "pedestrians": {"ped_stadium", "ped_beach", "ped_local"},
}
DEMAND_BOUNDS = {
    "cars": (0, 10000), "buses": (0, 1000), "two_wheelers": (0, 10000),
    "pedestrians": (0, 20000), "local_trains": (0, 1000),
}


class RouteValidationError(ValueError):
    """Raised before SUMO starts when a demand route is invalid."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        self.code = "ROUTE_INVALID"
        errors = report.get("errors", [])
        first = errors[0] if errors else {}
        detail = first.get("message", "unknown route validation failure")
        super().__init__(f"[ROUTE_INVALID] {detail}")


@lru_cache(maxsize=4)
def load_sumo_route_topology(net_file: str = NET_FILE) -> dict[str, Any]:
    """Read real edge endpoints, lane permissions, and SUMO lane connections."""
    root = ET.parse(net_file).getroot()
    edges: dict[str, dict[str, Any]] = {}
    for edge in root.findall("edge"):
        if edge.get("function") in {"internal", "crossing", "walkingarea"}:
            continue
        lanes = []
        for lane in edge.findall("lane"):
            allow = lane.get("allow")
            lanes.append({
                "allow": set(allow.split()) if allow is not None else None,
                "disallow": set(lane.get("disallow", "").split()),
            })
        edges[edge.get("id")] = {"from": edge.get("from"), "to": edge.get("to"), "lanes": lanes}

    connections: dict[tuple[str, str], list[tuple[int | None, int | None]]] = {}
    for connection in root.findall("connection"):
        source, target = connection.get("from"), connection.get("to")
        if source not in edges or target not in edges:
            continue
        pair = (source, target)
        connections.setdefault(pair, []).append((
            int(connection.get("fromLane")) if connection.get("fromLane") is not None else None,
            int(connection.get("toLane")) if connection.get("toLane") is not None else None,
        ))
    return {"edges": edges, "connections": connections}


def _lane_permits(lane: dict[str, Any], vehicle_class: str) -> bool:
    allow = lane["allow"]
    return (vehicle_class not in lane["disallow"] and
            (allow is None or vehicle_class in allow))


def validate_route(route_edges: list[str], net: dict[str, Any] | str = NET_FILE,
                   vehicle_class: str = "passenger", route_id: str | None = None) -> dict[str, Any]:
    """Validate edge existence, class access, node continuity and real lane links."""
    topology = load_sumo_route_topology(str(net)) if isinstance(net, (str, Path)) else net
    errors: list[dict[str, Any]] = []
    prefix = {"route_id": route_id, "vehicle_class": vehicle_class}
    if not route_edges:
        errors.append({**prefix, "code": "EMPTY_ROUTE", "message": f"Route {route_id or '<unnamed>'} has no edges"})
        return {"valid": False, "errors": errors}

    for edge_id in route_edges:
        edge = topology["edges"].get(edge_id)
        if edge is None:
            errors.append({**prefix, "code": "UNKNOWN_EDGE", "edge": edge_id,
                           "message": f"Route {route_id or '<unnamed>'} references unknown SUMO edge {edge_id}"})
        elif not any(_lane_permits(lane, vehicle_class) for lane in edge["lanes"]):
            errors.append({**prefix, "code": "VEHICLE_CLASS_FORBIDDEN", "edge": edge_id,
                           "message": f"Vehicle class {vehicle_class!r} is not permitted on SUMO edge {edge_id}"})

    for source, target in zip(route_edges, route_edges[1:]):
        from_edge, to_edge = topology["edges"].get(source), topology["edges"].get(target)
        if from_edge is None or to_edge is None:
            continue
        if from_edge["to"] != to_edge["from"]:
            errors.append({**prefix, "code": "NODE_DISCONNECT", "from_edge": source, "to_edge": target,
                           "message": f"No node continuity from {source} (to {from_edge['to']}) to {target} (from {to_edge['from']})"})
            continue
        # SUMO person walks may transfer across pedestrian-accessible edges
        # sharing a node without a vehicle <connection> record.
        if vehicle_class == "pedestrian":
            continue
        links = topology["connections"].get((source, target), [])
        connected = False
        for from_lane, to_lane in links:
            from_lanes, to_lanes = from_edge["lanes"], to_edge["lanes"]
            if ((from_lane is not None and from_lane >= len(from_lanes)) or
                    (to_lane is not None and to_lane >= len(to_lanes))):
                continue
            candidates_from = [from_lanes[from_lane]] if from_lane is not None else from_lanes
            candidates_to = [to_lanes[to_lane]] if to_lane is not None else to_lanes
            if any(_lane_permits(a, vehicle_class) for a in candidates_from) and any(
                    _lane_permits(b, vehicle_class) for b in candidates_to):
                connected = True
                break
        if not connected:
            errors.append({**prefix, "code": "NO_SUMO_CONNECTION", "from_edge": source, "to_edge": target,
                           "message": f"No SUMO lane connection for {vehicle_class} from {source} to {target}"})
    return {"valid": not errors, "route_id": route_id, "vehicle_class": vehicle_class,
            "edge_count": len(route_edges), "errors": errors}


def validate_route_file(route_file: str | Path, net_file: str = NET_FILE) -> dict[str, Any]:
    """Validate every vehicle route and pedestrian walk in a SUMO demand file."""
    root = ET.parse(route_file).getroot()
    topology = load_sumo_route_topology(str(net_file))
    type_classes = {item.get("id"): item.get("vClass", "passenger") for item in root.findall("vType")}
    routes = {item.get("id"): item.get("edges", "").split() for item in root.findall("route")}
    route_classes: dict[str, set[str]] = {route_id: set() for route_id in routes}
    errors: list[dict[str, Any]] = []

    for demand in root:
        if demand.tag in {"flow", "vehicle"}:
            route_id = demand.get("route")
            if route_id not in routes:
                errors.append({"code": "UNKNOWN_ROUTE", "vehicle_id": demand.get("id"), "route_id": route_id,
                               "message": f"Demand {demand.get('id')} references unknown route {route_id}"})
                continue
            vehicle_class = type_classes.get(demand.get("type"), "passenger")
            route_classes[route_id].add(vehicle_class)
        elif demand.tag == "personFlow":
            vehicle_class = type_classes.get(demand.get("type"), "pedestrian")
            for walk in demand.findall("walk"):
                report = validate_route(walk.get("edges", "").split(), topology, vehicle_class, demand.get("id"))
                errors.extend(report["errors"])

    for route_id, edges in routes.items():
        for vehicle_class in route_classes[route_id] or {"passenger"}:
            report = validate_route(edges, topology, vehicle_class, route_id)
            errors.extend(report["errors"])
    return {"valid": not errors, "route_file": str(route_file), "errors": errors}


def validate_scenario_routes(scenario: str) -> dict[str, Any]:
    route_file = config_routes_path(scenario)
    report = validate_route_file(route_file)
    report["scenario"] = scenario
    if not report["valid"]:
        raise RouteValidationError(report)
    return report


def operator_profiles() -> dict[str, Any]:
    """Load explicit, editable operator-effect profiles from project config."""
    path = Path(__file__).with_name("operator_profiles.json")
    with path.open("r", encoding="utf-8") as handle:
        profiles = json.load(handle)
    if not isinstance(profiles, dict) or not isinstance(profiles.get("weather"), dict):
        raise ValueError(f"Invalid operator profile configuration: {path}")
    for weather, values in profiles["weather"].items():
        factor = values.get("speed_factor")
        if (isinstance(factor, bool) or not isinstance(factor, (int, float))
                or not math.isfinite(float(factor)) or not 0 < float(factor) <= 1):
            raise ValueError(f"Invalid speed_factor for weather profile {weather!r}")
    route_settings = profiles.get("route_operations", {})
    route_values = [route_settings.get(name) for name in ("diversion_min", "diversion_max", "diversion_step")]
    if (any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
            for value in route_values) or route_values[0] < 0 or route_values[1] > 100
            or route_values[0] >= route_values[1] or route_values[2] <= 0
            or not isinstance(route_settings.get("eligible_vehicle_classes"), list)
            or not route_settings.get("eligible_vehicle_classes")
            or any(not isinstance(value, str) or not value for value in route_settings["eligible_vehicle_classes"])
            or isinstance(route_settings.get("near_destination_remaining_edges"), bool)
            or not isinstance(route_settings.get("near_destination_remaining_edges"), int)
            or route_settings["near_destination_remaining_edges"] < 0):
        raise ValueError("Invalid route_operations configuration")
    default_share = route_settings.get("default_diversion_share")
    if (isinstance(default_share, bool) or not isinstance(default_share, (int, float))
            or not route_values[0] <= float(default_share) <= route_values[1]
            or abs((float(default_share) - float(route_values[0])) / float(route_values[2])
                   - round((float(default_share) - float(route_values[0])) / float(route_values[2]))) > 1e-7):
        raise ValueError("Invalid default_diversion_share in route_operations configuration")
    for group, values in (("route_operations", route_settings), ("construction", profiles.get("construction", {})),
                          ("vip", profiles.get("vip", {}))):
        options = values.get("duration_options")
        default = values.get("default_duration_seconds")
        if (not isinstance(options, list) or not options
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(float(value)) or float(value) <= 0 for value in options)
                or isinstance(default, bool) or not isinstance(default, (int, float))
                or float(default) not in {float(value) for value in options}):
            raise ValueError(f"Invalid configured duration options for {group}")
    signal_settings = profiles.get("signal_timing", {})
    signal_min, signal_max = signal_settings.get("minimum_duration_s"), signal_settings.get("maximum_duration_s")
    if (any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
            for value in (signal_min, signal_max)) or signal_min <= 0 or signal_min >= signal_max
            or "phase_duration" not in signal_settings.get("supported_operations", [])):
        raise ValueError("Invalid signal_timing configuration")
    optimization = profiles.get("optimization", {})
    for name in ("route_priority_multiplier", "restriction_speed_factor", "signal_extension_max_s"):
        factor = optimization.get(name)
        if (isinstance(factor, bool) or not isinstance(factor, (int, float))
                or not math.isfinite(float(factor)) or float(factor) <= 0):
            raise ValueError(f"Invalid optimization profile value {name!r}")
    for group, names in {"construction": ("speed_cap_mps", "travel_time_factor", "default_duration_seconds"),
                         "vip": ("travel_time_factor", "default_duration_seconds")}.items():
        values = profiles.get(group)
        if not isinstance(values, dict):
            raise ValueError(f"Missing operator profile section {group!r}")
        for name in names:
            factor = values.get(name)
            if (isinstance(factor, bool) or not isinstance(factor, (int, float))
                or not math.isfinite(float(factor)) or float(factor) <= 0):
                raise ValueError(f"Invalid operator profile value {group}.{name}")
    return profiles


def config_routes_path(scenario: str) -> Path:
    config_path = Path(EVENT_CFG if scenario == "event_day" else NORMAL_CFG)
    root = ET.parse(config_path).getroot()
    route_value = root.find("./input/route-files")
    route_value = route_value.get("value") if route_value is not None else None
    if not route_value:
        raise ValueError(f"SUMO config {config_path.name} does not specify route-files")
    return (config_path.parent / route_value.split(",")[0].strip()).resolve()


def _flow_rate(node: ET.Element) -> float:
    if node.get("vehsPerHour") is not None:
        return float(node.get("vehsPerHour", "0"))
    if node.get("personsPerHour") is not None:
        return float(node.get("personsPerHour", "0"))
    period = float(node.get("period", "3600"))
    return 3600.0 / period if period > 0 else 0.0


def default_density(scenario: str) -> dict[str, int]:
    root = ET.parse(config_routes_path(scenario)).getroot()
    result = {key: 0.0 for key in MODE_TYPES}
    for node in root:
        mode = next((name for name, types in MODE_TYPES.items() if node.get("type") in types), None)
        if mode and node.tag in {"flow", "personFlow"}:
            result[mode] += _flow_rate(node)
    return {key: int(round(value)) for key, value in result.items()}


def validate_density(value: Any, scenario: str) -> dict[str, int]:
    defaults = default_density(scenario)
    supplied = value or {}
    result = {}
    for mode, (minimum, maximum) in DEMAND_BOUNDS.items():
        raw = supplied.get(mode, defaults[mode])
        if (isinstance(raw, bool) or not isinstance(raw, (int, float))
                or not math.isfinite(float(raw)) or int(raw) != raw):
            raise ValueError(f"Traffic density '{mode}' must be an integer")
        if not minimum <= int(raw) <= maximum:
            raise ValueError(f"Traffic density '{mode}' must be between {minimum} and {maximum}")
        result[mode] = int(raw)
    unknown = set(supplied) - set(DEMAND_BOUNDS)
    if unknown:
        raise ValueError(f"Unknown traffic density fields: {sorted(unknown)}")
    return result


def make_route_variant(scenario: str, density: dict[str, int]) -> Path:
    """Scale existing SUMO flow definitions; routes/topology remain authoritative."""
    source = config_routes_path(scenario)
    validate_scenario_routes(scenario)
    tree = ET.parse(source)
    root = tree.getroot()
    nodes_by_mode: dict[str, list[ET.Element]] = {key: [] for key in MODE_TYPES}
    originals: dict[str, list[float]] = {key: [] for key in MODE_TYPES}
    for node in root:
        mode = next((name for name, types in MODE_TYPES.items() if node.get("type") in types), None)
        if mode and node.tag in {"flow", "personFlow"}:
            nodes_by_mode[mode].append(node)
            originals[mode].append(_flow_rate(node))

    for mode, nodes in nodes_by_mode.items():
        if not nodes:
            if density[mode]:
                raise ValueError(f"SUMO route file has no flows for configured mode '{mode}'")
            continue
        original_total = sum(originals[mode])
        target_total = density[mode]
        for node, original in zip(nodes, originals[mode]):
            share = (target_total * original / original_total) if original_total else 0.0
            node.attrib.pop("period", None)
            if node.tag == "personFlow":
                node.set("personsPerHour", f"{share:.6f}")
            else:
                node.set("vehsPerHour", f"{share:.6f}")

    handle = tempfile.NamedTemporaryFile(prefix=f"chepauk_{scenario}_", suffix=".rou.xml", delete=False)
    handle.close()
    output = Path(handle.name)
    try:
        tree.write(output, encoding="utf-8", xml_declaration=True)
        report = validate_route_file(output)
        if not report["valid"]:
            raise RouteValidationError(report)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output
