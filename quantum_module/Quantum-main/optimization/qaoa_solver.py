"""
qaoa_solver.py

Lightweight QAOA with constraint repair.

Uses the Scenario-Aware QUBO.

Outputs:
    results/qaoa_solution.json
    results/qaoa_bitstring.txt
"""

from pathlib import Path
import json
import time
import numpy as np

from qiskit.quantum_info import SparsePauliOp
from qiskit.circuit.library import QAOAAnsatz
from qiskit_aer import AerSimulator

from qubo_builder import build_qubo
from decision_variables import generate_variables

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"
RESULTS.mkdir(exist_ok=True)

# ----------------------------------------------------
# QUBO -> Ising
# ----------------------------------------------------

def qubo_to_ising(Q):

    n = Q.shape[0]

    paulis = []

    offset = 0

    for i in range(n):

        offset += Q[i, i] / 2

        z = ["I"] * n
        z[n - 1 - i] = "Z"

        paulis.append(("".join(z), -Q[i, i] / 2))

    for i in range(n):

        for j in range(i + 1, n):

            if abs(Q[i, j]) < 1e-9:
                continue

            offset += Q[i, j] / 4

            zi = ["I"] * n
            zj = ["I"] * n
            zz = ["I"] * n

            zi[n - 1 - i] = "Z"
            zj[n - 1 - j] = "Z"
            zz[n - 1 - i] = "Z"
            zz[n - 1 - j] = "Z"

            paulis.append(("".join(zi), -Q[i, j] / 4))
            paulis.append(("".join(zj), -Q[i, j] / 4))
            paulis.append(("".join(zz), Q[i, j] / 4))

    return SparsePauliOp.from_list(paulis), offset

# ----------------------------------------------------
# Repair heuristic
# ----------------------------------------------------

def repair(bits, Q):

    bits = bits.copy()

    # route diversions (x1-x4)
    while sum(bits[:4]) > 2:

        active = [i for i in range(4) if bits[i]]
        worst = min(active, key=lambda i: Q[i, i])
        bits[worst] = 0

    # signals (x5-x14)
    while sum(bits[4:14]) > 5:

        active = [i for i in range(4, 14) if bits[i]]
        worst = min(active, key=lambda i: Q[i, i])
        bits[worst] = 0

    # restrictions (x15-x18)
    while sum(bits[14:18]) > 1:

        active = [i for i in range(14, 18) if bits[i]]
        worst = min(active, key=lambda i: Q[i, i])
        bits[worst] = 0

    return bits

# ----------------------------------------------------
# Energy
# ----------------------------------------------------

def energy(bits, Q):

    x = np.array(bits)

    return float(x @ Q @ x)

# ----------------------------------------------------
# Lightweight QAOA
# ----------------------------------------------------

def solve():

    print("Building Scenario-Aware QUBO...")

    Q, variables = build_qubo()

    print("Converting QUBO to Ising...")

    hamiltonian, _ = qubo_to_ising(Q)

    simulator = AerSimulator(method="statevector")

    best_bits = None
    best_energy = float("inf")

    start = time.time()

    gamma_values = np.linspace(0, np.pi, 8)
    beta_values = np.linspace(0, np.pi / 2, 8)

    total = len(gamma_values) * len(beta_values)
    done = 0

    print("Running Grid Search QAOA...")

    for gamma in gamma_values:

        for beta in beta_values:

            ansatz = QAOAAnsatz(hamiltonian, reps=1)
            circuit = ansatz.assign_parameters([gamma, beta])

            circuit = circuit.decompose(reps=10)

            circuit.measure_all()

            counts = simulator.run(circuit, shots=512).result().get_counts()

            bits = max(counts, key=counts.get)
            bits = [int(b) for b in bits]

            bits = repair(bits, Q)

            e = energy(bits, Q)

            if e < best_energy:

                best_energy = e
                best_bits = bits

            done += 1

            if done % 8 == 0:
                print(f"Progress: {done}/{total}")

    runtime = time.time() - start

    return variables, best_bits, best_energy, runtime

# ----------------------------------------------------
# Save
# ----------------------------------------------------

def save(variables, bits, objective, runtime):

    bitstring = "".join(map(str, bits))

    values = {
        v.id: b
        for v, b in zip(variables, bits)
    }

    with open(RESULTS / "qaoa_solution.json", "w") as f:

        json.dump({

            "mode": "Quantum",
            "runtime_seconds": runtime,
            "objective_value": objective,
            "bitstring": bitstring,
            "variables": values

        }, f, indent=4)

    with open(RESULTS / "qaoa_bitstring.txt", "w") as f:
        f.write(bitstring)

    return bitstring

# ----------------------------------------------------
# Main
# ----------------------------------------------------

if __name__ == "__main__":

    variables, bits, objective, runtime = solve()

    bitstring = save(
        variables,
        bits,
        objective,
        runtime
    )

    print("\nConstraint-Aware QAOA Complete")
    print("--------------------------------")

    print(f"Runtime : {runtime:.3f} s")
    print(f"QUBO Objective : {objective}")
    print(f"Bitstring : {bitstring}")

    print("\nSelected Variables")

    for v, b in zip(variables, bits):

        if b:
            print(f"{v.id:<4}{v.target}")

    print("\nSaved")
    print(RESULTS / "qaoa_solution.json")
    print(RESULTS / "qaoa_bitstring.txt")