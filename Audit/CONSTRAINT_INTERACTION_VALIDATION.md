# Constraint Interaction Validation

- **Test ID:** DTC-CONSTRAINTS-20261006
- **Date/time:** 2026-10-06, 14:38–14:47 Asia/Kolkata
- **Feature:** Weather, VIP and construction interactions and optimizer inputs.
- **Input:** Rain profile, VIP on `Anna Salai`, construction on `Kamarajar Salai`; same-corridor VIP/construction request; turn both controls off and restore clear weather.
- **Expected:** Accepted inputs affect both paired SUMO contexts, conflicting VIP/construction selections are rejected, and active constraints remain in shared pair settings used by Quantum and Classical fallback requests.
- **Actual:** Weather/VIP/construction controls returned verified live readbacks; same-corridor conflict returned 422 before restart; controls were restored and SUMO remained healthy. Existing trigger code builds optimization payload from pair constraints/density/route/signal inputs; both optimizers use that shared payload path.
- **TraCI command:** Lane speed and adapted edge travel-time operations; constraint application reuses existing paired scenario-start path. Quantum/Classic payload construction is in `python/server.py` and `python/integration/quantum_client.py`.
- **Readback:** Live operator state and per-controller readbacks; conflict response reason identifies incompatible selection.
- **Evidence:** Live REST operations; `python/server.py`; `python/simulation_pair.py`; `python/integration/quantum_client.py`; full test suite passed 37 tests.
- **Result:** **PARTIAL**. Tested controls and one conflict are verified. Full combinations, all-constraint Quantum E2E, and all-constraint Classical fallback E2E were not run. A central formal constraint-priority engine and validator for every optimizer action remain incomplete.
