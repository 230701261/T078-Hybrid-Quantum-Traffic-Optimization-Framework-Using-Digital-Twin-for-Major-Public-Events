"""
supabase_repository.py

Persistent storage repository for Quantum Traffic Digital Twin integration.
Supports:
1. Live Supabase PostgreSQL connection (via SUPABASE_URL and SUPABASE_ANON_KEY / SERVICE_KEY)
2. Resilient In-Memory local repository fallback for local testing & offline environments.
"""

import os
import threading
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from dotenv import load_dotenv
    # Load .env from project root if present
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except Exception:
    pass

from .schemas import OptimizationResponse, DigitalTwinCommand, get_utc_timestamp

class SupabaseRepository:
    def __init__(self, supabase_url: Optional[str] = None, supabase_key: Optional[str] = None):
        self.supabase_url = supabase_url or os.environ.get("SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        
        self.client = None
        self.use_cloud = False
        self.cloud_status = "NOT CONFIGURED"
        self.cloud_error: Optional[str] = None
        
        # In-memory thread-safe local fallback store
        self._lock = threading.Lock()
        self._simulations: Dict[str, Dict[str, Any]] = {}
        self._scenarios: Dict[str, Dict[str, Any]] = {}
        self._optimization_runs: Dict[str, Dict[str, Any]] = {}
        self._traffic_actions: Dict[str, List[Dict[str, Any]]] = {}
        self._optimization_benefits: Dict[str, Dict[str, Any]] = {}
        self._optimization_results: Dict[str, Dict[str, Any]] = {}
        self._applied_run_ids: set = set()
        self._responses_by_run: Dict[str, Dict[str, Any]] = {}

        if self.supabase_url and self.supabase_key and "your-project-id" not in self.supabase_url:
            try:
                from supabase import create_client
                self.client = create_client(self.supabase_url, self.supabase_key)
                self.check_cloud_connection()
            except Exception as e:
                self.cloud_status = "UNAVAILABLE"
                self.cloud_error = str(e)
                print(f"[Supabase Warning] Cloud Supabase unavailable ({e}). Operating in LOCAL IN-MEMORY FALLBACK MODE.")
                self.use_cloud = False
        else:
            print("[Supabase] No cloud credentials configured in environment. Operating in LOCAL IN-MEMORY FALLBACK MODE.")

    def check_cloud_connection(self) -> dict[str, Any]:
        """A client object is not a connection; perform a harmless database read."""
        if not self.supabase_url or not self.supabase_key or self.client is None:
            self.use_cloud = False
            self.cloud_status = "NOT CONFIGURED"
            return {"status": self.cloud_status, "error": None}
        try:
            self.client.table("simulations").select("id").limit(1).execute()
            self.use_cloud = True
            self.cloud_status = "CONNECTED"
            self.cloud_error = None
            return {"status": self.cloud_status, "error": None}
        except Exception as ex:
            self.use_cloud = False
            self.cloud_status = "UNAVAILABLE"
            self.cloud_error = str(ex)
            print(f"[Supabase Health Error] {ex}; continuing in LOCAL IN-MEMORY FALLBACK MODE")
            return {"status": self.cloud_status, "error": self.cloud_error}

    def _cloud_failure(self, operation: str, error: Exception) -> None:
        self.cloud_status = "UNAVAILABLE"
        self.cloud_error = f"{operation}: {error}"
        self.use_cloud = False
        print(f"[Supabase {operation} Error] {error}; future writes use LOCAL IN-MEMORY FALLBACK MODE")

    # ==========================================================================
    # 1. OPTIMIZATION RUN RECORDING
    # ==========================================================================

    def create_optimization_run(
        self,
        simulation_id: str,
        scenario_id: str,
        message_id: str,
        optimizer: str,
        bitstring: str = "",
        status: str = "created"
    ) -> str:
        """Creates a new optimization run entry and returns the generated UUID."""
        run_id = str(uuid.uuid4())
        record = {
            "id": run_id,
            "message_id": message_id,
            "simulation_id": simulation_id,
            "scenario_id": scenario_id,
            "optimizer": optimizer,
            "bitstring": bitstring,
            "status": status,
            "applied_to_sumo": False,
            "created_at": get_utc_timestamp(),
            "completed_at": None,
            "applied_at": None,
            "error_message": None
        }

        with self._lock:
            for existing in self._optimization_runs.values():
                if existing.get("message_id") == message_id:
                    return existing["id"]
            if self.use_cloud and self.client:
                try:
                    self.client.table("optimization_runs").insert(record).execute()
                except Exception as e:
                    self._cloud_failure("Insert", e)
            self._optimization_runs[run_id] = record

        return run_id

    def update_run_completed(
        self,
        run_id: str,
        response: OptimizationResponse
    ):
        """Updates run status to 'completed' and inserts detailed traffic actions & benefits."""
        now = get_utc_timestamp()

        # 1. Update run row
        updates = {
            "status": response.status,
            "optimizer": response.optimizer_used,
            "bitstring": response.bitstring,
            "objective_value": response.objective_value,
            "runtime_seconds": response.runtime_seconds,
            "completed_at": now,
            "error_message": response.error
        }

        if self.use_cloud and self.client:
            try:
                self.client.table("optimization_runs").update(updates).eq("id", run_id).execute()
            except Exception as e:
                self._cloud_failure("Update", e)

        with self._lock:
            if run_id in self._optimization_runs:
                self._optimization_runs[run_id].update(updates)
            self._responses_by_run[run_id] = response.model_dump()

        # 2. Store Traffic Actions
        actions_data = []
        for c in response.corridors:
            actions_data.append({
                "id": str(uuid.uuid4()),
                "optimization_run_id": run_id,
                "action_type": "route_diversion",
                "logical_target": c.corridor,
                "canonical_target": c.corridor.lower().replace(" ", "_"),
                "sumo_target_id": c.corridor,
                "enabled": c.enabled,
                "demand": c.demand,
                "capacity": c.capacity,
                "pressure": c.pressure,
                "overflow": c.overflow,
                "rerouted": c.rerouted,
                "remaining_queue": c.remaining_queue,
                "created_at": now
            })

        for s in response.signal_changes:
            actions_data.append({
                "id": str(uuid.uuid4()),
                "optimization_run_id": run_id,
                "action_type": "signal_extension",
                "logical_target": s.junction,
                "canonical_target": f"junction_{s.junction.lower()}",
                "sumo_target_id": s.junction,
                "enabled": True,
                "old_value": s.old_green,
                "new_value": s.new_green,
                "delta_value": s.extra_green,
                "created_at": now
            })

        for r in response.restrictions:
            actions_data.append({
                "id": str(uuid.uuid4()),
                "optimization_run_id": run_id,
                "action_type": "temporary_restriction",
                "logical_target": r.corridor,
                "canonical_target": r.corridor.lower().replace(" ", "_"),
                "sumo_target_id": r.corridor,
                "enabled": True,
                "created_at": now
            })

        if self.use_cloud and self.client and actions_data:
            try:
                self.client.table("traffic_actions").insert(actions_data).execute()
            except Exception as e:
                self._cloud_failure("Actions Insert", e)

        with self._lock:
            self._traffic_actions[run_id] = actions_data

        # 3. Store Benefits
        benefits_record = {
            "id": str(uuid.uuid4()),
            "optimization_run_id": run_id,
            "travel_time_saved_minutes": response.benefits.travel_time_saved_minutes,
            "queue_reduction_percent": response.benefits.queue_reduction_percent,
            "created_at": now
        }

        if self.use_cloud and self.client:
            try:
                self.client.table("optimization_benefits").insert(benefits_record).execute()
            except Exception as e:
                self._cloud_failure("Benefits Insert", e)

        with self._lock:
            self._optimization_benefits[run_id] = benefits_record

    def mark_run_applied(self, run_id: str):
        """Marks that the optimization run was successfully applied to the SUMO simulation."""
        now = get_utc_timestamp()
        updates = {
            "status": "applied",
            "applied_to_sumo": True,
            "applied_at": now
        }

        if self.use_cloud and self.client:
            try:
                self.client.table("optimization_runs").update(updates).eq("id", run_id).execute()
            except Exception as e:
                self._cloud_failure("Mark Applied", e)

        with self._lock:
            if run_id in self._optimization_runs:
                self._optimization_runs[run_id].update(updates)
            self._applied_run_ids.add(run_id)
            if run_id in self._responses_by_run:
                self._responses_by_run[run_id]["applied_to_sumo"] = True

    def mark_run_failed(self, run_id: str, error_message: str):
        updates = {"status": "failed", "applied_to_sumo": False, "error_message": error_message}
        if self.use_cloud and self.client:
            try:
                self.client.table("optimization_runs").update(updates).eq("id", run_id).execute()
            except Exception as ex:
                self._cloud_failure("Mark Failed", ex)
        with self._lock:
            if run_id in self._optimization_runs:
                self._optimization_runs[run_id].update(updates)
            if run_id in self._responses_by_run:
                self._responses_by_run[run_id].update({"status": "failed", "applied_to_sumo": False,
                                                       "error": error_message})
            self._applied_run_ids.discard(run_id)

    def is_run_applied(self, run_id: str) -> bool:
        """Idempotency check: returns True if this optimization run has already been applied."""
        with self._lock:
            if run_id in self._applied_run_ids:
                return True
            run = self._optimization_runs.get(run_id)
            if run and run.get("applied_to_sumo", False):
                return True
        return False

    def find_run_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Find an existing run by idempotency key in cloud or local mode."""
        if self.use_cloud and self.client:
            try:
                res = (self.client.table("optimization_runs").select("*")
                       .eq("message_id", message_id).limit(1).execute())
                if res.data:
                    return res.data[0]
            except Exception as e:
                self._cloud_failure("Idempotency Lookup", e)
        with self._lock:
            for run in self._optimization_runs.values():
                if run.get("message_id") == message_id:
                    return dict(run)
        return None

    def get_cached_response_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        run = self.find_run_by_message_id(message_id)
        if not run:
            return None
        with self._lock:
            cached = self._responses_by_run.get(run["id"])
            return dict(cached) if cached else None

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetches full optimization run details including actions and benefits."""
        if self.use_cloud and self.client:
            try:
                res = self.client.table("optimization_runs").select("*").eq("id", run_id).execute()
                if res.data:
                    run_data = res.data[0]
                    act_res = self.client.table("traffic_actions").select("*").eq("optimization_run_id", run_id).execute()
                    ben_res = self.client.table("optimization_benefits").select("*").eq("optimization_run_id", run_id).execute()
                    run_data["actions"] = act_res.data or []
                    run_data["benefits"] = ben_res.data[0] if ben_res.data else {}
                    return run_data
            except Exception as e:
                self._cloud_failure("Fetch", e)

        with self._lock:
            if run_id in self._optimization_runs:
                data = dict(self._optimization_runs[run_id])
                data["actions"] = self._traffic_actions.get(run_id, [])
                data["benefits"] = self._optimization_benefits.get(run_id, {})
                return data
        return None

    def list_recent_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Lists recent optimization runs ordered by creation time."""
        if self.use_cloud and self.client:
            try:
                res = self.client.table("optimization_runs").select("*").order("created_at", desc=True).limit(limit).execute()
                if res.data is not None:
                    return res.data
            except Exception as e:
                self._cloud_failure("List", e)

        with self._lock:
            runs = list(self._optimization_runs.values())
            runs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return runs[:limit]
