
"""
junction_mapper.py

Creates permanent project junction IDs (J1, J2...)
from the downloaded Chepauk road network.

Output:
    data/junction_mapping.json

Run:
    python network/junction_mapper.py
"""

from pathlib import Path
import json

# Import graph_loader from the same folder
from graph_loader import load_graph

# -----------------------------------------------------
# Paths
# -----------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = DATA_DIR / "junction_mapping.json"

# -----------------------------------------------------
# Load Graph
# -----------------------------------------------------

graph = load_graph()

# -----------------------------------------------------
# Collect Junction Information
# -----------------------------------------------------

junctions = []

for node in graph.nodes():

    junctions.append({
        "osm_id": int(node),
        "degree": graph.degree(node),
        "latitude": float(graph.nodes[node]["y"]),
        "longitude": float(graph.nodes[node]["x"])
    })

# -----------------------------------------------------
# Sort by Connectivity
# -----------------------------------------------------

junctions.sort(
    key=lambda x: x["degree"],
    reverse=True
)

# -----------------------------------------------------
# Create Mapping
# -----------------------------------------------------

mapping = {}

for i, junction in enumerate(junctions, start=1):

    mapping[f"J{i}"] = junction

# -----------------------------------------------------
# Save Mapping
# -----------------------------------------------------

with open(OUTPUT_FILE, "w") as f:
    json.dump(mapping, f, indent=4)

# -----------------------------------------------------
# Console Output
# -----------------------------------------------------

print("\nJunction Mapping Created")
print("----------------------------")
print(f"Total Junctions : {len(mapping)}")

print("\nTop 10 Most Connected Junctions\n")

for name, info in list(mapping.items())[:10]:

    print(
        f"{name:>3} | Degree={info['degree']:<2} | "
        f"OSM={info['osm_id']}"
    )

print(f"\nSaved to:\n{OUTPUT_FILE}")