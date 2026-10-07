
"""
graph_loader.py

Loads the saved Chepauk road network and provides helper
functions for the rest of the project.
"""

from pathlib import Path
import osmnx as ox
import networkx as nx

# --------------------------------------------------
# Paths
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
GRAPH_FILE = BASE_DIR / "network" / "graph.graphml"


# --------------------------------------------------
# Load Graph
# --------------------------------------------------

def load_graph():
    """Load the saved GraphML road network."""

    if not GRAPH_FILE.exists():
        raise FileNotFoundError(
            "graph.graphml not found. Run network/build_network.py first."
        )

    return ox.load_graphml(GRAPH_FILE)


# --------------------------------------------------
# Graph Summary
# --------------------------------------------------

def graph_summary(graph):
    """Return basic graph statistics."""

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges()
    }


# --------------------------------------------------
# Find Nearest Node
# --------------------------------------------------

def nearest_node(graph, latitude, longitude):
    """Find the nearest road network node."""

    return ox.distance.nearest_nodes(
        graph,
        X=longitude,
        Y=latitude
    )


# --------------------------------------------------
# Shortest Path
# --------------------------------------------------

def shortest_path(graph, start_node, end_node):
    """Compute shortest path using road length."""

    return nx.shortest_path(
        graph,
        start_node,
        end_node,
        weight="length"
    )


# --------------------------------------------------
# Path Distance
# --------------------------------------------------

def path_distance(graph, path):
    """Return total path distance in meters."""

    distance = 0

    for u, v in zip(path[:-1], path[1:]):

        edge = graph.get_edge_data(u, v)

        if edge:
            first_edge = edge[list(edge.keys())[0]]
            distance += first_edge.get("length", 0)

    return round(distance, 2)


# --------------------------------------------------
# Standalone Test
# --------------------------------------------------

if __name__ == "__main__":

    graph = load_graph()
    summary = graph_summary(graph)

    print("\nGraph Loaded Successfully")
    print("--------------------------")
    print(f"Nodes : {summary['nodes']}")
    print(f"Edges : {summary['edges']}")