"""
interaction_builder.py

Builds a network-derived interaction matrix using the
existing corridors.json structure.

Run:
    python optimization/interaction_builder.py
"""

from pathlib import Path
import sys
import json
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
OPT_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(OPT_DIR) not in sys.path:
    sys.path.insert(0, str(OPT_DIR))

from decision_variables import generate_variables
from problem_builder import build_problem

# =====================================================
# Paths
# =====================================================

CORRIDOR_FILE = BASE_DIR / "data" / "corridors.json"

# =====================================================
# Load Corridors
# =====================================================

def load_corridors():

    with open(CORRIDOR_FILE, "r") as f:
        return json.load(f)

# =====================================================
# Corridor Connectivity
# =====================================================

def corridor_connectivity():

    corridors = load_corridors()

    connectivity = {}

    names = list(corridors.keys())

    for i in range(len(names)):
        for j in range(i + 1, len(names)):

            c1 = corridors[names[i]]
            c2 = corridors[names[j]]

            # Number of extracted segments
            size1 = len(c1)
            size2 = len(c2)

            # Similar-sized corridors interact more strongly
            similarity = min(size1, size2) / max(size1, size2)

            score = round(similarity * 6)

            connectivity[(names[i], names[j])] = score
            connectivity[(names[j], names[i])] = score

    return connectivity

# =====================================================
# Signal Importance
# =====================================================

def signal_importance(problem):

    maximum = max(problem.demand.values())

    importance = {}

    for junction, demand in problem.demand.items():

        importance[junction] = demand / maximum

    return importance

# =====================================================
# Build Interaction Matrix
# =====================================================

def build_interaction_matrix():

    variables = generate_variables()

    problem = build_problem()

    connectivity = corridor_connectivity()

    demand = signal_importance(problem)

    n = len(variables)

    matrix = np.zeros((n, n))

    for i in range(n):

        for j in range(i + 1, n):

            v1 = variables[i]
            v2 = variables[j]

            weight = 0

            # --------------------------------------------
            # Route ↔ Route
            # --------------------------------------------

            if (
                v1.category == "route_diversion"
                and v2.category == "route_diversion"
            ):

                shared = connectivity.get((v1.target, v2.target), 1)

                weight = -(3 + shared)

            # --------------------------------------------
            # Route ↔ Signal
            # --------------------------------------------

            elif (
                "route_diversion" in (v1.category, v2.category)
                and "signal_extension" in (v1.category, v2.category)
            ):

                signal = (
                    v1.target
                    if v1.category == "signal_extension"
                    else v2.target
                )

                weight = -(2 + round(demand.get(signal, 0.3) * 5))

            # --------------------------------------------
            # Signal ↔ Signal
            # --------------------------------------------

            elif (
                v1.category == "signal_extension"
                and v2.category == "signal_extension"
            ):

                d1 = demand.get(v1.target, 0.3)
                d2 = demand.get(v2.target, 0.3)

                weight = -(1 + round((d1 + d2)))

            # --------------------------------------------
            # Restrictions
            # --------------------------------------------

            elif (
                "temporary_restriction"
                in (v1.category, v2.category)
            ):

                weight = 4

            matrix[i, j] = weight
            matrix[j, i] = weight

    return matrix, variables

# =====================================================
# Standalone Test
# =====================================================

if __name__ == "__main__":

    matrix, variables = build_interaction_matrix()

    print("\nNetwork-Derived Interaction Matrix")
    print("------------------------------------")

    print(f"Variables : {len(variables)}")
    print(f"Matrix Size: {matrix.shape}")

    print("\nTop-left 8×8 Matrix\n")

    print(matrix[:8, :8])

    print("\nRoute Interaction Weights")

    routes = [
        v for v in variables
        if v.category == "route_diversion"
    ]

    for i in range(len(routes)):
        for j in range(i + 1, len(routes)):

            idx1 = variables.index(routes[i])
            idx2 = variables.index(routes[j])

            print(
                f"{routes[i].target:22}"
                f"{routes[j].target:22}"
                f"{matrix[idx1, idx2]:>6.1f}"
            )