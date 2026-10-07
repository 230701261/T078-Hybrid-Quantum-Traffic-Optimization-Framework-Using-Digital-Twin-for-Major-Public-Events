"""
sumo_exporter.py

Exports the optimized traffic plan into a SUMO-ready JSON.
Synchronizes 1:1 with final_traffic_plan.json and scenario_input.json,
ensuring all corridors, signals, restrictions, and benefits are fully exported.

Input:
    results/final_traffic_plan.json
    scenario/scenario_input.json

Output:
    results/sumo_input.json

Run:
    python optimization/sumo_exporter.py
"""

from pathlib import Path
import json

# -------------------------------------------------------
# Paths
# -------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

RESULTS_DIR = BASE_DIR / "results"
SCENARIO_DIR = BASE_DIR / "scenario"

PLAN_FILE = RESULTS_DIR / "final_traffic_plan.json"
SCENARIO_FILE = SCENARIO_DIR / "scenario_input.json"

OUTPUT_FILE = RESULTS_DIR / "sumo_input.json"

# -------------------------------------------------------
# Helper
# -------------------------------------------------------

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

# -------------------------------------------------------
# Build SUMO Export
# -------------------------------------------------------

def build_export(plan_override=None, scenario_override=None):

    plan = plan_override if plan_override is not None else load_json(PLAN_FILE)
    scenario = scenario_override if scenario_override is not None else load_json(SCENARIO_FILE)

    # -------------------------------
    # Scenario Information
    # -------------------------------

    export = {

        "scenario": {

            "event": plan["event"]["name"],
            "venue": plan["event"]["venue"],
            "total_vehicles": plan["event"]["total_vehicles"],

            "weather": plan.get(
                "weather",
                scenario["constraints"]["weather"]
            ),

            "vip": scenario["constraints"]["vip"],
            "construction": scenario["constraints"]["construction"],
            "crowd_surge": scenario["constraints"]["crowd_surge"],
            "parking_overflow": scenario["constraints"]["parking_overflow"]
        },

        "optimizer": {

            "method": plan.get("optimizer_used", "Unknown"),
            "bitstring": plan.get("bitstring", "")
        },

        "rerouting": [],

        "signal_updates": [],

        "restrictions": [],

        "estimated_benefits": {

            "travel_time_saved_minutes":
                plan["benefits"]["travel_time_saved_minutes"],

            "queue_reduction_percent":
                plan["benefits"]["queue_reduction_percent"]
        }
    }

    # -------------------------------
    # Corridor Rerouting
    # -------------------------------

    for corridor in plan.get("corridors", []):

        if corridor.get("enabled", False):

            export["rerouting"].append({

                "corridor":
                    corridor["corridor"],

                "enabled":
                    True,

                "demand":
                    corridor["demand"],

                "capacity":
                    corridor["capacity"],

                "pressure":
                    corridor["pressure"],

                "overflow":
                    corridor["overflow"],

                "rerouted_vehicles":
                    corridor["rerouted"],

                "remaining_queue":
                    corridor["remaining_queue"]
            })

    # -------------------------------
    # Signal Updates
    # -------------------------------

    for signal in plan.get("signal_changes", []):

        export["signal_updates"].append({

            "junction":
                signal["junction"],

            "old_green":
                signal["old_green"],

            "new_green":
                signal["new_green"],

            "extra_green":
                signal["extra_green"]
        })

    # -------------------------------
    # Restrictions (Fixed & Populated)
    # -------------------------------

    for restr in plan.get("restrictions", []):

        export["restrictions"].append({

            "corridor":
                restr["corridor"],

            "type":
                restr.get("type", "temporary_restriction")
        })

    # -------------------------------
    # Save
    # -------------------------------

    with open(OUTPUT_FILE, "w") as f:
        json.dump(export, f, indent=4)

    return export

# -------------------------------------------------------
# Main
# -------------------------------------------------------

if __name__ == "__main__":

    export = build_export()

    print("\nSUMO Export Complete")
    print("---------------------")

    print(f"Optimizer : {export['optimizer']['method']}")
    print(f"Bitstring : {export['optimizer']['bitstring']}")

    print(f"\nRerouting Actions : {len(export['rerouting'])}")
    print(f"Signal Updates    : {len(export['signal_updates'])}")
    print(f"Restrictions      : {len(export['restrictions'])}")

    print("\nSaved")
    print(OUTPUT_FILE)