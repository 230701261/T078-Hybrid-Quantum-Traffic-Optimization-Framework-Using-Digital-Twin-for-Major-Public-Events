# System Test Matrix — Fix Pass

Captured 2026-10-06. PASS means observed in this session; PARTIAL/BLOCKED are not promoted to PASS.

| Test | Mode | Result | Evidence |
|---|---|---|---|
| Python compile | Local | PASS | `python -m compileall -q python` |
| JavaScript syntax | Local | PASS | `node --check` for app.js, renderer3d.js, controls.js |
| Scenario inputs | Local | PASS | `python tests/test_scenario_inputs.py`: 3 tests |
| Quantum/Digital Twin integration | Local/integration | PASS | `python tests/test_quantum_digital_twin_integration.py`: 8 tests |
| Negative/idempotency tests | Local | PASS | `python tests/test_negative_and_idempotency.py`: 6 tests |
| Issue-resolution regressions | Local | PASS | `python tests/test_issue_resolution.py`: 10 focused regressions including flow-conflicting route-block rejection |
| Live SUMO + Quantum E2E | Real API + SUMO/TraCI | PASS | `python tests/test_e2e_sumo_quantum_live.py`: 1 test; non-null objective asserted; 22/22 commands; duplicate reapply skipped |
| Live Quantum health | Real Quantum API | PASS | GET :8001/health -> healthy, 18 variables |
| UI-triggered QAOA | Real Quantum + paired live SUMO | PASS | Browser UI shows objective -367.74, bitstring/runtime/status; server log 21/21 application |
| Classical fallback | Quantum API stopped | PASS | HTTP trigger uses `Classical (Fallback)`, 21/21 applied |
| Live request idempotency | HTTP endpoint | PASS | Same `FALLBACK-AUDIT-001` repeated -> skipped/already_processed |
| Speed 1×/2×/3×/4× | Live SUMO | PASS (monotonic) | Deltas 2.0/3.5/5.5/8.0 s per 2 s wall; pause/resume verified |
| Density configuration | Two live SUMO instances | PASS | 1000 vs 2000 veh/h -> 29 vs 47 departures over 60 sim seconds |
| Weather/VIP/construction readback | Live TraCI | PASS | Heavy Rain lane-speed factor, 6 VIP edge costs, construction lane/cost values verified |
| Route block/reopen | Live TraCI | BLOCKED safely | Full closure on scheduled-flow edges previously terminated SUMO; preflight now rejects before mutation and leaves SUMO running. Unit closure/reopen covers conflict-free routes. |
| Signal timing | Live TraCI | PARTIAL | Green/yellow read back; requested independent red timing not representable at tested J4 program |
| Controls lifecycle | Live REST | PASS | Pause, resume, stop, start-from-stopped, reset returned actual states |
| WebSocket + Three.js telemetry | Browser + live SUMO | PASS | Browser rendered both map canvases and observed changing time, vehicle/pedestrian counts, speed, queue, congestion |
| Responsive viewport acceptance | Browser | PASS | Final pass inspected 1440×900, 1600×900, 1920×1080; maps remain side-by-side, no horizontal overflow, console clean |
| `run_test_runner.py` | Live local server/SUMO | PASS | Corrected root runner completed live REST/WS and Event Day switch; exit code 0 and ASGI shutdown cleanup |
| Supabase persistence | Cloud | BLOCKED | No credentials configured; local in-memory fallback only |

## Required commands and observed outcome

```text
python -m compileall -q python                           PASS
node --check ui/js/app.js                               PASS
node --check ui/js/renderer3d.js                        PASS
node --check ui/js/controls.js                          PASS
python tests/test_scenario_inputs.py                    PASS (3)
python tests/test_quantum_digital_twin_integration.py   PASS (8)
python tests/test_negative_and_idempotency.py           PASS (6)
python tests/test_issue_resolution.py                   PASS (9)
python tests/test_e2e_sumo_quantum_live.py              PASS (1 live E2E)
python run_test_runner.py                               PASS (live REST/WS; clean ASGI shutdown, exit code 0)
```

Pydantic v2 `.dict()` deprecation warnings remain in `quantum_client.py`. They do not cause test failures.

## Final hardening pass — 2026-10-06

| Test | Mode | Result | Evidence |
|---|---|---|---|
| Complete pytest suite | Local + live SUMO | PASS | `python -m pytest tests -q`: 32 passed, 6 deprecation warnings, 28.89 s |
| Standalone Quantum API | Real Quantum API | PASS | `python -m pytest -s tests/test_real_quantum_api.py -q`: 2 passed; returned `001100110011010000`, runtime 15.95 s |
| Digital Twin runner | Live SUMO/TraCI + REST/WS | PASS | Root `python run_test_runner.py`, exit 0, real Normal/Event Day telemetry, orderly ASGI shutdown |
| Quantum → SUMO | Live Event Day | PASS | Message `FINAL-HARDENING-20261006-01`; Quantum, 18 bits, objective -391.06, 17.46 s, 24/24 applied |

## Revalidation addendum (2026-10-06)

| Test | Mode | Result | Evidence |
|---|---|---|---|
| Complete pytest suite | Local + live SUMO/API tests | PASS | 39 passed, 11 deprecation warnings, 32.44 s; first run's denied socket access cleared by stopping temporary services and rerunning with socket permission |
| Root live runner | Local live server/SUMO | PASS | Exit 0; 60-edge geometry, live telemetry, Event Day switch, ASGI cleanup |
| Fresh Quantum input capture | Live Quantum + paired SUMO | PASS | `DTC-LIVE-20261006-02`; result `001111100000100000`, objective -287.1, applied true; actual current density/intersection/constraint inputs read from experiment state |
| State telemetry JSON safety | Regression + live readback | PASS | NaN normalized; state endpoint returned JSON after optimization |
| Supabase | Cloud | BLOCKED | Credentials unavailable; in-memory fallback only |
| Full corridor close / independent TLS red timing | Live SUMO | BLOCKED / UNSUPPORTED | Safely rejected for scheduled-flow conflict; loaded TLS phases have fixed bounds |
| Duplicate message | Live API | PASS | Same ID returned skipped/already_processed, no second apply |
| Browser and viewports | Live browser | PASS | WS connected; telemetry and result visible; console clean; 3 requested desktop sizes |
| Corridor full block | Live TraCI | BLOCKED | Anna Salai rejected pre-mutation due scheduled-flow edges; SUMO remained connected |
| J4 red timing | Live TraCI | PARTIAL | API success false; red unsupported; green/yellow read back |
| Supabase persistence | Cloud | BLOCKED | Credentials missing; fallback mode only |
| Offline classical fallback | Live Event Day SUMO | PASS | Quantum API stopped; `Classical (Fallback)` result `110011011000000000`, 22/22 commands applied; UI showed fallback label |
