"""
id_mapper.py

Explicit, bidirectional mapping layer between:
1. Quantum Module Logical IDs (e.g. 'Anna Salai', 'J1')
2. Digital Twin Canonical IDs (e.g. 'corridor_mount_road', 'junction_nw')
3. SUMO Network Edge IDs and Traffic Light Junction IDs (e.g. 'E_WEST_1', 'J_NW')

Ensures zero hardcoding in controller or solver routines.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class CorridorMapping:
    quantum_name: str
    canonical_id: str
    primary_sumo_edges: List[str]
    reverse_sumo_edges: List[str]
    description: str

@dataclass
class JunctionMapping:
    quantum_id: str
    canonical_id: str
    sumo_tls_id: str
    associated_edges: List[str]
    description: str

# ==============================================================================
# 1. CORRIDOR MAPPINGS
# ==============================================================================

CORRIDOR_MAP: Dict[str, CorridorMapping] = {
    "Anna Salai": CorridorMapping(
        quantum_name="Anna Salai",
        canonical_id="corridor_mount_road",
        primary_sumo_edges=["E_WEST_IN_N", "E_WEST_1", "E_WEST_OUT_S"],
        reverse_sumo_edges=["E_WEST_IN_S", "E_WEST_1_rev", "E_WEST_OUT_N"],
        description="West Major Arterial (Mount Road / Anna Salai)"
    ),
    "Wallajah Road": CorridorMapping(
        quantum_name="Wallajah Road",
        canonical_id="corridor_wallajah",
        primary_sumo_edges=["E_NORTH_IN_W", "E_NORTH_1", "E_NORTH_2", "E_NORTH_OUT_E"],
        reverse_sumo_edges=["E_NORTH_IN_E", "E_NORTH_2_rev", "E_NORTH_1_rev", "E_NORTH_OUT_W"],
        description="North Major Arterial (Wallajah Road)"
    ),
    "Kamarajar Salai": CorridorMapping(
        quantum_name="Kamarajar Salai",
        canonical_id="corridor_kamarajar_salai",
        primary_sumo_edges=["E_EAST_IN_N", "E_EAST_1", "E_EAST_OUT_S"],
        reverse_sumo_edges=["E_EAST_IN_S", "E_EAST_1_rev", "E_EAST_OUT_N"],
        description="East Coastal Road (Kamarajar Salai / Marina Beach Road)"
    ),
    "Triplicane High Road": CorridorMapping(
        quantum_name="Triplicane High Road",
        canonical_id="corridor_triplicane",
        primary_sumo_edges=["E_SOUTH_IN_W", "E_SOUTH_1", "E_SOUTH_2", "E_SOUTH_OUT_E", "E_CENTRAL_1", "E_CENTRAL_2"],
        reverse_sumo_edges=["E_SOUTH_IN_E", "E_SOUTH_2_rev", "E_SOUTH_1_rev", "E_SOUTH_OUT_W", "E_CENTRAL_2_rev", "E_CENTRAL_1_rev"],
        description="South & Central Arterial (Triplicane High Road / Bells Road)"
    )
}

# ==============================================================================
# 2. JUNCTION / TRAFFIC LIGHT MAPPINGS
# ==============================================================================

JUNCTION_MAP: Dict[str, JunctionMapping] = {
    "J1": JunctionMapping(
        quantum_id="J1",
        canonical_id="junction_nw",
        sumo_tls_id="J_NW",
        associated_edges=["E_WEST_1", "E_NORTH_1"],
        description="North-West Major Signal (Mount Rd / Wallajah Rd)"
    ),
    "J2": JunctionMapping(
        quantum_id="J2",
        canonical_id="junction_n_central",
        sumo_tls_id="J_N_CENTRAL",
        associated_edges=["E_NORTH_1", "E_NORTH_2", "E_CENTRAL_1"],
        description="North-Central Signal (Wallajah Rd / Central Stadium Approach)"
    ),
    "J3": JunctionMapping(
        quantum_id="J3",
        canonical_id="junction_ne",
        sumo_tls_id="J_NE",
        associated_edges=["E_NORTH_2", "E_EAST_1"],
        description="North-East Signal (Wallajah Rd / Kamarajar Salai)"
    ),
    "J4": JunctionMapping(
        quantum_id="J4",
        canonical_id="junction_central_stad",
        sumo_tls_id="J_CENTRAL_STAD",
        associated_edges=["E_CENTRAL_1", "E_CENTRAL_2", "E_STAD_ACC"],
        description="Central Stadium Gate & Vehicle Access Signal"
    ),
    "J5": JunctionMapping(
        quantum_id="J5",
        canonical_id="junction_sw",
        sumo_tls_id="J_SW",
        associated_edges=["E_WEST_1", "E_SOUTH_1"],
        description="South-West Signal (Mount Rd / Bells Rd)"
    ),
    "J6": JunctionMapping(
        quantum_id="J6",
        canonical_id="junction_s_central",
        sumo_tls_id="J_S_CENTRAL",
        associated_edges=["E_SOUTH_1", "E_SOUTH_2", "E_CENTRAL_2"],
        description="South-Central Signal (Bells Rd / Central Stadium Approach)"
    ),
    "J7": JunctionMapping(
        quantum_id="J7",
        canonical_id="junction_se",
        sumo_tls_id="J_SE",
        associated_edges=["E_SOUTH_2", "E_EAST_1"],
        description="South-East Signal (Bells Rd / Kamarajar Salai)"
    ),
    # Peripheral secondary junctions mapped to closest primary TLS controllers
    "J8": JunctionMapping(
        quantum_id="J8",
        canonical_id="junction_peripheral_north",
        sumo_tls_id="J_NW",
        associated_edges=["E_NORTH_IN_W", "E_WEST_IN_N"],
        description="North Peripheral Feeder Sub-Controller"
    ),
    "J9": JunctionMapping(
        quantum_id="J9",
        canonical_id="junction_peripheral_east",
        sumo_tls_id="J_NE",
        associated_edges=["E_EAST_IN_N", "E_NORTH_IN_E"],
        description="East Peripheral Feeder Sub-Controller"
    ),
    "J10": JunctionMapping(
        quantum_id="J10",
        canonical_id="junction_peripheral_south",
        sumo_tls_id="J_SE",
        associated_edges=["E_SOUTH_IN_E", "E_EAST_IN_S"],
        description="South Peripheral Feeder Sub-Controller"
    )
}

# ==============================================================================
# 3. CONVERSION & LOOKUP HELPERS
# ==============================================================================

def map_quantum_corridor_to_sumo(quantum_name: str) -> List[str]:
    """Returns all SUMO edge IDs (both directions) for a given quantum corridor name."""
    if quantum_name in CORRIDOR_MAP:
        mapping = CORRIDOR_MAP[quantum_name]
        return mapping.primary_sumo_edges + mapping.reverse_sumo_edges
    raise KeyError(f"Unknown Quantum Corridor: '{quantum_name}'. Valid: {list(CORRIDOR_MAP.keys())}")

def map_quantum_junction_to_sumo_tls(quantum_id: str) -> str:
    """Maps Quantum J1..J10 ID to real SUMO Traffic Light ID."""
    if quantum_id in JUNCTION_MAP:
        return JUNCTION_MAP[quantum_id].sumo_tls_id
    raise KeyError(f"Unknown Quantum Junction ID: '{quantum_id}'. Valid: {list(JUNCTION_MAP.keys())}")

def map_sumo_tls_to_quantum_junctions(sumo_tls_id: str) -> List[str]:
    """Reverse lookup: find quantum junction IDs mapped to a SUMO TLS."""
    return [q_id for q_id, jm in JUNCTION_MAP.items() if jm.sumo_tls_id == sumo_tls_id]

def get_canonical_corridor_id(quantum_name: str) -> str:
    if quantum_name in CORRIDOR_MAP:
        return CORRIDOR_MAP[quantum_name].canonical_id
    return quantum_name.lower().replace(" ", "_")

def get_canonical_junction_id(quantum_id: str) -> str:
    if quantum_id in JUNCTION_MAP:
        return JUNCTION_MAP[quantum_id].canonical_id
    return f"junction_{quantum_id.lower()}"
