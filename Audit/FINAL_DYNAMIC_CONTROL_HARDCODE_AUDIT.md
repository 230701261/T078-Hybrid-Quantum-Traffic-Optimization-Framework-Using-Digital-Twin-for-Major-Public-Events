# Final Dynamic Control Hardcode Audit

- **Test ID:** DYN-HARDCODE-2026-10-06
- **Date/time:** 2026-10-06 (Asia/Kolkata)
- **Configuration:** Source review of mapper, operator profile, edge inventory, routing and control endpoints
- **Input:** Search for inline operational effect factors and static route/TLS selection behavior
- **Expected:** Effect coefficients reside in explicit configuration; actual network IDs are read from live SUMO; no fabricated operational success.
- **Actual:** Quantum mapping's route preference and restriction factors now load from `python/operator_profiles.json` and are validated by `operator_profiles()`. Edge inventory IDs and topology are retrieved from TraCI. Corridor aliases remain explicit in the existing Quantum ID mapper by design. VIP still uses configured corridor preference; no dynamic VIP route is implied.
- **API:** Existing APIs; `/api/network/edges` returns live edge details.
- **TraCI:** Live edge/TLS discovery; no live proof of dynamic reroute behavior.
- **Readback:** Unit preflight tests pass; no live hardcode audit execution scenario available in current socket-restricted environment.
- **Evidence:** `python/integration/quantum_sumo_adapter.py`, `python/integration/constraint_engine.py`, `python/scenario_inputs.py`, `python/operator_profiles.json`, `python/traci_controller.py`.
- **Result:** **PARTIAL** — configured factors are not inline; several requested operation types remain corridor-configured rather than dynamic.
