"""
validation_report.py

Automatically validates optimization outputs for the
Chepauk Quantum Traffic Optimization project.

Run:
    python experiments/validation_report.py
"""

from pathlib import Path
import json

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"

FINAL_PLAN = RESULTS / "final_traffic_plan.json"
SUMO = RESULTS / "sumo_input.json"
COMPARE = RESULTS / "comparison_report.json"
QAOA = RESULTS / "qaoa_solution.json"


# --------------------------------------------------
# Helper
# --------------------------------------------------

def load_json(path):
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


checks = []

plan = load_json(FINAL_PLAN)
sumo = load_json(SUMO)
compare = load_json(COMPARE)
qaoa = load_json(QAOA)


# --------------------------------------------------
# File existence
# --------------------------------------------------

checks.append(("Traffic Plan Exists", plan is not None))
checks.append(("SUMO Export Exists", sumo is not None))
checks.append(("Comparison Report Exists", compare is not None))
checks.append(("Quantum Solution Exists", qaoa is not None))


if plan:

    # ----------------------------------------------
    # Corridor limit
    # ----------------------------------------------

    enabled_corridors = sum(
        c["enabled"] for c in plan.get("corridors", [])
    )

    checks.append((
        f"Route Diversions ({enabled_corridors}/2)",
        enabled_corridors <= 2
    ))

    # ----------------------------------------------
    # Signal limit
    # ----------------------------------------------

    signal_changes = len(plan.get("signal_changes", []))

    checks.append((
        f"Signal Extensions ({signal_changes}/5)",
        signal_changes <= 5
    ))

    # ----------------------------------------------
    # Restriction limit
    # ----------------------------------------------

    restrictions = 0

    if "restrictions" in plan:
        restrictions = len(plan["restrictions"])

    checks.append((
        f"Road Restrictions ({restrictions}/1)",
        restrictions <= 1
    ))


# --------------------------------------------------
# Bitstring consistency
# --------------------------------------------------

if plan and qaoa:

    plan_bits = plan.get("bitstring")
    qaoa_bits = qaoa.get("bitstring")

    checks.append((
        "Bitstring Match",
        plan_bits == qaoa_bits
    ))


# --------------------------------------------------
# Print Report
# --------------------------------------------------

print("\nValidation Report")
print("=================\n")

passed = 0

for name, ok in checks:

    status = "PASS" if ok else "FAIL"

    print(f"{status:<5} {name}")

    if ok:
        passed += 1

print("\n-----------------")
print(f"Passed {passed}/{len(checks)} checks")

if passed == len(checks):
    print("All validation checks passed.")
else:
    print("Some checks require attention.")