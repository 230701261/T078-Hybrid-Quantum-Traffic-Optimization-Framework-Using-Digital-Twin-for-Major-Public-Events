"""
comparison_engine.py

Research-grade comparison of:

- Greedy
- Exact Classical
- Lightweight QAOA

All methods are evaluated using the SAME QUBO objective.

Run:
    python optimization/comparison_engine.py
"""

from pathlib import Path
import json
import numpy as np

from qubo_builder import build_qubo

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS = BASE_DIR / "results"

# ----------------------------------------------------
# Load JSON
# ----------------------------------------------------

def load(filename):

    with open(RESULTS / filename, "r") as f:
        return json.load(f)

# ----------------------------------------------------
# Evaluate xᵀQx
# ----------------------------------------------------

def evaluate_qubo(bitstring, Q):

    x = np.array([int(b) for b in bitstring])

    return float(x @ Q @ x)

# ----------------------------------------------------
# Count actions
# ----------------------------------------------------

def counts(bitstring):

    corridor = sum(int(b) for b in bitstring[:4])
    signal = sum(int(b) for b in bitstring[4:14])
    restriction = sum(int(b) for b in bitstring[14:])

    return corridor, signal, restriction

# ----------------------------------------------------
# Estimated traffic benefit
# ----------------------------------------------------

def estimated_benefits(corridors, signals):

    travel = round(corridors * 1.2 + signals * 0.22, 1)
    queue = round(corridors * 2 + signals, 1)

    return travel, queue

# ----------------------------------------------------
# Runtime helper
# ----------------------------------------------------

def runtime(solution):

    if "runtime_seconds" in solution:
        return round(solution["runtime_seconds"], 4)

    if "runtime" in solution:
        return round(solution["runtime"], 4)

    return None

# ----------------------------------------------------
# Build report
# ----------------------------------------------------

def build_report():

    Q, _ = build_qubo()

    greedy = load("greedy_solution.json")
    classical = load("classical_solution.json")
    quantum = load("qaoa_solution.json")

    report = {}

    for name, solution in [
        ("Greedy", greedy),
        ("Classical", classical),
        ("Quantum", quantum)
    ]:

        bitstring = solution["bitstring"]

        objective = evaluate_qubo(bitstring, Q)

        c, s, r = counts(bitstring)

        travel, queue = estimated_benefits(c, s)

        report[name] = {
            "runtime": runtime(solution),
            "qubo_objective": round(objective, 2),
            "bitstring": bitstring,
            "corridors": c,
            "signals": s,
            "restrictions": r,
            "travel_saved_min": travel,
            "queue_reduction_percent": queue
        }

    with open(RESULTS / "comparison_report.json", "w") as f:
        json.dump(report, f, indent=4)

    return report

# ----------------------------------------------------
# Print
# ----------------------------------------------------

if __name__ == "__main__":

    report = build_report()

    print("\nResearch Comparison Complete")
    print("--------------------------------")

    for name in ["Greedy", "Classical", "Quantum"]:

        r = report[name]

        print(f"\n{name}")

        print(f"Runtime        : {r['runtime']} s")
        print(f"QUBO Objective : {r['qubo_objective']}")
        print(f"Bitstring      : {r['bitstring']}")
        print(f"Corridors      : {r['corridors']}")
        print(f"Signals        : {r['signals']}")
        print(f"Restrictions   : {r['restrictions']}")
        print(f"Travel Saved   : {r['travel_saved_min']} min")
        print(f"Queue Reduced  : {r['queue_reduction_percent']}%")

    print("\nSaved")
    print(RESULTS / "comparison_report.json")