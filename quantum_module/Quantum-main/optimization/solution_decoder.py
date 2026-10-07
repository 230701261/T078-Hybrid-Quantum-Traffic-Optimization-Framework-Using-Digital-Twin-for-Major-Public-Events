
"""
solution_decoder.py

Converts the optimization bitstring into a
Traffic Authority Action Plan.

Outputs:
    results/
        quantum_output.json
        traffic_action_plan.json
"""

from pathlib import Path
import json

from decision_variables import generate_variables
from problem_builder import build_problem

# =====================================================
# Paths
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent

RESULTS_DIR = BASE_DIR / "results"

BITSTRING_FILE = RESULTS_DIR / "qaoa_bitstring.txt"

# =====================================================
# Load Solution
# =====================================================

def load_bitstring():

    with open(BITSTRING_FILE, "r") as f:

        return f.read().strip()

# =====================================================
# Decode
# =====================================================

def decode_solution():

    variables = generate_variables()
    problem = build_problem()

    bitstring = load_bitstring()

    actions = []

    signal_changes = []

    reroutes = []

    restrictions = []

    for bit, variable in zip(bitstring, variables):

        enabled = bit == "1"

        if variable.category == "route_diversion":

            reroutes.append({
                "corridor": variable.target,
                "enabled": enabled,
                "vehicles_redirected": 700 if enabled else 0
            })

        elif variable.category == "signal_extension":

            signal_changes.append({
                "junction": variable.target,
                "before_green": 30,
                "after_green": 45 if enabled else 30
            })

        elif variable.category == "temporary_restriction":

            restrictions.append({
                "corridor": variable.target,
                "enabled": enabled
            })

        actions.append({
            "variable": variable.id,
            "description": variable.description,
            "enabled": enabled
        })

    output = {

        "event": problem.event,

        "rerouting": reroutes,

        "signal_changes": signal_changes,

        "road_restrictions": restrictions,

        "actions": actions
    }

    return output

# =====================================================
# Save
# =====================================================

def save_output(output):

    with open(RESULTS_DIR / "quantum_output.json", "w") as f:

        json.dump(output, f, indent=4)

    with open(RESULTS_DIR / "traffic_action_plan.json", "w") as f:

        json.dump(output["actions"], f, indent=4)

# =====================================================
# Main
# =====================================================

if __name__ == "__main__":

    output = decode_solution()

    save_output(output)

    print("\nTraffic Action Plan Generated")
    print("--------------------------------")

    print(f"Rerouting Decisions : {len(output['rerouting'])}")
    print(f"Signal Changes      : {len(output['signal_changes'])}")
    print(f"Road Restrictions   : {len(output['road_restrictions'])}")

    print("\nEnabled Reroutes")

    for r in output["rerouting"]:

        if r["enabled"]:

            print(
                f"✓ {r['corridor']} "
                f"({r['vehicles_redirected']} vehicles)"
            )

    print("\nSignal Timing")

    for s in output["signal_changes"][:5]:

        print(
            f"{s['junction']}: "
            f"{s['before_green']}s → {s['after_green']}s"
        )

    print("\nSaved Files")

    print(RESULTS_DIR / "quantum_output.json")
    print(RESULTS_DIR / "traffic_action_plan.json")