"""
job_manager.py

Coordinates the end-to-end Optimization Job Lifecycle:
CREATED -> QUEUED -> RUNNING -> COMPLETED -> APPLIED (or FAILED)

Enforces:
- Idempotency (ensures no optimization result is applied twice)
- Error handling & recovery
- Supabase persistence & audit logging
- Event/Periodic trigger evaluation (avoids per-step overcoupling)
"""

import time
import uuid
import threading
import contextlib
from typing import Dict, Any, Optional, List

from .schemas import (
    OptimizationRequest,
    OptimizationRequestPayload,
    OptimizationResponse,
    DigitalTwinCommand
)
from .supabase_repository import SupabaseRepository
from .quantum_client import QuantumOptimizationClient
from .quantum_sumo_adapter import QuantumResultValidator, QuantumToTrafficMapper, TraCIAdapter

class OptimizationJobManager:
    def __init__(self, repository: Optional[SupabaseRepository] = None, client: Optional[QuantumOptimizationClient] = None,
                 traci_context=None, constraint_context=None):
        self.repo = repository or SupabaseRepository()
        self.client = client or QuantumOptimizationClient()
        self.traci_context = traci_context or contextlib.nullcontext
        self.constraint_context = constraint_context
        self._lock = threading.Lock()
        self._inflight_message_ids = set()
        
        self.is_optimizing = False
        self.last_run_time = 0.0
        self.min_interval_seconds = 60.0  # Cooldown between periodic optimizations
        self.latest_plan: Optional[OptimizationResponse] = None
        self.status_callback = None

    def _emit(self, stage: str, message_id: str, run_id: Optional[str] = None,
              details: Optional[Dict[str, Any]] = None):
        event = {"stage": stage, "message_id": message_id, "run_id": run_id,
                 "timestamp": time.time(), "details": details or {}}
        if self.status_callback:
            self.status_callback(event)
        return event

    def create_and_run_job(
        self,
        simulation_id: str = "sim_chepauk_001",
        scenario_id: str = "scenario_event_day",
        payload: Optional[Dict[str, Any]] = None,
        apply_to_sumo: bool = True,
        message_id: Optional[str] = None
    ) -> OptimizationResponse:
        """
        Executes a complete lifecycle optimization run:
        1. Creates record (CREATED)
        2. Dispatches to Quantum service (RUNNING)
        3. Validates & stores result (COMPLETED)
        4. Maps and applies to SUMO (APPLIED)
        """
        message_id = message_id or str(uuid.uuid4())
        self._emit("QUEUED", message_id)
        existing = self.repo.find_run_by_message_id(message_id)
        if existing:
            self._emit("SKIPPED", message_id, existing.get("id"), {"reason": "duplicate_message_id"})
            return self._already_processed_response(message_id, simulation_id, scenario_id, existing)

        with self._lock:
            if message_id in self._inflight_message_ids:
                self._emit("SKIPPED", message_id, details={"reason": "already_in_flight"})
                return self._skipped_response(message_id, simulation_id, scenario_id)
            if self.is_optimizing:
                print("[JobManager Warning] An optimization job is already active. Rejecting concurrent run.")
                self._emit("REJECTED", message_id, details={"reason": "another_job_is_running"})
                return OptimizationResponse(
                    message_id=message_id,
                    simulation_id=simulation_id,
                    scenario_id=scenario_id,
                    optimizer_used="None",
                    bitstring="000000000000000000",
                    benefits={"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0},
                    status="failed",
                    error="Concurrent optimization job already in progress"
                )
            self.is_optimizing = True
            self._inflight_message_ids.add(message_id)

        run_id = self.repo.create_optimization_run(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            message_id=message_id,
            optimizer="Quantum",
            status="running"
        )
        self._emit("RUNNING", message_id, run_id)

        print(f"\n[INTEGRATION] Starting Optimization Job {run_id} for simulation={simulation_id}, scenario={scenario_id}")

        try:
            req_payload = OptimizationRequestPayload(**payload) if payload else OptimizationRequestPayload()
            request = OptimizationRequest(
                message_id=message_id,
                simulation_id=simulation_id,
                scenario_id=scenario_id,
                payload=req_payload
            )

            t_start = time.time()
            try:
                response = self.client.optimize(request)
                response.runtime_seconds = round(time.time() - t_start, 2)
                if "Fallback" in response.optimizer_used:
                    self._emit("FALLBACK", message_id, run_id,
                               {"optimizer_used": response.optimizer_used})
                self._emit("RESULT_RECEIVED", message_id, run_id,
                           {"optimizer_used": response.optimizer_used})
            except Exception as ex:
                error_msg = f"Optimization invocation failed: {str(ex)}"
                print(f"[OPTIMIZATION ERROR] {error_msg}")
                response = OptimizationResponse(
                    message_id=message_id,
                    simulation_id=simulation_id,
                    scenario_id=scenario_id,
                    optimizer_used="None",
                    bitstring="000000000000000000",
                    benefits={"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0},
                    status="failed",
                    error=error_msg
                )

            # The repository's optimization-run ID is distinct from the
            # caller's idempotency message ID; expose both to the UI/API.
            response.run_id = run_id

            # Validate all decisions before recording or sending any command.
            self._emit("VALIDATING", message_id, run_id)
            if response.status != "failed":
                try:
                    QuantumToTrafficMapper.map_response_to_commands(response)
                except (KeyError, ValueError) as ex:
                    response.status = "failed"
                    response.error = f"Quantum result validation failed: {ex}"

            if response.status == "failed":
                self._emit("FAILED", message_id, run_id, {"error": response.error})
            else:
                self._emit("MAPPING", message_id, run_id)

            self.repo.update_run_completed(run_id, response)
            self.latest_plan = response

            if response.status == "failed" or not response.bitstring or response.bitstring == "000000000000000000":
                print(f"[OPTIMIZATION] run={run_id} status=failed runtime={response.runtime_seconds}s error={response.error}")
                if response.status != "failed":
                    response.status = "failed"
                    response.error = response.error or "Optimizer returned no enabled decisions"
                    self.repo.mark_run_failed(run_id, response.error)
                    self._emit("FAILED", message_id, run_id, {"error": response.error})
                return response

            print(f"[QUANTUM] simulation={simulation_id} optimization={run_id} status=completed bitstring={response.bitstring} runtime={response.runtime_seconds}s")
            if apply_to_sumo:
                self._emit("APPLYING", message_id, run_id)
                result = self.apply_plan_to_sumo(run_id, response)
                if result.get("status") == "failed":
                    response.status = "failed"
                    response.error = result.get("error")
                    self.repo.mark_run_failed(run_id, response.error or "TraCI application failed")
                    self._emit("FAILED", message_id, run_id, {"error": response.error})
                else:
                    response.application_result = result.get("result")
                    self._emit("APPLIED", message_id, run_id,
                               {"application_result": response.application_result})

            self.last_run_time = time.time()
            if response.status != "failed":
                self._emit("COMPLETED", message_id, run_id, {"applied_to_sumo": response.applied_to_sumo})
            self.latest_plan = response
            return response
        except Exception as ex:
            self.repo.mark_run_failed(run_id, str(ex))
            self._emit("FAILED", message_id, run_id, {"error": str(ex)})
            raise
        finally:
            with self._lock:
                self._inflight_message_ids.discard(message_id)
                self.is_optimizing = bool(self._inflight_message_ids)

    def _skipped_response(self, message_id: str, simulation_id: str, scenario_id: str) -> OptimizationResponse:
        return OptimizationResponse(
            message_id=message_id,
            simulation_id=simulation_id,
            scenario_id=scenario_id,
            optimizer_used="Already Processed",
            bitstring="000000000000000000",
            benefits={"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0},
            status="skipped",
            error="already_processed"
        )

    def _already_processed_response(self, message_id: str, simulation_id: str, scenario_id: str, run: Dict[str, Any]) -> OptimizationResponse:
        cached = self.repo.get_cached_response_by_message_id(message_id)
        if cached:
            cached.update(status="skipped", error="already_processed", applied_to_sumo=bool(run.get("applied_to_sumo")))
            return OptimizationResponse(**cached)
        return OptimizationResponse(
            run_id=run.get("id"),
            message_id=message_id,
            simulation_id=run.get("simulation_id", simulation_id),
            scenario_id=run.get("scenario_id", scenario_id),
            optimizer_used=run.get("optimizer", "Already Processed"),
            bitstring=run.get("bitstring") if len(run.get("bitstring", "")) == 18 else "000000000000000000",
            benefits={"travel_time_saved_minutes": 0.0, "queue_reduction_percent": 0.0},
            status="skipped",
            applied_to_sumo=bool(run.get("applied_to_sumo")),
            error="already_processed"
        )

    def apply_plan_to_sumo(self, run_id: str, response: OptimizationResponse) -> Dict[str, Any]:
        """Maps and applies a completed optimization response directly to the active SUMO simulation."""
        # Idempotency Check
        if self.repo.is_run_applied(run_id):
            print(f"[INTEGRATION] Optimization run {run_id} already applied. Skipping duplicate application.")
            return {"status": "skipped", "reason": "already_applied"}

        try:
            # 1. Map to DigitalTwinCommands
            commands = QuantumToTrafficMapper.map_response_to_commands(response)
            
            # 2. Execute via TraCIAdapter
            with self.traci_context():
                validation_context = self.constraint_context() if self.constraint_context else None
                result = TraCIAdapter.apply_commands(commands, validation_context)
            response.application_result = result
            if not result.get("success"):
                return {"status": "failed", "error": "One or more SUMO commands failed readback verification", "result": result}
            # 3. Mark as Applied in Supabase
            self.repo.mark_run_applied(run_id)
            response.applied_to_sumo = True
            
            print(f"[INTEGRATION] optimization={run_id} status=applied commands_applied={result['applied_count']}/{result['total_commands']}")
            print(f"[SUMO] optimization={run_id} status=success")
            return {"status": "success", "result": result}
            
        except Exception as e:
            error_msg = f"Failed applying commands to SUMO: {str(e)}"
            print(f"[SUMO ERROR] optimization={run_id} error={error_msg}")
            return {"status": "failed", "error": error_msg}

    def evaluate_trigger(
        self,
        current_sim_time: float,
        scenario_name: str,
        congestion_ratio: float
    ) -> bool:
        """
        Evaluates whether an automated optimization run should be triggered.
        Triggers when:
        1. Severe congestion occurs (congestion_ratio > 0.35)
        2. Significant cooldown time has elapsed since last optimization
        """
        if self.is_optimizing:
            return False

        now = time.time()
        if (now - self.last_run_time) < self.min_interval_seconds:
            return False

        if scenario_name == "event_day" and congestion_ratio > 0.35:
            return True

        return False
