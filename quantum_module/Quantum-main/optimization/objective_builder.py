
"""
objective_builder.py

Builds the mathematical objective function shared by both
the Classical and Quantum optimizers.

Run:
    python optimization/objective_builder.py
"""

from dataclasses import dataclass, field

from problem_builder import build_problem
from constraint_compiler import compile_constraints

# =====================================================
# Objective Weights
# =====================================================

TRAVEL_TIME_WEIGHT = 5
QUEUE_WEIGHT = 4
CONGESTION_WEIGHT = 3
SAFETY_WEIGHT = 2
THROUGHPUT_WEIGHT = 4
IMPLEMENTATION_WEIGHT = 1

# =====================================================
# Decision Costs
# =====================================================

IMPLEMENTATION_COSTS = {
    "route_diversion": 8,
    "signal_extension": 3,
    "temporary_restriction": 12
}

# =====================================================
# Objective Components
# =====================================================

@dataclass
class ObjectiveComponents:

    travel_time: float
    queue_length: float
    congestion: float
    safety_risk: float
    throughput: float

    implementation_costs: dict = field(default_factory=dict)

    implementation_total: float = 0

    total_score: float = 0

# =====================================================
# Travel Time
# =====================================================

def estimate_travel_time(problem):

    total_length = sum(r["length"] for r in problem.roads)

    average_speed = 40

    weather = problem.constraints["weather"]

    if weather == "Heavy Rain":
        average_speed = 25

    elif weather == "Light Rain":
        average_speed = 32

    elif weather == "Fog":
        average_speed = 28

    return (total_length / 1000) / average_speed * 60

# =====================================================
# Queue
# =====================================================

def estimate_queue(problem):

    demand = sum(problem.demand.values())

    capacity = sum(r["capacity"] for r in problem.roads)

    return demand / max(capacity, 1) * demand

# =====================================================
# Congestion
# =====================================================

def estimate_congestion(problem):

    congested = sum(
        1 for road in problem.roads
        if road["capacity"] < 700
    )

    return congested / len(problem.roads)

# =====================================================
# Safety
# =====================================================

def estimate_safety(problem):

    risk = 0

    if problem.constraints["weather"] == "Heavy Rain":
        risk += 0.5

    if problem.constraints["crowd_surge"]:
        risk += 0.3

    if problem.constraints["vip"]:
        risk += 0.2

    return min(risk, 1)

# =====================================================
# Throughput
# =====================================================

def estimate_throughput(problem):

    return sum(problem.demand.values())

# =====================================================
# Penalties
# =====================================================

def penalty_total():

    return sum(
        rule.penalty
        for rule in compile_constraints()
    )

# =====================================================
# Implementation Cost
# =====================================================

def implementation_cost_summary():

    total = sum(IMPLEMENTATION_COSTS.values())

    return IMPLEMENTATION_COSTS.copy(), total

# =====================================================
# Main
# =====================================================

def build_objective():

    problem = build_problem()

    travel = estimate_travel_time(problem)
    queue = estimate_queue(problem)
    congestion = estimate_congestion(problem)
    safety = estimate_safety(problem)
    throughput = estimate_throughput(problem)

    costs, implementation_total = implementation_cost_summary()

    penalties = penalty_total()

    score = (

        TRAVEL_TIME_WEIGHT * travel +

        QUEUE_WEIGHT * queue +

        CONGESTION_WEIGHT * congestion +

        SAFETY_WEIGHT * safety -

        THROUGHPUT_WEIGHT * throughput +

        IMPLEMENTATION_WEIGHT * implementation_total +

        penalties
    )

    return ObjectiveComponents(

        travel_time=travel,

        queue_length=queue,

        congestion=congestion,

        safety_risk=safety,

        throughput=throughput,

        implementation_costs=costs,

        implementation_total=implementation_total,

        total_score=score
    )

# =====================================================
# Test
# =====================================================

if __name__ == "__main__":

    obj = build_objective()

    print("\nObjective Function Built")
    print("--------------------------------")

    print(f"Travel Time        : {obj.travel_time:.2f} min")
    print(f"Queue Length       : {obj.queue_length:.2f}")
    print(f"Congestion Index   : {obj.congestion:.3f}")
    print(f"Safety Risk        : {obj.safety_risk:.2f}")
    print(f"Throughput         : {obj.throughput}")

    print("\nImplementation Costs")

    for k, v in obj.implementation_costs.items():

        print(f"{k:<22}{v}")

    print(f"\nTotal Cost Weight : {obj.implementation_total}")

    print("\nFinal Objective Score")
    print("--------------------------------")
    print(f"{obj.total_score:.2f}")