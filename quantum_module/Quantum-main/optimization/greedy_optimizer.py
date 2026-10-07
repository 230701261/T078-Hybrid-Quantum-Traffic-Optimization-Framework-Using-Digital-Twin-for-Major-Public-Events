
"""
greedy_optimizer.py

Rule-based classical optimizer for pre-event traffic planning.

This serves as the traditional traffic-management baseline
for comparison against Classical QUBO and Quantum QAOA.

Run:
    python optimization/greedy_optimizer.py
"""

from pathlib import Path
import json
import time

from problem_builder import build_problem

# =====================================================
# Paths
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"

# =====================================================
# Corridor Capacity
# =====================================================

CORRIDOR_CAPACITY = {

    "Anna Salai": 4200,

    "Triplicane High Road": 2200,

    "Wallajah Road": 2800,

    "Kamarajar Salai": 2400
}

CORRIDOR_TO_JUNCTION = {

    "Anna Salai": "J1",

    "Triplicane High Road": "J2",

    "Wallajah Road": "J4",

    "Kamarajar Salai": "J3"
}

# Decision variable mapping
ROUTE_VARIABLES = {

    "Anna Salai": "x1",

    "Triplicane High Road": "x2",

    "Wallajah Road": "x3",

    "Kamarajar Salai": "x4"
}

SIGNAL_VARIABLES = {

    "J1": "x5",

    "J2": "x6",

    "J3": "x7",

    "J4": "x8",

    "J5": "x9",

    "J6": "x10",

    "J7": "x11",

    "J8": "x12",

    "J9": "x13",

    "J10": "x14"
}

# =====================================================
# Priority Calculation
# =====================================================

def compute_priorities(problem):

    priorities = []

    for corridor, junction in CORRIDOR_TO_JUNCTION.items():

        demand = problem.demand[junction]

        capacity = CORRIDOR_CAPACITY[corridor]

        ratio = demand / capacity

        priorities.append({

            "corridor": corridor,

            "junction": junction,

            "demand": demand,

            "capacity": capacity,

            "priority": ratio
        })

    priorities.sort(

        key=lambda x: x["priority"],

        reverse=True
    )

    return priorities

# =====================================================
# Greedy Optimization
# =====================================================

def run_greedy():

    start = time.time()

    problem = build_problem()

    priorities = compute_priorities(problem)

    variables = {

        f"x{i}": 0

        for i in range(1, 19)
    }

    selected = []

    # Select top two corridors
    for item in priorities[:2]:

        corridor = item["corridor"]

        junction = item["junction"]

        variables[ROUTE_VARIABLES[corridor]] = 1

        variables[SIGNAL_VARIABLES[junction]] = 1

        selected.append(item)

    runtime = time.time() - start

    bitstring = "".join(

        str(variables[f"x{i}"])

        for i in range(1, 19)
    )

    objective = round(

        sum(x["priority"] * 100 for x in selected),

        2
    )

    solution = {

        "mode": "greedy",

        "runtime": runtime,

        "objective": objective,

        "bitstring": bitstring,

        "variables": variables,

        "selected_corridors": selected
    }

    with open(

        RESULTS_DIR / "greedy_solution.json",

        "w"
    ) as f:

        json.dump(solution, f, indent=4)

    with open(

        RESULTS_DIR / "greedy_bitstring.txt",

        "w"
    ) as f:

        f.write(bitstring)

    return solution

# =====================================================
# Standalone Test
# =====================================================

if __name__ == "__main__":

    solution = run_greedy()

    print("\nGreedy Optimization Complete")

    print("--------------------------------")

    print(f"Runtime         : {solution['runtime']:.4f} s")

    print(f"Objective Value : {solution['objective']}")

    print(f"Bitstring       : {solution['bitstring']}")

    print("\nSelected Corridors")

    for item in solution["selected_corridors"]:

        print(

            f"{item['corridor']:22}"

            f"Priority={item['priority']:.3f}"

            f" Demand={item['demand']}"

        )

    print("\nSaved")

    print(RESULTS_DIR / "greedy_solution.json")