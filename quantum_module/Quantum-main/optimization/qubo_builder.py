"""
qubo_builder.py

Builds a scenario-aware QUBO matrix for the Chepauk
traffic optimization project.

Diagonal values consider:

- Corridor demand
- Weather-adjusted capacity
- Signal importance
- Implementation cost
- Scenario penalties

Run:
    python optimization/qubo_builder.py
"""

from pathlib import Path
import sys
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
OPT_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(OPT_DIR) not in sys.path:
    sys.path.insert(0, str(OPT_DIR))

from objective_builder import build_objective
from interaction_builder import build_interaction_matrix
from decision_variables import generate_variables
from problem_builder import build_problem
from constraint_compiler import penalty_dictionary

# ---------------------------------------------------
# Corridor Mapping
# ---------------------------------------------------

CORRIDOR_DEMAND = {
    "Anna Salai": "J1",
    "Triplicane High Road": "J2",
    "Wallajah Road": "J4",
    "Kamarajar Salai": "J3"
}

# ---------------------------------------------------
# Signal Priority
# ---------------------------------------------------

SIGNAL_PRIORITY = {
    "J1": 1.00,
    "J2": 1.20,
    "J3": 0.60,
    "J4": 1.10,
    "J5": 0.70,
    "J6": 0.40,
    "J7": 0.30,
    "J8": 0.20,
    "J9": 0.10,
    "J10": 0.05
}

# ---------------------------------------------------
# Implementation Cost
# ---------------------------------------------------

IMPLEMENTATION_COST = {
    "route_diversion": 8,
    "signal_extension": 3,
    "temporary_restriction": 12
}

# ---------------------------------------------------
# Capacity Model
# ---------------------------------------------------

def average_capacity(problem):

    capacities = [road["capacity"] for road in problem.roads]

    return sum(capacities) / len(capacities)

# ---------------------------------------------------
# Corridor Pressure
# ---------------------------------------------------

def corridor_pressure(problem):

    avg_capacity = average_capacity(problem)

    pressure = {}

    for corridor, junction in CORRIDOR_DEMAND.items():

        demand = problem.demand.get(junction, 500)

        pressure[corridor] = demand / max(avg_capacity, 1)

    return pressure

# ---------------------------------------------------
# Diagonal Weight
# ---------------------------------------------------

def diagonal_weight(variable, pressure):

    if variable.category == "route_diversion":

        p = pressure.get(variable.target, 0.30)

        benefit = p * 60

        return round(-benefit + IMPLEMENTATION_COST[variable.category], 2)

    elif variable.category == "signal_extension":

        priority = SIGNAL_PRIORITY.get(variable.target, 0.20)

        benefit = priority * 15

        return round(-benefit + IMPLEMENTATION_COST[variable.category], 2)

    else:

        return IMPLEMENTATION_COST[variable.category]


# ---------------------------------------------------
# Constraint Penalty Encoding
# ---------------------------------------------------

ROUTE_PENALTY = 20
SIGNAL_PENALTY = 12
RESTRICTION_PENALTY = 25

def add_constraint_penalties(Q, variables):

    index = {v.id: i for i, v in enumerate(variables)}

    groups = [

        (["x1","x2","x3","x4"],2,ROUTE_PENALTY),

        (["x5","x6","x7","x8","x9",
          "x10","x11","x12","x13","x14"],5,SIGNAL_PENALTY),

        (["x15","x16","x17","x18"],1,RESTRICTION_PENALTY)
    ]

    for ids, limit, lam in groups:

        # Diagonal contribution
        for var in ids:

            i = index[var]

            Q[i,i] += lam*(1-2*limit)

        # Pairwise interaction
        for a in range(len(ids)):

            for b in range(a+1,len(ids)):

                i = index[ids[a]]
                j = index[ids[b]]

                Q[i,j] += 2*lam
                Q[j,i] += 2*lam

    return Q


# ---------------------------------------------------
# Build QUBO
# ---------------------------------------------------


def build_qubo():

    problem = build_problem()

    interaction, variables = build_interaction_matrix()

    pressure = corridor_pressure(problem)

    penalties = penalty_dictionary()

    Q = interaction.copy()

    # -----------------------------------------
    # Base diagonal values
    # -----------------------------------------

    for i, variable in enumerate(variables):

        Q[i,i] = diagonal_weight(variable,pressure)

    # -----------------------------------------
    # Scenario penalties
    # -----------------------------------------

    for i, variable in enumerate(variables):

        if variable.id not in penalties:
            continue

        rule = penalties[variable.id]

        if rule["action"] == "soft_penalty":

            Q[i,i] += rule["penalty"]/50

        elif rule["action"] == "reward":

            Q[i,i] -= abs(rule["penalty"])/50

        elif rule["action"] == "force_zero":

            Q[i,i] += 1000

    # -----------------------------------------
    # Operational constraint encoding
    # -----------------------------------------

    Q = add_constraint_penalties(Q,variables)

    return Q,variables

# ---------------------------------------------------
# Standalone Test
# ---------------------------------------------------

if __name__ == "__main__":

    Q, variables = build_qubo()

    penalties = penalty_dictionary()

    print("\nScenario-Aware QUBO Built")
    print("--------------------------------")

    print(f"Variables : {len(variables)}")
    print(f"Matrix Size: {Q.shape}")

    print("\nDiagonal Values")

    for i, variable in enumerate(variables):

        print(f"{variable.id:<4}{Q[i,i]:>8}  ({variable.target})")

    print("\nApplied Scenario Rules")
    print("\nEmbedded Operational Constraints")
    print("Route Diversions      : max 2")
    print("Signal Extensions     : max 5")
    print("Road Restrictions     : max 1")



    if penalties:

        for variable_id, info in penalties.items():

            print(
                f"{variable_id:<4}"
                f"{info['action']:<15}"
                f"{info['penalty']:<6}"
                f"{info['reason']}"
            )

    else:

        print("None")

    print("\nTop-left 8×8 Matrix\n")

    print(Q[:8, :8])
