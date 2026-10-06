"""
test_quantum_digital_twin_integration.py

Comprehensive Unit & Integration Test Suite for:
1. Request & Response Contract Validation
2. Bitstring & Constraint Validator
3. ID Mapping Layer (Quantum <-> Canonical <-> SUMO)
4. Supabase Repository Lifecycle & Idempotency
5. Quantum Optimization Client Execution
6. Command Mapper & TraCI Adapter Translation
7. End-to-End Simulation Integration Lifecycle
"""

import sys
import os
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from python.integration.schemas import (
    OptimizationRequest,
    OptimizationRequestPayload,
    OptimizationResponse,
    CorridorAction,
    SignalChangeAction,
    RestrictionAction,
    OptimizationBenefits
)
from python.integration.id_mapper import (
    map_quantum_corridor_to_sumo,
    map_quantum_junction_to_sumo_tls,
    get_canonical_corridor_id,
    get_canonical_junction_id,
    CORRIDOR_MAP,
    JUNCTION_MAP
)
from python.integration.supabase_repository import SupabaseRepository
from python.integration.quantum_sumo_adapter import (
    QuantumResultValidator,
    QuantumToTrafficMapper
)
from python.integration.quantum_client import QuantumOptimizationClient
from python.integration.job_manager import OptimizationJobManager

