
"""
build_network.py

Purpose:
1. Download the Chepauk (MA Chidambaram Stadium) road network.
2. Save it as graph.graphml.
3. Export intersections.json.
4. Export roads.json.
5. Print network statistics.

Run:
python network/build_network.py
"""

from pathlib import Path
import json
import osmnx as ox

# =====================================================
# Configuration
# =====================================================

CENTER = (13.0628, 80.2792)
NETWORK_RADIUS = 1200  # meters

BASE_DIR = Path(__file__).resolve().parent.parent
NETWORK_DIR = BASE_DIR / "network"
DATA_DIR = BASE_DIR / "data"

NETWORK_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

GRAPH_FILE = NETWORK_DIR / "graph.graphml"

# =====================================================
# Download Road Network
# =====================================================

print("Downloading Chepauk road network...")

graph = ox.graph_from_point(
    CENTER,
    dist=NETWORK_RADIUS,
    network_type="drive"
)

# Save graph
ox.save_graphml(graph, GRAPH_FILE)

print(f"Graph saved to: {GRAPH_FILE}")

# =====================================================
# Convert graph to GeoDataFrames
# =====================================================

nodes, edges = ox.graph_to_gdfs(graph)

# =====================================================
# Export Intersections
# =====================================================

intersections = {}

for i, (node_id, row) in enumerate(nodes.iterrows(), start=1):
    intersections[f"J{i}"] = {
        "osm_id": int(node_id),
        "latitude": float(row.geometry.y),
        "longitude": float(row.geometry.x)
    }

with open(DATA_DIR / "intersections.json", "w") as f:
    json.dump(intersections, f, indent=4)

# =====================================================
# Export Roads
# =====================================================

roads = []

for edge_id, (edge_index, row) in enumerate(edges.iterrows(), start=1):

    # MultiIndex = (u, v, key)
    if isinstance(edge_index, tuple):
        if len(edge_index) == 3:
            u, v, key = edge_index
        elif len(edge_index) == 2:
            u, v = edge_index
            key = 0
        else:
            u = v = key = 0
    else:
        u = v = key = 0

    road_name = row.get("name", "Unnamed Road")
    if isinstance(road_name, list):
        road_name = road_name[0]

    lanes = row.get("lanes", "Unknown")
    if isinstance(lanes, list):
        lanes = lanes[0]

    speed = row.get("maxspeed", "Unknown")
    if isinstance(speed, list):
        speed = speed[0]

    roads.append({
        "road_id": f"R{edge_id}",
        "osm_u": int(u),
        "osm_v": int(v),
        "osm_key": int(key),
        "name": road_name,
        "length": round(float(row.get("length", 0)), 2),
        "lanes": lanes,
        "speed_limit": speed,
        "oneway": bool(row.get("oneway", False))
    })

with open(DATA_DIR / "roads.json", "w") as f:
    json.dump(roads, f, indent=4)

# =====================================================
# Statistics
# =====================================================

print("\nNetwork Statistics")
print("---------------------------")
print(f"Intersections : {len(nodes)}")
print(f"Road Segments : {len(edges)}")

print("\nGenerated Files")
print("---------------------------")
print(f"✓ {GRAPH_FILE}")
print(f"✓ {DATA_DIR/'intersections.json'}")
print(f"✓ {DATA_DIR/'roads.json'}")

print("\nNetwork build completed successfully.")