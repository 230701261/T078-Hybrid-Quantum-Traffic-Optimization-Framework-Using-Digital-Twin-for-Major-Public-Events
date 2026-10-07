
"""
quadratic_program_builder.py

Converts the scenario-aware QUBO matrix into a constrained
Quadratic Program.

Run:
    python optimization/quadratic_program_builder.py
"""

from pathlib import Path
import numpy as np
import sys

from qiskit_optimization import QuadraticProgram

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from optimization.qubo_builder import build_qubo

RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ----------------------------------------------------
# Build Quadratic Program
# ----------------------------------------------------

def build_quadratic_program():

    Q, variables = build_qubo()

    qp = QuadraticProgram("ChepaukTrafficOptimization")

    # Binary variables
    for var in variables:
        qp.binary_var(var.id)

    linear = {}
    quadratic = {}

    for i, var_i in enumerate(variables):

        linear[var_i.id] = float(Q[i, i])

        for j in range(i + 1, len(variables)):

            value = float(Q[i, j])

            if abs(value) > 1e-9:

                quadratic[(var_i.id, variables[j].id)] = value

    qp.minimize(
        linear=linear,
        quadratic=quadratic,
        constant=0
    )

    # ------------------------------------------------
    # Operational Constraints
    # ------------------------------------------------

    # Maximum two corridor diversions
    qp.linear_constraint(
        linear={
            "x1": 1,
            "x2": 1,
            "x3": 1,
            "x4": 1
        },
        sense="<=",
        rhs=2,
        name="max_two_diversions"
    )

    # Maximum five signal extensions
    qp.linear_constraint(
        linear={
            "x5": 1,
            "x6": 1,
            "x7": 1,
            "x8": 1,
            "x9": 1,
            "x10": 1,
            "x11": 1,
            "x12": 1,
            "x13": 1,
            "x14": 1
        },
        sense="<=",
        rhs=5,
        name="max_five_signals"
    )

    # Maximum one temporary restriction
    qp.linear_constraint(
        linear={
            "x15": 1,
            "x16": 1,
            "x17": 1,
            "x18": 1
        },
        sense="<=",
        rhs=1,
        name="max_one_restriction"
    )

    np.save(RESULTS_DIR / "qubo_matrix.npy", Q)
    np.savetxt(RESULTS_DIR / "qubo_matrix.csv", Q, delimiter=",")

    with open(RESULTS_DIR / "ising_summary.txt", "w") as f:

        f.write("Scenario-Aware QUBO Summary\n")
        f.write("==========================\n\n")
        f.write(f"Variables: {len(variables)}\n")
        f.write(f"Quadratic Terms: {len(quadratic)}\n")
        f.write("Constraints:\n")
        f.write("- Max 2 route diversions\n")
        f.write("- Max 5 signal extensions\n")
        f.write("- Max 1 temporary restriction\n")

    return qp, variables

# ----------------------------------------------------
# Standalone Test
# ----------------------------------------------------

if __name__ == "__main__":

    qp, variables = build_quadratic_program()

    print("\nQuadratic Program Built Successfully")
    print("------------------------------------")

    print(f"Binary Variables : {len(variables)}")
    print(f"Quadratic Terms  : {len(qp.objective.quadratic.to_dict())}")
    print(f"Linear Terms     : {len(qp.objective.linear.to_dict())}")
    print(f"Constraints      : {qp.get_num_linear_constraints()}")

    print("\nOperational Constraints")
    print("- Maximum 2 route diversions")
    print("- Maximum 5 signal extensions")
    print("- Maximum 1 temporary restriction")

    print("\nArtifacts Saved")
    print("----------------")
    print(RESULTS_DIR / "qubo_matrix.npy")
    print(RESULTS_DIR / "qubo_matrix.csv")
    print(RESULTS_DIR / "ising_summary.txt")