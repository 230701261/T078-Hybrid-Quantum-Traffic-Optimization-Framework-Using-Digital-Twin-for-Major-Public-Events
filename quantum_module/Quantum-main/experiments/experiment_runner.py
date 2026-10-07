"""
experiment_runner.py

Runs multiple traffic scenarios and records the results for
research comparison.

Output:
    experiments/scenario_results.csv
"""

from pathlib import Path
import json
import pandas as pd
import subprocess
import sys

BASE = Path(__file__).resolve().parent.parent

PROBLEM = BASE / "optimization" / "problem_builder.py"
PIPELINE = BASE / "pipeline" / "pipeline_controller.py"

RESULTS = BASE / "results"
CSV = BASE / "experiments" / "scenario_results.csv"

# -------------------------------------------------------
# Scenarios
# -------------------------------------------------------

SCENARIOS = [

    {
        "name": "S1_Clear",
        "weather": "Clear",
        "vip": False,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": True
    },

    {
        "name": "S2_Rain",
        "weather": "Heavy Rain",
        "vip": False,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },

    {
        "name": "S3_VIP",
        "weather": "Clear",
        "vip": True,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },

    {
        "name": "S4_Construction",
        "weather": "Clear",
        "vip": False,
        "construction": True,
        "crowd_surge": False,
        "parking_overflow": False
    },

    {
        "name": "S5_Combined",
        "weather": "Heavy Rain",
        "vip": True,
        "construction": True,
        "crowd_surge": True,
        "parking_overflow": True
    }

]

# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def update_problem_builder(scenario):
    """
    Replace scenario values inside problem_builder.py.
    """

    text = PROBLEM.read_text()

    replacements = {
        '"weather": "Clear"': f'"weather": "{scenario["weather"]}"',
        '"weather": "Heavy Rain"': f'"weather": "{scenario["weather"]}"',

        '"vip": False': f'"vip": {str(scenario["vip"])}',
        '"vip": True': f'"vip": {str(scenario["vip"])}',

        '"construction": False': f'"construction": {str(scenario["construction"])}',
        '"construction": True': f'"construction": {str(scenario["construction"])}',

        '"crowd_surge": False': f'"crowd_surge": {str(scenario["crowd_surge"])}',
        '"crowd_surge": True': f'"crowd_surge": {str(scenario["crowd_surge"])}',

        '"parking_overflow": False': f'"parking_overflow": {str(scenario["parking_overflow"])}',
        '"parking_overflow": True': f'"parking_overflow": {str(scenario["parking_overflow"])}'
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    PROBLEM.write_text(text)


def metric(section, key):
    """
    Safely read a metric from comparison_report.json.
    """

    data = json.load(open(RESULTS / "comparison_report.json"))

    if section not in data:
        raise KeyError(section)

    if key not in data[section]:
        raise KeyError(f"{section} missing key '{key}'")

    return data[section][key]

# -------------------------------------------------------
# Run Experiments
# -------------------------------------------------------

rows = []

for scenario in SCENARIOS:

    print(f"\nRunning {scenario['name']}")

    update_problem_builder(scenario)

    subprocess.run(
        [sys.executable, str(PIPELINE)],
        check=True
    )

    rows.append({

        "Scenario": scenario["name"],
        "Weather": scenario["weather"],
        "VIP": scenario["vip"],
        "Construction": scenario["construction"],
        "CrowdSurge": scenario["crowd_surge"],

        "GreedyObj": metric("Greedy", "qubo_objective"),
        "ClassicalObj": metric("Classical", "qubo_objective"),
        "QuantumObj": metric("Quantum", "qubo_objective"),

        "GreedyTravel": metric("Greedy", "travel_saved_min"),
        "ClassicalTravel": metric("Classical", "travel_saved_min"),
        "QuantumTravel": metric("Quantum", "travel_saved_min"),

        "GreedyQueue": metric("Greedy", "queue_reduction_percent"),
        "ClassicalQueue": metric("Classical", "queue_reduction_percent"),
        "QuantumQueue": metric("Quantum", "queue_reduction_percent"),

        "GreedyRuntime": metric("Greedy", "runtime"),
        "ClassicalRuntime": metric("Classical", "runtime"),
        "QuantumRuntime": metric("Quantum", "runtime")

    })

# -------------------------------------------------------
# Save CSV
# -------------------------------------------------------

df = pd.DataFrame(rows)

CSV.parent.mkdir(exist_ok=True)

df.to_csv(CSV, index=False)

print("\nExperiment Suite Complete")
print("-------------------------")
print(df)
print(f"\nSaved:\n{CSV}")