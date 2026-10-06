"""
quantum_client.py

HTTP and In-Process client for invoking the Quantum Traffic Optimization Service.
Provides automatic failover, retries, timeout management, and direct in-process
solver execution when running standalone or in CI/CD environments.
"""

import os
import sys
import time
import json
import uuid
import tempfile
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional

from .schemas import OptimizationRequest, OptimizationResponse

class QuantumOptimizationClient:
    def __init__(self, service_url: Optional[str] = None, timeout: float = 60.0):
        self.service_url = service_url or os.environ.get("QUANTUM_SERVICE_URL", "http://127.0.0.1:8001")
        self.timeout = float(os.environ.get("QUANTUM_TIMEOUT_SECONDS", str(timeout)))
        
        # Locate local quantum module directory for fallback in-process solver
        self.quantum_module_dir = Path(__file__).resolve().parent.parent.parent.parent / "quantum_module" / "Quantum-main"
        self._fallback_lock = threading.Lock()

    def optimize(self, request: OptimizationRequest) -> OptimizationResponse:
        """
        Sends optimization request to Quantum Service endpoint.
        Uses the local classical optimizer if the Quantum HTTP service is offline.
        """
        endpoint = f"{self.service_url}/api/quantum/optimize"
        try:
            req_json = request.model_dump_json() if hasattr(request, "model_dump_json") else request.json()
        except Exception:
            req_json = json.dumps(request.dict())
        req_bytes = req_json.encode("utf-8")

        # 1. Attempt HTTP REST API invocation
        try:
            http_req = urllib.request.Request(
                endpoint,
                data=req_bytes,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(http_req, timeout=self.timeout) as response:
                if response.status == 200:
                    resp_data = json.loads(response.read().decode("utf-8"))
                    return OptimizationResponse(**resp_data)
        except Exception as http_err:
            pass

        # 2. Classical in-process fallback when the Quantum API is unavailable.
        return self._run_in_process(request)

    def _run_in_process(self, request: OptimizationRequest) -> OptimizationResponse:
        """Executes the existing classical optimizer as the API-offline fallback."""
        start_time = time.time()
        
        # Ensure Quantum-main and optimization subdirectories are in sys.path
        if self.quantum_module_dir.exists():
            for p in [self.quantum_module_dir, self.quantum_module_dir / "optimization", self.quantum_module_dir / "scenario"]:
                if str(p) not in sys.path:
                    sys.path.insert(0, str(p))

        try:
            from optimization import problem_builder, classical_optimizer, traffic_decision_engine, sumo_exporter

            # The checked-out Quantum repository can be read-only (for example,
            # when it is mounted beside the integration workspace). Keep the
            # actual classical solve unchanged, but isolate all run artifacts.
            scenario_dict = {
                "event": request.payload.event.dict() if hasattr(request.payload.event, "dict") else request.payload.event,
                "constraints": request.payload.constraints.dict() if hasattr(request.payload.constraints, "dict") else request.payload.constraints,
                "intersections": request.payload.intersections
            }
            with self._fallback_lock, tempfile.TemporaryDirectory(prefix="chepauk-classical-fallback-") as temp_dir:
                results_dir = Path(temp_dir) / "results"
                scenario_dir = Path(temp_dir) / "scenario"
                results_dir.mkdir(parents=True)
                scenario_dir.mkdir(parents=True)
                scenario_file = scenario_dir / "scenario_input.json"
                scenario_file.write_text(json.dumps(scenario_dict, indent=4), encoding="utf-8")

                original_paths = {
                    "scenario": problem_builder.SCENARIO_FILE,
                    "classical_results": classical_optimizer.RESULTS_DIR,
                    "plan_results": traffic_decision_engine.RESULTS,
                    "plan_classical_file": traffic_decision_engine.CLASSICAL_FILE,
                    "plan_qaoa_file": traffic_decision_engine.QAOA_FILE,
                    "plan_output": traffic_decision_engine.OUTPUT,
                    "export_results": sumo_exporter.RESULTS_DIR,
                    "export_scenario": sumo_exporter.SCENARIO_FILE,
                    "export_plan": sumo_exporter.PLAN_FILE,
                    "export_output": sumo_exporter.OUTPUT_FILE,
                }
                problem_builder.SCENARIO_FILE = scenario_file
                classical_optimizer.RESULTS_DIR = results_dir
                traffic_decision_engine.RESULTS = results_dir
                traffic_decision_engine.CLASSICAL_FILE = results_dir / "classical_solution.json"
                traffic_decision_engine.QAOA_FILE = results_dir / "qaoa_solution.json"
                traffic_decision_engine.OUTPUT = results_dir / "final_traffic_plan.json"
                sumo_exporter.RESULTS_DIR = results_dir
                sumo_exporter.SCENARIO_FILE = scenario_file
                sumo_exporter.PLAN_FILE = traffic_decision_engine.OUTPUT
                sumo_exporter.OUTPUT_FILE = results_dir / "sumo_input.json"
                try:
                    variables, bits, objective, opt_runtime = classical_optimizer.solve_classically()
                    bitstring = classical_optimizer.save_result(variables, bits, objective, opt_runtime)
                    optimizer_used = "Classical (Fallback)"

                    solver_result = {
                        "mode": optimizer_used,
                        "runtime_seconds": opt_runtime,
                        "objective_value": objective,
                        "bitstring": bitstring,
                        "variables": {variable.id: int(bit) for variable, bit in zip(variables, bits)},
                    }
                    self._write_json_atomic(results_dir / "qaoa_solution.json", solver_result)

                    # Consume this run's solution explicitly to prevent stale QAOA artifacts.
                    plan = traffic_decision_engine.build_plan(
                        solution_override={"bitstring": bitstring},
                        optimizer_override=optimizer_used,
                    )
                    sumo_exporter.build_export(plan_override=plan, scenario_override=scenario_dict)
                    self._write_json_atomic(traffic_decision_engine.OUTPUT, plan)
                    sumo_input = json.loads(sumo_exporter.OUTPUT_FILE.read_text(encoding="utf-8"))
                    persisted_solver = json.loads((results_dir / "qaoa_solution.json").read_text(encoding="utf-8"))
                    persisted_plan = json.loads(traffic_decision_engine.OUTPUT.read_text(encoding="utf-8"))
                    if not (
                        persisted_solver.get("bitstring") == bitstring
                        and persisted_plan.get("bitstring") == bitstring
                        and sumo_input.get("optimizer", {}).get("bitstring") == bitstring
                    ):
                        raise ValueError("Offline fallback artifacts do not share one bitstring")
                finally:
                    problem_builder.SCENARIO_FILE = original_paths["scenario"]
                    classical_optimizer.RESULTS_DIR = original_paths["classical_results"]
                    traffic_decision_engine.RESULTS = original_paths["plan_results"]
                    traffic_decision_engine.CLASSICAL_FILE = original_paths["plan_classical_file"]
                    traffic_decision_engine.QAOA_FILE = original_paths["plan_qaoa_file"]
                    traffic_decision_engine.OUTPUT = original_paths["plan_output"]
                    sumo_exporter.RESULTS_DIR = original_paths["export_results"]
                    sumo_exporter.SCENARIO_FILE = original_paths["export_scenario"]
                    sumo_exporter.PLAN_FILE = original_paths["export_plan"]
                    sumo_exporter.OUTPUT_FILE = original_paths["export_output"]

            runtime = round(time.time() - start_time, 3)
            return OptimizationResponse(
                message_id=request.message_id,
                simulation_id=request.simulation_id,
                scenario_id=request.scenario_id,
                optimizer_used=optimizer_used,
                bitstring=bitstring,
                objective_value=float(objective),
                corridors=plan.get("corridors", []),
                signal_changes=plan.get("signal_changes", []),
                restrictions=plan.get("restrictions", []),
                benefits=plan.get("benefits", {"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0}),
                runtime_seconds=runtime,
                status="completed",
                applied_to_sumo=False
            )

        except Exception as e:
            runtime = round(time.time() - start_time, 3)
            return OptimizationResponse(
                message_id=request.message_id,
                simulation_id=request.simulation_id,
                scenario_id=request.scenario_id,
                optimizer_used="None (Failed)",
                bitstring="000000000000000000",
                objective_value=None,
                corridors=[],
                signal_changes=[],
                restrictions=[],
                benefits={"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0},
                runtime_seconds=runtime,
                status="failed",
                error=str(e)
            )

    @staticmethod
    def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
        temporary_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary_path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
        try:
            temporary_path.replace(path)
        except PermissionError:
            # Windows security/AV filters can deny an atomic rename in a
            # private TemporaryDirectory even though both files are writable.
            # These artifacts are isolated to this fallback invocation, so a
            # direct write is safe and keeps the classical fallback usable.
            path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
            temporary_path.unlink(missing_ok=True)
