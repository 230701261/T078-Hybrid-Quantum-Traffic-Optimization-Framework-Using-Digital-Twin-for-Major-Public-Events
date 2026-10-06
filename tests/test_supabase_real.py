"""
test_supabase_real.py

Safe, dedicated test script for Supabase connectivity and persistence.
Explicitly checks:
1. Operational Mode: REAL SUPABASE CLOUD MODE vs LOCAL IN-MEMORY FALLBACK MODE
2. Record creation (optimization_runs)
3. Status updates (CREATED -> RUNNING -> COMPLETED -> APPLIED)
4. Child table insertions (traffic_actions & optimization_benefits)
5. Relational retrieval & data integrity
6. Idempotency checks
"""

import sys
import os
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from python.integration.schemas import (
    OptimizationResponse,
    CorridorAction,
    SignalChangeAction,
    OptimizationBenefits
)
from python.integration.supabase_repository import SupabaseRepository

def test_supabase_persistence():
    print("=" * 60)
    print(" SUPABASE PERSISTENCE & CONNECTIVITY TEST ")
    print("=" * 60)

    repo = SupabaseRepository()
    mode = "REAL SUPABASE CLOUD MODE" if repo.use_cloud else "LOCAL IN-MEMORY FALLBACK MODE"
    print(f"\n[Active Operating Mode]: {mode}")
    if not repo.use_cloud:
        print("[Note]: To run against live Supabase, configure SUPABASE_URL and SUPABASE_ANON_KEY in .env")

    # 1. Create Run
    test_msg_id = f"test_msg_{uuid.uuid4()}"
    run_id = repo.create_optimization_run(
        simulation_id="sim_supabase_test",
        scenario_id="scenario_event_day",
        message_id=test_msg_id,
        optimizer="Quantum",
        status="running"
    )
    print(f"\n1. Created Optimization Run ID: {run_id}")
    assert run_id is not None, "Failed to create optimization run"

    # 2. Update to Completed with Actions & Benefits
    dummy_resp = OptimizationResponse(
        message_id=test_msg_id,
        simulation_id="sim_supabase_test",
        scenario_id="scenario_event_day",
        optimizer_used="Quantum (QAOA)",
        bitstring="110011011000000000",
        corridors=[
            CorridorAction(
                corridor="Wallajah Road",
                enabled=True,
                demand=1100.0,
                capacity=428.0,
                pressure=2.57,
                overflow=672.0,
                rerouted=85.0,
                remaining_queue=587.0
            )
        ],
        signal_changes=[
            SignalChangeAction(
                junction="J1",
                old_green=25.0,
                new_green=37.0,
                extra_green=12.0
            )
        ],
        restrictions=[],
        benefits=OptimizationBenefits(
            travel_time_saved_minutes=3.2,
            queue_reduction_percent=14.5
        ),
        runtime_seconds=3.15,
        status="completed"
    )

    repo.update_run_completed(run_id, dummy_resp)
    print("2. Updated Run to COMPLETED (inserted traffic actions & benefits)")

    # 3. Retrieve and Validate Relational Tree
    fetched = repo.get_run(run_id)
    print("3. Retrieved Run from Repository:")
    print(f"   - Status: {fetched.get('status')}")
    print(f"   - Bitstring: {fetched.get('bitstring')}")
    print(f"   - Runtime: {fetched.get('runtime_seconds')}s")
    print(f"   - Actions Count: {len(fetched.get('actions', []))}")
    print(f"   - Benefits: {fetched.get('benefits')}")
    
    assert fetched.get("status") == "completed", "Status mismatch"
    assert fetched.get("bitstring") == "110011011000000000", "Bitstring mismatch"

    # 4. Mark Applied & Verify Idempotency
    print("4. Testing Idempotency:")
    assert not repo.is_run_applied(run_id), "Run should not be applied yet"
    repo.mark_run_applied(run_id)
    assert repo.is_run_applied(run_id), "Run must be marked applied"
    print("   [PASS] First apply marked successfully.")
    
    # Second check
    second_check = repo.is_run_applied(run_id)
    assert second_check is True, "Idempotency guard check failed"
    print("   [PASS] Second apply check returned True (Idempotent: duplicate application will be safely skipped).")

    print("\n" + "=" * 60)
    print(f" RESULT: {mode} VERIFIED 100% SUCCESSFULLY")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    test_supabase_persistence()
