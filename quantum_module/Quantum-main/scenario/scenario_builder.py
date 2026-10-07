
"""
scenario_builder.py

Creates and updates the planning scenario
used by the entire optimization pipeline.

Run:
    python scenario/scenario_builder.py
"""

from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent
SCENARIO_FILE = BASE_DIR / "scenario" / "scenario_input.json"

# =====================================================
# Default Scenario
# =====================================================

SCENARIO = {
    "event": {
        "name": "IPL Match",
        "venue": "MA Chidambaram Stadium",
        "total_vehicles": 9515
    },

    "constraints": {
        "weather": "Clear",
        "vip": False,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },

    "intersections": {
        "J1": 1200,
        "J2": 1447,
        "J3": 600,
        "J4": 1100,
        "J5": 450
    }
}

# =====================================================
# Save
# =====================================================

def save():

    SCENARIO_FILE.parent.mkdir(exist_ok=True)

    with open(SCENARIO_FILE, "w") as f:
        json.dump(SCENARIO, f, indent=4)

    return SCENARIO

# =====================================================
# Main
# =====================================================

if __name__ == "__main__":

    scenario = save()

    print("\nScenario Created")
    print("---------------------------")

    print(f"Event : {scenario['event']['name']}")
    print(f"Venue : {scenario['event']['venue']}")
    print(f"Vehicles : {scenario['event']['total_vehicles']}")

    print("\nConstraints")

    for key, value in scenario["constraints"].items():
        print(f"{key:<18}{value}")

    print("\nSaved")
    print(SCENARIO_FILE)