class TestQuantumDigitalTwinIntegration(unittest.TestCase):

    def setUp(self):
        self.repo = SupabaseRepository()
        self.client = QuantumOptimizationClient()
        self.job_manager = OptimizationJobManager(repository=self.repo, client=self.client)

    # --------------------------------------------------------------------------
    # 1. ID MAPPING TESTS
    # --------------------------------------------------------------------------
    def test_corridor_id_mapping(self):
        """Verify all 4 Quantum corridors map to valid SUMO edges."""
        corridors = ["Anna Salai", "Wallajah Road", "Kamarajar Salai", "Triplicane High Road"]
        for c in corridors:
            edges = map_quantum_corridor_to_sumo(c)
            self.assertIsInstance(edges, list)
            self.assertGreater(len(edges), 0)
            canonical = get_canonical_corridor_id(c)
            self.assertIsInstance(canonical, str)
            self.assertTrue(canonical.startswith("corridor_"))

    def test_junction_id_mapping(self):
        """Verify Quantum J1..J10 map to valid SUMO traffic light IDs."""
        for j_id in [f"J{i}" for i in range(1, 11)]:
            tls_id = map_quantum_junction_to_sumo_tls(j_id)
            self.assertIsInstance(tls_id, str)
            self.assertTrue(tls_id.startswith("J_"))
            canonical = get_canonical_junction_id(j_id)
            self.assertTrue(canonical.startswith("junction_"))

    def test_invalid_mapping_raises_key_error(self):
        """Verify unknown IDs raise KeyError instead of silent failure."""
        with self.assertRaises(KeyError):
            map_quantum_corridor_to_sumo("Unknown Expressway")
        with self.assertRaises(KeyError):
            map_quantum_junction_to_sumo_tls("J99")

    # --------------------------------------------------------------------------
    # 2. VALIDATOR & BITSTRING TESTS
    # --------------------------------------------------------------------------
    def test_bitstring_validator_valid(self):
        """Valid 18-bit string must pass validation."""
        resp = OptimizationResponse(
            message_id="msg_001",
            simulation_id="sim_001",
            scenario_id="scen_001",
            optimizer_used="Quantum",
            bitstring="101001010000001000",
            corridors=[],
            signal_changes=[],
            restrictions=[],
            benefits=OptimizationBenefits(travel_time_saved_minutes=4.2, queue_reduction_percent=18.5),
            status="completed"
        )
        self.assertTrue(QuantumResultValidator.validate(resp))

    def test_bitstring_validator_invalid_length(self):
        """Bitstrings not equal to 18 bits must fail validation."""
        with self.assertRaises(ValueError):
            OptimizationResponse(
                message_id="msg_002",
                simulation_id="sim_002",
                scenario_id="scen_002",
                optimizer_used="Quantum",
                bitstring="101", # Too short
                benefits=OptimizationBenefits(travel_time_saved_minutes=0.0, queue_reduction_percent=0.0)
            )

    # --------------------------------------------------------------------------
    # 3. COMMAND MAPPER TESTS
    # --------------------------------------------------------------------------
    def test_quantum_to_traffic_command_mapping(self):
        """Verify decoded plan generates concrete DigitalTwinCommands."""
        resp = OptimizationResponse(
            message_id="msg_003",
            simulation_id="sim_003",
            scenario_id="scen_003",
            optimizer_used="Quantum",
            bitstring="100010000000000000",
            corridors=[
                CorridorAction(
                    corridor="Anna Salai",
                    enabled=True,
                    demand=1200,
                    capacity=428,
                    pressure=2.8,
                    overflow=772,
                    rerouted=85,
                    remaining_queue=687
                )
            ],
            signal_changes=[
                SignalChangeAction(
                    junction="J1",
                    old_green=25,
                    new_green=37,
                    extra_green=12
                )
            ],
            restrictions=[],
            benefits=OptimizationBenefits(travel_time_saved_minutes=3.2, queue_reduction_percent=12.0),
            status="completed"
        )

        commands = QuantumToTrafficMapper.map_response_to_commands(resp)
        self.assertGreater(len(commands), 0)

        # Check Signal Command
        sig_cmds = [c for c in commands if c.action_type == "signal_extension"]
        self.assertEqual(len(sig_cmds), 1)
        self.assertEqual(sig_cmds[0].sumo_target_id, "J_NW")
        self.assertEqual(sig_cmds[0].parameters["extra_green"], 12)

        # Check Route Diversion Commands
        route_cmds = [c for c in commands if c.action_type == "route_diversion"]
        self.assertGreaterEqual(len(route_cmds), 1)
        self.assertIn("E_WEST_1", [c.sumo_target_id for c in route_cmds])

    # --------------------------------------------------------------------------
    # 4. SUPABASE REPOSITORY & IDEMPOTENCY TESTS
    # --------------------------------------------------------------------------
    def test_supabase_repository_lifecycle_and_idempotency(self):
        """Verify complete repository lifecycle and idempotency guard."""
        run_id = self.repo.create_optimization_run(
            simulation_id="sim_test_001",
            scenario_id="scen_test_001",
            message_id="msg_test_001",
            optimizer="Quantum",
            status="created"
        )
        self.assertIsNotNone(run_id)

        # Update to completed
        dummy_resp = OptimizationResponse(
            message_id="msg_test_001",
            simulation_id="sim_test_001",
            scenario_id="scen_test_001",
            optimizer_used="Quantum",
            bitstring="100010000000000000",
            benefits=OptimizationBenefits(travel_time_saved_minutes=2.5, queue_reduction_percent=10.0),
            status="completed"
        )
        self.repo.update_run_completed(run_id, dummy_resp)

        # Check not yet applied
        self.assertFalse(self.repo.is_run_applied(run_id))

        # Mark applied
        self.repo.mark_run_applied(run_id)
        self.assertTrue(self.repo.is_run_applied(run_id))

        # Check idempotency check
        applied_again = self.repo.is_run_applied(run_id)
        self.assertTrue(applied_again)

    # --------------------------------------------------------------------------
    # 5. END-TO-END OPTIMIZATION JOB LIFECYCLE TEST
    # --------------------------------------------------------------------------
    def test_end_to_end_job_lifecycle(self):
        """Runs one full optimization cycle without SUMO active (dry-run mode)."""
        response = self.job_manager.create_and_run_job(
            simulation_id="sim_e2e_test",
            scenario_id="event_day",
            payload={
                "event": {"name": "IPL Match", "venue": "MA Chidambaram Stadium", "total_vehicles": 9515},
                "constraints": {"weather": "Heavy Rain", "vip": True, "construction": True, "crowd_surge": True, "parking_overflow": True},
                "intersections": {"J1": 1200, "J2": 1447, "J3": 600, "J4": 1100, "J5": 450},
                "solver": "classical" # Use classical for deterministic fast unit test
            },
            apply_to_sumo=False # No active TraCI instance during standalone unit test
        )

        self.assertEqual(response.status, "completed")
        self.assertEqual(len(response.bitstring), 18)
        self.assertGreaterEqual(len(response.corridors), 4)
        self.assertGreaterEqual(response.benefits.travel_time_saved_minutes, 0.0)

if __name__ == "__main__":
    unittest.main()
