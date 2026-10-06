"""Validation and SUMO route-file scaling for operator-configured scenarios."""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
import math
import json
from pathlib import Path
from typing import Any

from .config import EVENT_CFG, NORMAL_CFG

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
    optimization = profiles.get("optimization", {})
    for name in ("route_priority_multiplier", "restriction_speed_factor", "signal_extension_max_s"):
        factor = optimization.get(name)
        if (isinstance(factor, bool) or not isinstance(factor, (int, float))
                or not math.isfinite(float(factor)) or float(factor) <= 0):
            raise ValueError(f"Invalid optimization profile value {name!r}")
    for group, names in {"construction": ("speed_cap_mps", "travel_time_factor"),
                         "vip": ("travel_time_factor",)}.items():
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
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output
