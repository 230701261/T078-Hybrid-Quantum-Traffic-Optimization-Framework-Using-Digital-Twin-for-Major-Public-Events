"""
test_real_quantum_api.py

Tests the standalone Quantum API service running on port 8001.
1. Starts the Quantum API service in a background subprocess / thread
2. Sends a POST /api/quantum/optimize request with realistic Event Day payload
3. Validates all response fields, 18-bit bitstring, corridors, signals, restrictions, benefits
4. Tests health endpoint GET /health
5. Terminates server cleanly
"""

import sys
import time
import json
import uuid
import urllib.request
import urllib.error
import subprocess
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
QUANTUM_DIR = Path(__file__).resolve().parent.parent.parent / "quantum_module" / "Quantum-main"

class TestRealQuantumAPI(unittest.TestCase):
    process = None

    @classmethod
    def setUpClass(cls):
        # Start standalone Quantum API server on port 8001
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8001", "--log-level", "warning"],
            cwd=str(QUANTUM_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # Wait up to 5 seconds for server to start
        for _ in range(10):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        if cls.process:
            cls.process.terminate()
            cls.process.wait()

    def test_quantum_api_health(self):
        """Verify GET /health returns 200 with 18 decision variables."""
        req = urllib.request.Request("http://127.0.0.1:8001/health")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["decision_variables"], 18)

    def test_real_quantum_api_optimize_endpoint(self):
        """Verify POST /api/quantum/optimize executes and returns full 18-bit plan."""
        req_payload = {
            "message_id": str(uuid.uuid4()),
            "simulation_id": "sim_real_api_test",
            "scenario_id": "event_day",
            "event": {
                "name": "IPL Match (CSK vs MI)",
                "venue": "MA Chidambaram Stadium",
                "total_vehicles": 9515
            },
            "constraints": {
                "weather": "Heavy Rain",
                "vip": True,
                "construction": True,
                "crowd_surge": True,
                "parking_overflow": True
            },
            "intersections": {
                "J1": 1200,
                "J2": 1447,
                "J3": 600,
                "J4": 1100,
                "J5": 450
            },
            "solver": "qaoa" # Runs QAOA
        }

        req_bytes = json.dumps(req_payload).encode("utf-8")
        http_req = urllib.request.Request(
            "http://127.0.0.1:8001/api/quantum/optimize",
            data=req_bytes,
            headers={"Content-Type": "application/json"}
        )

        t_start = time.time()
        with urllib.request.urlopen(http_req, timeout=45.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t_start

        # Validate all required fields
        self.assertIn("message_id", data)
        self.assertIn("simulation_id", data)
        self.assertIn("scenario_id", data)
        self.assertIn("optimizer_used", data)
        self.assertIn("bitstring", data)
        self.assertIn("corridors", data)
        self.assertIn("signal_changes", data)
        self.assertIn("restrictions", data)
        self.assertIn("benefits", data)
        self.assertIn("runtime_seconds", data)
        self.assertIn("status", data)

        # Validate 18 binary bits
        bitstring = data["bitstring"]
        self.assertEqual(len(bitstring), 18)
        self.assertTrue(all(c in "01" for c in bitstring))

        self.assertEqual(data["status"], "completed")
        self.assertGreaterEqual(len(data["corridors"]), 4)
        self.assertGreater(data["benefits"]["travel_time_saved_minutes"], 0.0)

        print(f"\n[REAL QUANTUM API TEST PASSED] Optimizer: {data['optimizer_used']} | Bitstring: {bitstring} | Runtime: {elapsed:.2f}s")

if __name__ == "__main__":
    unittest.main()
