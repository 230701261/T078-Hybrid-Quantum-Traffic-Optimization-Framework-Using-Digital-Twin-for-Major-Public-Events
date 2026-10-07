
"""
constraint_compiler.py

Converts authority-selected scenarios into optimization
constraints used by BOTH Classical and Quantum optimizers.

Compatible with the new Scenario Profile architecture.

Run:
    python optimization/constraint_compiler.py
"""

from pathlib import Path
from dataclasses import dataclass
import sys

# -----------------------------------------------------
# Project Root
# -----------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# -----------------------------------------------------
# Imports
# -----------------------------------------------------

from problem_builder import build_problem
from decision_variables import generate_variables
from scenario.scenario_profiles import (
    SCENARIO_PROFILES,
    SPECIAL_CONDITIONS
)

# -----------------------------------------------------
# Constraint Object
# -----------------------------------------------------

@dataclass
class ConstraintRule:
    variable: str
    action: str
    reason: str
    penalty: int

# -----------------------------------------------------
# Normalize Inputs
# -----------------------------------------------------

def normalize_construction(problem):

    construction = problem.constraints.get("construction", False)

    if isinstance(construction, bool):

        if construction:
            return list(problem.corridors.keys())

        return []

    return construction

# -----------------------------------------------------
# Compile Rules
# -----------------------------------------------------

def compile_constraints():

    problem = build_problem()

    variables = generate_variables()

    rules = []

    weather = problem.constraints.get("weather", "Clear")

    construction = normalize_construction(problem)

    vip = problem.constraints.get("vip", False)

    crowd = problem.constraints.get("crowd_surge", False)

    parking = problem.constraints.get("parking_overflow", False)

    weather_profile = SCENARIO_PROFILES.get(weather, SCENARIO_PROFILES["Clear"])

    # -------------------------------------------------
    # Weather Rules
    # -------------------------------------------------

    if weather_profile["capacity_multiplier"] < 1:

        for var in variables:

            if var.category == "route_diversion":

                penalty = int(
                    (1 - weather_profile["capacity_multiplier"]) * 800
                )

                rules.append(

                    ConstraintRule(
                        variable=var.id,
                        action="soft_penalty",
                        reason=f"{weather} reduces diversion efficiency",
                        penalty=penalty
                    )
                )

    # -------------------------------------------------
    # Construction Rules
    # -------------------------------------------------

    for var in variables:

        if (
            var.category in ["route_diversion", "temporary_restriction"]
            and var.target in construction
        ):

            rules.append(

                ConstraintRule(
                    variable=var.id,
                    action="force_zero",
                    reason=f"{var.target} under construction",
                    penalty=1000
                )
            )

    # -------------------------------------------------
    # VIP Rules
    # -------------------------------------------------

    if vip:

        for var in variables:

            if var.category == "signal_extension":

                rules.append(

                    ConstraintRule(
                        variable=var.id,
                        action="reward",
                        reason="VIP corridor priority",
                        penalty=-300
                    )
                )

    # -------------------------------------------------
    # Crowd Surge
    # -------------------------------------------------

    if crowd:

        for var in variables:

            if var.category == "signal_extension":

                rules.append(

                    ConstraintRule(
                        variable=var.id,
                        action="reward",
                        reason="Crowd surge pedestrian management",
                        penalty=-120
                    )
                )

    # -------------------------------------------------
    # Parking Overflow
    # -------------------------------------------------

    if parking:

        for var in variables:

            if var.category == "route_diversion":

                rules.append(

                    ConstraintRule(
                        variable=var.id,
                        action="reward",
                        reason="Parking overflow rerouting",
                        penalty=-80
                    )
                )

    return rules

# -----------------------------------------------------
# Penalty Dictionary
# -----------------------------------------------------

def penalty_dictionary():

    penalties = {}

    for rule in compile_constraints():

        penalties[rule.variable] = {
            "action": rule.action,
            "reason": rule.reason,
            "penalty": rule.penalty
        }

    return penalties

# -----------------------------------------------------
# Standalone Test
# -----------------------------------------------------

if __name__ == "__main__":

    rules = compile_constraints()

    print("\nConstraint Compilation Complete")
    print("--------------------------------")

    if not rules:

        print("No additional constraints applied.")

    else:

        for rule in rules:

            print(
                f"{rule.variable:<4}"
                f"{rule.action:<15}"
                f"{rule.penalty:<6}"
                f"{rule.reason}"
            )

    print(f"\nTotal compiled rules: {len(rules)}")