
"""
classical_optimizer.py

Exact classical optimization using exhaustive search.

Searches every feasible binary combination while
respecting operational constraints.

Run:
    python optimization/classical_optimizer.py
"""

from pathlib import Path
import json
import time
import numpy as np
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from optimization.qubo_builder import build_qubo

RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ----------------------------------------------------
# Constraint Check
# ----------------------------------------------------

def feasible(bits):

    # x1-x4 : max 2 diversions
    if bits[:4].sum() > 2:
        return False

    # x5-x14 : max 5 signals
    if bits[4:14].sum() > 5:
        return False

    # x15-x18 : max 1 restriction
    if bits[14:].sum() > 1:
        return False

    return True

# ----------------------------------------------------
# Objective
# ----------------------------------------------------

def objective(Q, bits):

    return float(bits @ Q @ bits)

# ----------------------------------------------------
# Exhaustive Search
# ----------------------------------------------------

def solve_classically():

    Q, variables = build_qubo()

    n = len(variables)

    best_value = float("inf")
    best_bits = None

    start = time.time()

    for state in range(1 << n):

        bits = np.array(
            [(state >> i) & 1 for i in range(n)],
            dtype=np.int8
        )

        if not feasible(bits):
            continue

        value = objective(Q, bits)

        if value < best_value:

            best_value = value
            best_bits = bits.copy()

    runtime = time.time() - start

    return variables, best_bits, best_value, runtime

# ----------------------------------------------------
# Save
# ----------------------------------------------------

def save_result(variables, bits, value, runtime):

    bitstring = ""

    values = {}

    for variable, bit in zip(variables, bits):

        values[variable.id] = int(bit)
        bitstring += str(int(bit))

    with open(RESULTS_DIR / "classical_bitstring.txt", "w") as f:
        f.write(bitstring)

    with open(RESULTS_DIR / "classical_solution.json", "w") as f:

        json.dump({
            "mode": "classical_exhaustive",
            "runtime_seconds": runtime,
            "objective_value": value,
            "bitstring": bitstring,
            "variables": values
        }, f, indent=4)

    return bitstring

# ----------------------------------------------------
# Main
# ----------------------------------------------------

if __name__ == "__main__":

    variables, bits, value, runtime = solve_classically()

    bitstring = save_result(
        variables,
        bits,
        value,
        runtime
    )

    print("\nExact Classical Optimization Complete")
    print("-------------------------------------")

    print(f"Runtime         : {runtime:.4f} s")
    print(f"Objective Value : {value}")
    print(f"Bitstring       : {bitstring}")

    print("\nSelected Variables")

    for variable, bit in zip(variables, bits):

        if bit:
            print(f"{variable.id:<4}{variable.target}")

    print("\nSaved")

    print(RESULTS_DIR / "classical_solution.json")
    print(RESULTS_DIR / "classical_bitstring.txt")