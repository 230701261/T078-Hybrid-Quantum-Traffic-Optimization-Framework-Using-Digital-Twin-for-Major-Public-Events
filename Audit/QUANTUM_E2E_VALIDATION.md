# Quantum End-to-End Validation

## Real Quantum API

- Original Quantum repository was started from `D:\Work\Project\Traffic\quantum_module\Quantum-main` on port 8001.
- `GET /health`: HTTP 200, `status=healthy`, `decision_variables=18`.
- The API log showed QUBO construction, Ising conversion, and grid-search QAOA progress through 64/64 evaluations.
- A direct real Event Day request returned bitstring `011010010000110001`, objective `-394.64`, runtime 11.003 s, status completed.
- The API returns `objective_value` from the solver’s existing objective calculation; optimizer mathematics were not changed.
- Live UI run ID: `a332cf4e-c22d-4e2d-9872-16aca174ecbc`; simulation ID `pair_922f823ed419_quantum`; scenario `normal_day`; bitstring `110000011000100000`; objective `-367.74`; runtime 10.94 s; application succeeded and UI displayed COMPLETED · APPLIED.
- API and UI reported Quantum optimizer; no hand-built response was injected.

## Live SUMO E2E / duplicate guard

`python tests/test_e2e_sumo_quantum_live.py` passed against the live Quantum API, including assertions that the objective is non-null in both the response and local run record. Run `e7785002-33ec-498e-a214-0cf94f1d54d3` applied 22/22 commands; re-application returned `skipped / already_applied`.

## Quantum-off fallback and request idempotency

With port 8001 stopped, POST `/api/integration/trigger_optimization` with `message_id=FALLBACK-AUDIT-001` returned HTTP 200, `optimizer_used=Classical (Fallback)`, valid 18-bit result, status completed, `applied_to_sumo=true`, 21/21 TraCI commands. Repeating the exact message ID returned `status=skipped`, `error=already_processed`, and no second application.

## Persistence boundary

The repository announced LOCAL IN-MEMORY FALLBACK MODE because Supabase credentials were absent. These runs do not prove cloud persistence.

Final hardening pass (2026-10-06): real Event Day HTTP trigger `FINAL-HARDENING-20261006-01` returned Quantum, bitstring `101011110000000001`, objective `-391.06`, runtime `17.46 s`, completed/applied true, and 24/24 commands successful. Exact duplicate replay returned skipped/already_processed. Supabase stayed in local fallback mode.

With the Quantum API stopped, Event Day trigger `FINAL-HARDENING-20261006-FALLBACK` executed the existing classical optimizer: optimizer `Classical (Fallback)`, 18-bit result `110011011000000000`, objective `-431.2`, runtime `5.21 s`, and 22/22 commands applied. The browser WebSocket displayed `CLASSICAL FALLBACK · APPLIED`. Persistence remained local in-memory.

## Dynamic operator controls verification (2026-10-06)

- The original Quantum API was started from the existing external Quantum repository; no Quantum source was changed.
- A live Event Day optimization with `message_id=DTC-LIVE-20261006-02` returned optimizer `Quantum`, bitstring `001111100000100000`, objective `-287.1`, and `applied_to_sumo=true`.
- The paired Digital Twin state endpoint read back the same message ID, result, constraints, Event Day name, live total vehicle count (13), configured density, and live intersection counts (J8=4, J9=3, J10=2; other observed intersections were zero at capture). This verifies that optimization received the captured current inputs rather than the former made-up integration defaults.
- The API's saved pair experiment does not retain solver runtime or per-command application counts, so those are not inferred here.
- A live state read initially encountered non-finite telemetry (`NaN`) rejected by JSON serialization. `GET /api/simulation/state` now normalizes non-finite telemetry with the existing JSON-safe conversion path; regression test and subsequent live state read returned successfully.
- **Result:** PASS for real Quantum result, live-input capture, TraCI application flag, and state readback; runtime/per-command counts are unavailable in the persisted pair experiment evidence.
