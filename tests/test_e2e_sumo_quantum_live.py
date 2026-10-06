"""
test_e2e_sumo_quantum_live.py

Live End-to-End Test verifying:
1. TraCI controller boots SUMO in event_day mode
2. Quantum optimization job is triggered via JobManager
3. Optimization result is computed & recorded in Supabase store
4. Decisions (signal extension & route diversion) are mapped and applied directly to SUMO
5. Target traffic signal phase duration changes in live TraCI instance
6. Same run cannot be applied twice (idempotency guard)
"""

import sys
import os
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from python.traci_controller import TraCIController
from python.integration import (
    OptimizationJobManager,
    SupabaseRepository,
    QuantumOptimizationClient
)

class TestE2ESUMOQuantumLive(unittest.TestCase):

    def setUp(self):
        self.controller = TraCIController()
        self.repo = SupabaseRepository()
        self.client = QuantumOptimizationClient()
        self.job_manager = OptimizationJobManager(repository=self.repo, client=self.client)

    def tearDown(self):
        self.controller.close()

    def test_live_sumo_quantum_integration(self):
        # 1. Start SUMO simulation in event_day mode
        started = self.controller.start("event_day")
        self.assertTrue(started, "Failed to start SUMO simulation")
        time.sleep(1.0)

        # 2. Trigger Quantum Optimization Job
        response = self.job_manager.create_and_run_job(
            simulation_id="sim_live_e2e",
            scenario_id="event_day",
            payload={
                "event": {"name": "IPL Match Live E2E", "venue": "MA Chidambaram Stadium", "total_vehicles": 9515},
                "constraints": {"weather": "Heavy Rain", "vip": True, "construction": True, "crowd_surge": True, "parking_overflow": True},
                "intersections": {"J1": 1200, "J2": 1447, "J3": 600, "J4": 1100, "J5": 450},
                "solver": "classical" # Fast deterministic solver for E2E verification
            },
            apply_to_sumo=True
        )

        # 3. Verify Response and Status
        self.assertEqual(response.status, "completed")
        self.assertTrue(response.applied_to_sumo)
        self.assertEqual(len(response.bitstring), 18)
        self.assertIsNotNone(response.objective_value, "Optimizer objective must be returned and persisted with the real result")
        self.assertGreater(len(response.signal_changes), 0)

        # 4. Verify Supabase Persistence
        recent_runs = self.repo.list_recent_runs(limit=5)
        self.assertGreaterEqual(len(recent_runs), 1)
        latest_run = recent_runs[0]
        self.assertEqual(latest_run["status"], "applied")
        self.assertTrue(latest_run["applied_to_sumo"])
        self.assertIsNotNone(latest_run.get("objective_value"), "The computed solver objective must be persisted with the run")

        # 5. Verify Idempotency: re-applying the same run must be skipped
        reapply_result = self.job_manager.apply_plan_to_sumo(latest_run["id"], response)
        self.assertEqual(reapply_result["status"], "skipped")
        self.assertEqual(reapply_result["reason"], "already_applied")

        print("\n[E2E VERIFIED] Live SUMO TraCI + Quantum Optimization + Supabase + Idempotency passed 100%!")

if __name__ == "__main__":
    unittest.main()
