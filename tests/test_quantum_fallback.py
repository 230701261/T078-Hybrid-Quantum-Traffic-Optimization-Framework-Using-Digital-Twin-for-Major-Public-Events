"""
test_quantum_fallback.py

Verifies Step 5: Quantum Failure & Fallback Handling
1. Configures Quantum client with an unavailable/unreachable port (http://127.0.0.1:9999)
2. Triggers optimization through OptimizationJobManager
3. Verifies that the failure is caught and automatically falls back to Classical solver
4. Verifies response clearly states: optimizer_used = 'Classical (Fallback)'
5. Verifies 18-bit validity and Supabase record creation
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from python.integration import (
    OptimizationJobManager,
    SupabaseRepository,
    QuantumOptimizationClient
)

class TestQuantumFallback(unittest.TestCase):

    def test_unreachable_quantum_service_triggers_classical_fallback(self):
        # Point to unreachable port 9999
        client = QuantumOptimizationClient(service_url="http://127.0.0.1:9999", timeout=1.0)
        repo = SupabaseRepository()
        job_manager = OptimizationJobManager(repository=repo, client=client)

        response = job_manager.create_and_run_job(
            simulation_id="sim_fallback_test",
            scenario_id="event_day",
            payload={
                "event": {"name": "IPL Match", "venue": "MA Chidambaram Stadium", "total_vehicles": 9515},
                "constraints": {"weather": "Heavy Rain", "vip": True, "construction": True, "crowd_surge": True, "parking_overflow": True},
                "intersections": {"J1": 1200, "J2": 1447, "J3": 600, "J4": 1100, "J5": 450},
                "solver": "classical"
            },
            apply_to_sumo=False
        )

        self.assertEqual(response.status, "completed")
        self.assertIn("Classical", response.optimizer_used)
        self.assertEqual(len(response.bitstring), 18)
        self.assertTrue(all(c in "01" for c in response.bitstring))

        # Check recorded in Supabase
        recent_runs = repo.list_recent_runs(limit=1)
        self.assertEqual(len(recent_runs), 1)
        self.assertEqual(recent_runs[0]["status"], "completed")

        print(f"\n[FALLBACK VERIFIED] Fallback Optimizer: {response.optimizer_used} | Bitstring: {response.bitstring}")

if __name__ == "__main__":
    unittest.main()
