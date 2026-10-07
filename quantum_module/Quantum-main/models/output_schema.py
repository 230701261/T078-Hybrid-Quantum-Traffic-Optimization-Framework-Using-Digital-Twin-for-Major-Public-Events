
from pydantic import BaseModel
from typing import List

class RouteChange(BaseModel):
    source: str
    destination: str
    vehicles: int

class SignalChange(BaseModel):
    intersection: str
    before: int
    after: int

class Metrics(BaseModel):
    travel_time: float
    queue_length: int
    congestion: float

class OptimizationOutput(BaseModel):
    mode: str
    route_redirections: List[RouteChange]
    signal_changes: List[SignalChange]
    metrics: Metrics