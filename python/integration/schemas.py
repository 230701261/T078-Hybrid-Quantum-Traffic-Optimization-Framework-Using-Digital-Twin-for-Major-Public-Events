"""
schemas.py

Pydantic and dataclass models defining the formal versioned Integration Contract
between Quantum Optimization Service, Integration API Layer, Supabase, and Digital Twin.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, field_validator
import uuid
import datetime

def get_utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

# ==============================================================================
# 1. OPTIMIZATION REQUEST SCHEMAS (DIGITAL TWIN -> QUANTUM SERVICE)
# ==============================================================================

class EventInfo(BaseModel):
    # Values are supplied from the active scenario/TraCI snapshot by the
    # Digital Twin. None represents unavailable metadata in standalone use.
    name: Optional[str] = None
    venue: Optional[str] = None
    total_vehicles: Optional[int] = Field(default=None, ge=0)

class ScenarioConstraints(BaseModel):
    weather: str = Field(default="Clear")
    vip: bool = Field(default=False)
    construction: Union[bool, List[str]] = Field(default=False)
    crowd_surge: bool = Field(default=False)
    parking_overflow: bool = Field(default=False)
    vip_enabled: bool = Field(default=False)
    vip_corridor: Optional[str] = None
    construction_enabled: bool = Field(default=False)
    construction_corridor: Optional[str] = None

class OptimizationRequestPayload(BaseModel):
    event: EventInfo = Field(default_factory=EventInfo)
    constraints: ScenarioConstraints = Field(default_factory=ScenarioConstraints)
    # Runtime integration supplies these from live SUMO vehicle positions.
    # Empty means unavailable; never seed fabricated junction demand.
    intersections: Dict[str, float] = Field(default_factory=dict)
    solver: Optional[str] = Field(default="qaoa") # 'qaoa' or 'classical'
    density: Dict[str, int] = Field(default_factory=dict)
    route_modifications: Dict[str, Any] = Field(default_factory=dict)
    signal_timings: Dict[str, Dict[str, float]] = Field(default_factory=dict)

class OptimizationRequest(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    simulation_id: str = Field(default="sim_chepauk_001")
    scenario_id: str = Field(default="scenario_ipl_match")
    timestamp: str = Field(default_factory=get_utc_timestamp)
    schema_version: str = Field(default="1.0")
    payload: OptimizationRequestPayload = Field(default_factory=OptimizationRequestPayload)

# ==============================================================================
# 2. OPTIMIZATION RESPONSE SCHEMAS (QUANTUM SERVICE -> INTEGRATION LAYER)
# ==============================================================================

class CorridorAction(BaseModel):
    corridor: str
    enabled: bool
    demand: float
    capacity: float
    pressure: float
    overflow: float
    rerouted: float
    remaining_queue: float

class SignalChangeAction(BaseModel):
    junction: str
    old_green: float
    new_green: float
    extra_green: float

class RestrictionAction(BaseModel):
    corridor: str
    type: str = "temporary_restriction"

class OptimizationBenefits(BaseModel):
    travel_time_saved_minutes: float
    queue_reduction_percent: float

class OptimizationResponse(BaseModel):
    run_id: Optional[str] = None
    message_id: str
    simulation_id: str
    scenario_id: str
    optimizer_used: str # 'Quantum' or 'Classical'
    bitstring: str = Field(..., min_length=18, max_length=18)
    corridors: List[CorridorAction] = Field(default_factory=list)
    signal_changes: List[SignalChangeAction] = Field(default_factory=list)
    restrictions: List[RestrictionAction] = Field(default_factory=list)
    benefits: OptimizationBenefits
    objective_value: Optional[float] = None
    application_result: Optional[Dict[str, Any]] = None
    runtime_seconds: float = Field(default=0.0, ge=0.0)
    status: str = Field(default="completed")
    applied_to_sumo: bool = False
    error: Optional[str] = None

    @field_validator("bitstring")
    @classmethod
    def validate_bitstring(cls, v: str) -> str:
        if not all(c in "01" for c in v):
            raise ValueError("Bitstring must consist solely of 0 and 1 binary characters.")
        return v

# ==============================================================================
# 3. DIGITAL TWIN COMMAND ADAPTER SCHEMAS
# ==============================================================================

class DigitalTwinCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str # 'signal_extension', 'route_diversion', 'temporary_restriction'
    logical_target: str
    canonical_target: str
    sumo_target_id: str # SUMO TLS ID or SUMO Edge ID
    parameters: Dict[str, Any] = Field(default_factory=dict)
    applied: bool = False
    timestamp: str = Field(default_factory=get_utc_timestamp)
