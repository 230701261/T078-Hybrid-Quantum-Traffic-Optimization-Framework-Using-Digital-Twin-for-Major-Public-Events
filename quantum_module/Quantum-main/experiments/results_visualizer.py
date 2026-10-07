"""
results_visualizer.py

Generates research-quality figures from
scenario_results.csv.

Outputs:
    experiments/figures/

Works with the current experiment_runner output.
"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------------------------------------
# Paths
# ---------------------------------------------------

BASE = Path(__file__).resolve().parent
CSV = BASE / "scenario_results.csv"

FIG_DIR = BASE / "figures"
FIG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------
# Load Data
# ---------------------------------------------------

df = pd.read_csv(CSV)

plt.rcParams["figure.figsize"] = (7, 5)
plt.rcParams["font.size"] = 11

# ===================================================
# Figure 1
# Travel Time Saved
# ===================================================

plt.figure()

plt.plot(
    df["Scenario"],
    df["GreedyTravel"],
    marker="o",
    linewidth=2,
    label="Greedy"
)

plt.plot(
    df["Scenario"],
    df["ClassicalTravel"],
    marker="s",
    linewidth=2,
    label="Classical"
)

plt.plot(
    df["Scenario"],
    df["QuantumTravel"],
    marker="^",
    linewidth=2,
    label="Quantum"
)

plt.ylabel("Travel Time Saved (minutes)")
plt.xlabel("Scenario")
plt.title("Travel Time Saved Across Scenarios")
plt.grid(True)
plt.legend()

plt.tight_layout()
plt.savefig(FIG_DIR / "travel_time_saved.png", dpi=300)
plt.close()

# ===================================================
# Figure 2
# QUBO Objective
# ===================================================

plt.figure()

plt.plot(
    df["Scenario"],
    df["GreedyObj"],
    marker="o",
    linewidth=2,
    label="Greedy"
)

plt.plot(
    df["Scenario"],
    df["ClassicalObj"],
    marker="s",
    linewidth=2,
    label="Classical"
)

plt.plot(
    df["Scenario"],
    df["QuantumObj"],
    marker="^",
    linewidth=2,
    label="Quantum"
)

plt.ylabel("QUBO Objective")
plt.xlabel("Scenario")
plt.title("Optimization Objective Across Scenarios")
plt.grid(True)
plt.legend()

plt.tight_layout()
plt.savefig(FIG_DIR / "qubo_objective.png", dpi=300)
plt.close()

# ===================================================
# Figure 3
# Weather Impact
# ===================================================

weather_avg = (
    df.groupby("Weather")[["ClassicalTravel", "QuantumTravel"]]
    .mean()
)

plt.figure()

x = range(len(weather_avg))
width = 0.35

plt.bar(
    [i - width / 2 for i in x],
    weather_avg["ClassicalTravel"],
    width,
    label="Classical"
)

plt.bar(
    [i + width / 2 for i in x],
    weather_avg["QuantumTravel"],
    width,
    label="Quantum"
)

plt.xticks(list(x), weather_avg.index)

plt.ylabel("Average Travel Time Saved (minutes)")
plt.xlabel("Weather Condition")
plt.title("Weather Impact on Optimization Performance")
plt.legend()

plt.tight_layout()
plt.savefig(FIG_DIR / "weather_impact.png", dpi=300)
plt.close()

# ===================================================
# Figure 4
# Constraint Activation Overview
# ===================================================

constraint_counts = pd.DataFrame({
    "VIP": df["VIP"].astype(int),
    "Construction": df["Construction"].astype(int),
    "Crowd Surge": df["CrowdSurge"].astype(int)
}, index=df["Scenario"])

plt.figure(figsize=(7, 4))

plt.imshow(constraint_counts.T, aspect="auto")

plt.xticks(range(len(df["Scenario"])), df["Scenario"])
plt.yticks(range(3), constraint_counts.columns)

plt.title("Constraint Activation Across Scenarios")
plt.xlabel("Scenario")
plt.ylabel("Constraint")

plt.colorbar(label="0 = Off, 1 = On")

plt.tight_layout()
plt.savefig(FIG_DIR / "constraint_heatmap.png", dpi=300)
plt.close()

# ===================================================
# Figure 5
# Performance Difference
# ===================================================

difference = df["QuantumTravel"] - df["ClassicalTravel"]

plt.figure()

colors = [
    "green" if value >= 0 else "red"
    for value in difference
]

plt.bar(
    df["Scenario"],
    difference,
    color=colors
)

plt.axhline(0, linestyle="--")

plt.ylabel("Quantum - Classical (minutes)")
plt.xlabel("Scenario")
plt.title("Travel Time Difference Between Quantum and Classical")

plt.tight_layout()
plt.savefig(FIG_DIR / "quantum_vs_classical_difference.png", dpi=300)
plt.close()

# ===================================================
# Finished
# ===================================================

print("\nResearch Figures Generated")
print("--------------------------")

for file in sorted(FIG_DIR.glob("*.png")):
    print(file.name)