
"""
problem_builder.py

Creates the OptimizationProblem object used by the
entire traffic optimization pipeline.

Single source of truth:
    scenario/scenario_input.json
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List
import json
import sys

# =====================================================
# Paths
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
SCENARIO_FILE = BASE_DIR / "scenario" / "scenario_input.json"
ROADS_FILE = BASE_DIR / "data" / "roads.json"
JUNCTION_FILE = BASE_DIR / "data" / "junction_mapping.json"
CORRIDOR_FILE = BASE_DIR / "data" / "corridors.json"

# =====================================================
# Data Structure
# =====================================================

@dataclass
class OptimizationProblem:
    event: Dict
    demand: Dict
    roads: List
    junctions: Dict
    corridors: Dict
    constraints: Dict
    signal_limits: Dict

# =====================================================
# Helpers
# =====================================================

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

# =====================================================
# Capacity Estimation
# =====================================================

def estimate_capacity(road):
    """
    Estimate vehicles/hour capacity from OSM road type.
    """

    if "capacity" in road:
        return int(road["capacity"])

    highway = str(road.get("highway", "secondary")).lower()

    lanes = road.get("lanes", 2)

    try:
        lanes = int(str(lanes).split(";")[0])
    except:
        lanes = 2

    base_capacity = {
        "motorway": 2200,
        "trunk": 1800,
        "primary": 1500,
        "secondary": 1200,
        "tertiary": 900,
        "residential": 600,
        "service": 400
    }

    per_lane = base_capacity.get(highway, 1000)

    return per_lane * max(lanes, 1)

# =====================================================
# Capacity Adjustment
# =====================================================


def adjust_capacity(capacity, constraints):

    from scenario.scenario_profiles import (
        SCENARIO_PROFILES,
        SPECIAL_CONDITIONS
    )

    weather = constraints.get("weather", "Clear")

    profile = SCENARIO_PROFILES[weather]

    capacity *= profile["capacity_multiplier"]

    for condition, values in SPECIAL_CONDITIONS.items():

        if constraints.get(condition, False):

            capacity *= values["capacity_multiplier"]

    return int(capacity)

# =====================================================
# Signal Limits
# =====================================================

def build_signal_limits(constraints):

    limits = {
        "min_green": 30,
        "max_green": 60,
        "yellow": 5
    }

    if constraints.get("vip"):
        limits["max_green"] = 70

    if constraints.get("construction"):
        limits["min_green"] = 25

    return limits

# =====================================================
# Build Problem
# =====================================================

def build_problem():

    scenario = load_json(SCENARIO_FILE)

    roads = load_json(ROADS_FILE)
    junctions = load_json(JUNCTION_FILE)
    corridors = load_json(CORRIDOR_FILE)

    constraints = scenario["constraints"]

    updated_roads = []

    for road in roads:

        r = road.copy()

        base_capacity = estimate_capacity(r)

        r["capacity"] = adjust_capacity(base_capacity, constraints)

        updated_roads.append(r)

    signal_limits = build_signal_limits(constraints)

    return OptimizationProblem(
        event=scenario["event"],
        demand=scenario["intersections"],
        roads=updated_roads,
        junctions=junctions,
        corridors=corridors,
        constraints=constraints,
        signal_limits=signal_limits
    )

# =====================================================
# Standalone Test
# =====================================================

if __name__ == "__main__":

    problem = build_problem()

    print("\nOptimization Problem Built Successfully")
    print("---------------------------------------")

    print(f"Event: {problem.event['name']}")
    print(f"Venue: {problem.event['venue']}")
    print(f"Total Vehicles: {problem.event['total_vehicles']}")

    print("\nDemand Distribution")

    for junction, demand in problem.demand.items():
        print(f"{junction}: {demand}")

    print("\nActive Constraints")

    for key, value in problem.constraints.items():
        print(f"{key:<18}{value}")

    print("\nSignal Limits")
    print(problem.signal_limits)

    capacities = [r["capacity"] for r in problem.roads]

    print(f"\nRoads Loaded: {len(problem.roads)}")
    print(f"Junctions Loaded: {len(problem.junctions)}")
    print(f"Corridors Loaded: {len(problem.corridors)}")
    print(f"Average Road Capacity: {sum(capacities)//len(capacities)} vehicles/hour")