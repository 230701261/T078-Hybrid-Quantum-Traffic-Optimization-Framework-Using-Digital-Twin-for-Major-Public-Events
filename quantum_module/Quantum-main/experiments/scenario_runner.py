"""
scenario_runner.py

Runs multiple traffic scenarios automatically and stores
a consolidated experiment report.

Run:
    python experiments/scenario_runner.py
"""

from pathlib import Path
import json
import subprocess
import sys
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

SCENARIO_FILE = BASE_DIR / "scenario" / "scenario_input.json"
RESULTS_DIR = BASE_DIR / "results"
EXPERIMENT_DIR = BASE_DIR / "experiments"

EXPERIMENT_DIR.mkdir(exist_ok=True)

SCENARIOS = [
    {
        "id": "S1",
        "weather": "Clear",
        "vip": False,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },
    {
        "id": "S2",
        "weather": "Heavy Rain",
        "vip": False,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },
    {
        "id": "S3",
        "weather": "Clear",
        "vip": True,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },
    {
        "id": "S4",
        "weather": "Heavy Rain",
        "vip": True,
        "construction": False,
        "crowd_surge": False,
        "parking_overflow": False
    },
    {
        "id": "S5",
        "weather": "Heavy Rain",
        "vip": False,
        "construction": ["Wallajah Road"],
        "crowd_surge": False,
        "parking_overflow": False
    },
    {
        "id": "S6",
        "weather": "Heavy Rain",
        "vip": True,
        "construction": ["Wallajah Road"],
        "crowd_surge": True,
        "parking_overflow": True
    }
]


def write_scenario(config):

    with open(SCENARIO_FILE) as f:
        data = json.load(f)

    data["constraints"]["weather"] = config["weather"]
    data["constraints"]["vip"] = config["vip"]
    data["constraints"]["construction"] = config["construction"]
    data["constraints"]["crowd_surge"] = config["crowd_surge"]
    data["constraints"]["parking_overflow"] = config["parking_overflow"]

    with open(SCENARIO_FILE, "w") as f:
        json.dump(data, f, indent=2)


def run_pipeline():

    subprocess.run(
        [sys.executable, "pipeline/pipeline_controller.py"],
        cwd=BASE_DIR,
        check=True
    )


def load_results():

    with open(RESULTS_DIR / "comparison_report.json") as f:
        return json.load(f)


rows = []

print("\nRunning Scenario Experiments")
print("-----------------------------")

for scenario in SCENARIOS:

    print(f"\n{scenario['id']}  {scenario['weather']}")

    write_scenario(scenario)

    run_pipeline()

    report = load_results()

    rows.append({
        "Scenario": scenario["id"],
        "Weather": scenario["weather"],
        "VIP": scenario["vip"],
        "Construction": bool(scenario["construction"]),
        "CrowdSurge": scenario["crowd_surge"],
        "GreedyObj": report["Greedy"]["qubo_objective"],
        "ClassicalObj": report["Classical"]["qubo_objective"],
        "QuantumObj": report["Quantum"]["qubo_objective"],
        "GreedyTravel": report["Greedy"]["travel_saved_min"],
        "ClassicalTravel": report["Classical"]["travel_saved_min"],
        "QuantumTravel": report["Quantum"]["travel_saved_min"]
    })

df = pd.DataFrame(rows)

csv_path = EXPERIMENT_DIR / "scenario_results.csv"

df.to_csv(csv_path, index=False)

print("\nAll Experiments Complete")
print("------------------------")
print(df)

print("\nSaved")
print(csv_path)