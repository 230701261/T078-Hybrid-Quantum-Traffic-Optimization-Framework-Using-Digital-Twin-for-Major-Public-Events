
"""
corridor_extractor.py

Extracts the major named roads around Chepauk Stadium
and groups them into reusable event corridors.

Output:
    data/corridors.json

Run:
    python network/corridor_extractor.py
"""

from pathlib import Path
import json

from graph_loader import load_graph

# -----------------------------------------------------
# Paths
# -----------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

OUTPUT_FILE = DATA_DIR / "corridors.json"

# -----------------------------------------------------
# Load graph
# -----------------------------------------------------

graph = load_graph()

# -----------------------------------------------------
# Candidate event roads
# -----------------------------------------------------

TARGET_ROADS = [
    "Marina Road",
    "Wallajah Road",
    "Victoria Road",
    "Bells Road",
    "Pycrofts Road",
    "Anna Salai",
    "Kamarajar Salai",
    "Triplicane High Road"
]

corridors = {}

# -----------------------------------------------------
# Search road network
# -----------------------------------------------------

for u, v, key, data in graph.edges(keys=True, data=True):

    road_name = data.get("name")

    if road_name is None:
        continue

    if isinstance(road_name, list):
        names = road_name
    else:
        names = [road_name]

    for name in names:

        for target in TARGET_ROADS:

            if target.lower() in str(name).lower():

                if target not in corridors:
                    corridors[target] = []

                corridors[target].append({
                    "from": int(u),
                    "to": int(v),
                    "length": round(float(data.get("length", 0)), 2),
                    "oneway": bool(data.get("oneway", False))
                })

# -----------------------------------------------------
# Save
# -----------------------------------------------------

with open(OUTPUT_FILE, "w") as f:
    json.dump(corridors, f, indent=4)

# -----------------------------------------------------
# Console summary
# -----------------------------------------------------

print("\nCorridor Extraction Completed")
print("--------------------------------")

total_segments = 0

for corridor, segments in corridors.items():

    total_segments += len(segments)

    print(f"{corridor:<22} {len(segments):>4} segments")

print("--------------------------------")
print(f"Total corridors found : {len(corridors)}")
print(f"Total road segments   : {total_segments}")

print(f"\nSaved to:\n{OUTPUT_FILE}")