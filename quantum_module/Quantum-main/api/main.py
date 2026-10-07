"""
api/main.py

FastAPI HTTP service wrapping the Quantum Traffic Optimization Module.
Provides standard, versioned endpoints for the Digital Twin Integration Layer.

Endpoints:
- POST /api/quantum/optimize
- GET /api/quantum/optimization/{simulation_id}
- GET /health
"""

import sys
import time
import json
import uuid
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure project root and optimization directory are in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
OPT_DIR = BASE_DIR / "optimization"
SCEN_DIR = BASE_DIR / "scenario"

for p in [BASE_DIR, OPT_DIR, SCEN_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from optimization.problem_builder import build_problem, SCENARIO_FILE
from optimization.qubo_builder import build_qubo
from optimization.classical_optimizer import solve_classically, save_result as save_classical
from optimization.qaoa_solver import solve as solve_qaoa, save as save_qaoa
from optimization.traffic_decision_engine import build_plan, OUTPUT as FINAL_PLAN_FILE
from optimization.sumo_exporter import build_export

app = FastAPI(
    title="Quantum Traffic Optimization Service",
    version="1.0.0",
    description="Scenario-Aware QUBO and QAOA Traffic Optimizer for Chepauk / MA Chidambaram Stadium District."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory result cache
RESULT_CACHE: Dict[str, Dict[str, Any]] = {}
OPTIMIZATION_LOCK = threading.Lock()


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """Replace a result artifact atomically so readers never see partial JSON."""
    temporary_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    temporary_path.replace(path)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "quantum_traffic_optimizer",
        "version": "1.0.0",
        "decision_variables": 18
    }

@app.post("/api/quantum/optimize")
def optimize_traffic(request_data: Dict[str, Any]):
    """Serialize access to shared scenario and result artifacts."""
    with OPTIMIZATION_LOCK:
        return _run_optimization(request_data)


def _run_optimization(request_data: Dict[str, Any]):
    """Executes one scenario-aware optimization and persists its matching plan."""
    start_time = time.time()

    # 1. Parse metadata and payload
    message_id = request_data.get("message_id", str(uuid.uuid4()))
    simulation_id = request_data.get("simulation_id", "sim_chepauk_001")
    scenario_id = request_data.get("scenario_id", "scenario_001")
    payload = request_data.get("payload", request_data)

    event_info = payload.get("event", {"name": "IPL Match", "venue": "MA Chidambaram Stadium", "total_vehicles": 9515})
    constraints = payload.get("constraints", {
        "weather": "Heavy Rain", "vip": True, "construction": True, "crowd_surge": True, "parking_overflow": True
    })
    intersections = payload.get("intersections", {
        "J1": 1200, "J2": 1447, "J3": 600, "J4": 1100, "J5": 450
    })
    solver_choice = payload.get("solver", "qaoa").lower()

    # 2. Update scenario_input.json dynamically with request parameters
    scenario_dict = {
        "event": event_info,
        "constraints": constraints,
        "intersections": intersections
    }

    try:
        with open(SCENARIO_FILE, "w") as f:
            json.dump(scenario_dict, f, indent=4)
    except Exception as e:
        print(f"[Warning] Could not write temporary scenario_input.json: {e}")

    # 3. Build QUBO
    try:
        Q, var_dict = build_qubo()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"QUBO formulation failed: {str(e)}"
        )

    # 4. Execute Solver
    optimizer_used = "Quantum"
    bitstring = "000000000000000000"
    objective_value = 0.0

    try:
        if solver_choice == "classical":
            optimizer_used = "Classical"
            variables, bits, value, opt_runtime = solve_classically()
            bitstring = save_classical(variables, bits, value, opt_runtime)
            objective_value = value
        else:
            try:
                # QAOA Optimization (AerSimulator statevector grid-search)
                optimizer_used = "Quantum"
                variables, bits, objective, opt_runtime = solve_qaoa()
                bitstring = save_qaoa(variables, bits, objective, opt_runtime)
                objective_value = objective
            except Exception as q_err:
                print(f"[QAOA Solver Warning] QAOA solver encountered issue ({q_err}), falling back to Classical exact solver.")
                optimizer_used = "Classical (Fallback)"
                variables, bits, value, opt_runtime = solve_classically()
                bitstring = save_classical(variables, bits, value, opt_runtime)
                objective_value = value
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Optimization execution failed: {str(e)}"
        )

    # 5. Build Final Traffic Plan and SUMO Export
    try:
        # Decode from this call's actual solver output instead of whichever
        # optimizer artifact happened to be written by a previous call.
        plan = build_plan(
            solution_override={"bitstring": bitstring},
            optimizer_override=optimizer_used,
        )
        if plan.get("bitstring") != bitstring:
            raise ValueError("Decoded plan bitstring does not match solver output")

        export = build_export(plan_override=plan, scenario_override=scenario_dict)
        if export.get("optimizer", {}).get("bitstring") != bitstring:
            raise ValueError("SUMO export bitstring does not match solver output")

        plan_corridors = [
            {"corridor": c["corridor"], "enabled": True, "demand": c["demand"],
             "capacity": c["capacity"], "pressure": c["pressure"],
             "overflow": c["overflow"], "rerouted_vehicles": c["rerouted"],
             "remaining_queue": c["remaining_queue"]}
            for c in plan.get("corridors", []) if c.get("enabled", False)
        ]
        if export.get("rerouting", []) != plan_corridors:
            raise ValueError("SUMO export corridor actions differ from the decoded plan")
        if export.get("signal_updates", []) != plan.get("signal_changes", []):
            raise ValueError("SUMO export signal actions differ from the decoded plan")
        if export.get("restrictions", []) != plan.get("restrictions", []):
            raise ValueError("SUMO export restrictions differ from the decoded plan")

        result_dir = BASE_DIR / "results"
        solver_values = {variable.id: int(bit) for variable, bit in zip(variables, bits)}
        solver_result = {
            "mode": optimizer_used,
            "runtime_seconds": opt_runtime,
            "objective_value": objective_value,
            "bitstring": bitstring,
            "variables": solver_values,
        }
        _write_json_atomic(result_dir / "qaoa_solution.json", solver_result)
        _write_json_atomic(FINAL_PLAN_FILE, plan)

        # Confirm all three result artifacts describe this exact optimization.
        persisted_solver = json.loads((result_dir / "qaoa_solution.json").read_text(encoding="utf-8"))
        persisted_plan = json.loads(FINAL_PLAN_FILE.read_text(encoding="utf-8"))
        persisted_export = json.loads((result_dir / "sumo_input.json").read_text(encoding="utf-8"))
        if not (
            persisted_solver.get("bitstring") == bitstring
            and persisted_plan.get("bitstring") == bitstring
            and persisted_export.get("optimizer", {}).get("bitstring") == bitstring
        ):
            raise ValueError("Persisted optimization artifacts do not share one bitstring")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Traffic plan decoding or artifact consistency failed: {str(e)}"
        )

    runtime = round(time.time() - start_time, 3)

    response_payload = {
        "message_id": message_id,
        "simulation_id": simulation_id,
        "scenario_id": scenario_id,
        "optimizer_used": optimizer_used,
        "objective_value": float(objective_value),
        "bitstring": bitstring,
        "corridors": plan.get("corridors", []),
        "signal_changes": plan.get("signal_changes", []),
        "restrictions": plan.get("restrictions", []),
        "benefits": plan.get("benefits", {"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0}),
        "runtime_seconds": runtime,
        "status": "completed",
        "applied_to_sumo": False
    }

    # Cache result
    RESULT_CACHE[simulation_id] = response_payload

    return response_payload

@app.get("/api/quantum/optimization/{simulation_id}")
def get_cached_optimization(simulation_id: str):
    """Retrieves the latest cached optimization result for a given simulation ID."""
    if simulation_id in RESULT_CACHE:
        return RESULT_CACHE[simulation_id]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No optimization run found for simulation_id: {simulation_id}"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
