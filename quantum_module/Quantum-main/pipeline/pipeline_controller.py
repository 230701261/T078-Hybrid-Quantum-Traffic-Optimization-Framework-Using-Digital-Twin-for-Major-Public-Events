
"""
pipeline_controller.py

Runs the complete Chepauk optimization pipeline.

Run:
    python pipeline/pipeline_controller.py
"""

from pathlib import Path
import subprocess
import time

BASE_DIR = Path(__file__).resolve().parent.parent

steps = [

    ("Problem Builder",
     "optimization/problem_builder.py"),

    ("Decision Variables",
     "optimization/decision_variables.py"),

    ("Constraint Compiler",
     "optimization/constraint_compiler.py"),

    ("Objective Builder",
     "optimization/objective_builder.py"),

    ("Interaction Builder",
     "optimization/interaction_builder.py"),

    ("QUBO Builder",
     "optimization/qubo_builder.py"),

    ("Quadratic Program",
     "optimization/quadratic_program_builder.py"),

    ("Classical Optimization",
     "optimization/classical_optimizer.py"),

    ("Quantum Optimization",
     "optimization/qaoa_solver.py"),

    ("Traffic Decision Engine",
     "optimization/traffic_decision_engine.py"),

    ("Comparison Engine",
     "optimization/comparison_engine.py")
]

# ----------------------------------------------------

def run_step(name, script):

    print(f"\n{name}")
    print("-" * len(name))

    start = time.time()

    result = subprocess.run(
        ["python", script],
        cwd=BASE_DIR
    )

    elapsed = time.time() - start

    if result.returncode != 0:

        raise RuntimeError(f"{name} failed.")

    print(f"Completed in {elapsed:.2f} seconds.")

# ----------------------------------------------------

if __name__ == "__main__":

    print("\nChepauk Traffic Optimization Pipeline")
    print("=" * 40)

    total_start = time.time()

    for name, script in steps:

        run_step(name, script)

    total = time.time() - total_start

    print("\nPipeline Completed Successfully")
    print("=" * 40)
    print(f"Total Runtime: {total:.2f} seconds")