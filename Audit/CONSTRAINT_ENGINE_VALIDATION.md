# Constraint Engine Validation

- **Test ID:** DYN-CONSTRAINT-2026-10-06
- **Date/time:** 2026-10-06 (Asia/Kolkata)
- **Configuration:** Shared `TraCIAdapter.apply_commands` used for both Quantum and Classical optimizer results
- **Input:** Unknown edge, unknown TLS, and hard-closed edge command batches
- **Expected:** Reject the full batch before any TraCI mutation
- **Actual:** All three batches rejected with zero commands applied; edge and TLS targets are checked against live TraCI ID lists; route diversion to a hard-closed edge is rejected.
- **API:** Shared adapter preflight via new `ConstraintEngine`
- **TraCI:** Validation reads edge IDs, lane permissions, and TLS IDs under `TRACI_SESSION_LOCK`
- **Readback:** Unit mocks verified `adaptTraveltime` was not called for rejected batches.
- **Evidence:** `python -m pytest tests/test_constraint_engine.py -q` — **3 passed**.
- **Result:** **PASS** for the currently mapped command types. Route feasibility and arbitrary operator actions are not yet covered.
