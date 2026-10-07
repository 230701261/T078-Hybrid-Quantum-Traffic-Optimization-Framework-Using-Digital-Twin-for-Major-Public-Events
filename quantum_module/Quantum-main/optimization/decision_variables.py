
"""
decision_variables.py

Automatically generates binary decision variables
from the Chepauk road network.

These variables become the inputs for both the
Classical and Quantum optimization models.

Run:
    python optimization/decision_variables.py
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List
import json

# =====================================================
# Paths
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

CORRIDOR_FILE = DATA_DIR / "corridors.json"
JUNCTION_FILE = DATA_DIR / "junction_mapping.json"

# =====================================================
# Decision Variable
# =====================================================

@dataclass
class DecisionVariable:
    id: str
    category: str
    target: str
    description: str

# =====================================================
# Load JSON
# =====================================================

def load_json(path: Path):
    with open(path, "r") as f:
        return json.load(f)

# =====================================================
# Generate Variables
# =====================================================

def generate_variables():

    corridors = load_json(CORRIDOR_FILE)
    junctions = load_json(JUNCTION_FILE)

    variables = []
    counter = 1

    # -------------------------------------------------
    # Route Diversion Variables
    # -------------------------------------------------

    for corridor in corridors.keys():

        variables.append(
            DecisionVariable(
                id=f"x{counter}",
                category="route_diversion",
                target=corridor,
                description=f"Enable diversion through {corridor}"
            )
        )

        counter += 1

    # -------------------------------------------------
    # Signal Timing Variables
    # (Top 10 major junctions)
    # -------------------------------------------------

    top_junctions = list(junctions.keys())[:10]

    for junction in top_junctions:

        variables.append(
            DecisionVariable(
                id=f"x{counter}",
                category="signal_extension",
                target=junction,
                description=f"Increase green time at {junction}"
            )
        )

        counter += 1

    # -------------------------------------------------
    # Road Restriction Variables
    # -------------------------------------------------

    for corridor in corridors.keys():

        variables.append(
            DecisionVariable(
                id=f"x{counter}",
                category="temporary_restriction",
                target=corridor,
                description=f"Restrict access on {corridor}"
            )
        )

        counter += 1

    return variables

# =====================================================
# Convert to Dictionary
# =====================================================

def variable_dictionary():

    variables = generate_variables()

    return {
        variable.id: {
            "category": variable.category,
            "target": variable.target,
            "description": variable.description
        }
        for variable in variables
    }

# =====================================================
# Test
# =====================================================

if __name__ == "__main__":

    variables = generate_variables()

    print("\nDecision Variables Generated")
    print("-----------------------------")
    print(f"Total Variables: {len(variables)}\n")

    for variable in variables:

        print(
            f"{variable.id:<4}"
            f"{variable.category:<22}"
            f"{variable.target}"
        )