# Final Acceptance Report

- **Test ID:** FINAL-ACCEPTANCE-20261006
- **Date/time:** 2026-10-06, 13:45–17:05 Asia/Kolkata
- **Configuration:** Existing Chepauk project, original Quantum repository, live SUMO/TraCI pair, real Quantum API, local in-memory persistence fallback, browser/WebSocket.
- **Input:** Local complete pytest suite; live runner; real Quantum API tests; Event Day Quantum integration trigger and duplicate replay; live Anna Salai full-block request; live J4 phase-control request; desktop browser viewports.
- **Expected:** All accepted release criteria verified with no fake data or hidden failures.
- **Actual:** The latest complete test run passed 43 tests (11 deprecation warnings). The live REST/WebSocket runner exited 0 and shut down through ASGI lifespan. This pass also performed a fresh Event Day Quantum optimization (`DTC-LIVE-20261006-02`) against live inputs; it returned a real 18-bit bitstring, objective -287.1, `applied_to_sumo=true`, and the pair state recorded actual density, live intersection loads, constraints and event vehicle total. A NaN in live telemetry initially caused state serialization failure; normalization and regression/live readback now pass. The Light/Dark theme toggles and persists through refresh, retains both canvases, and was checked at 1440/1600/1920 widths. A real positive route request failed; the corrected pair rollback rejected it safely and health readback confirmed SUMO remained connected. Prior real Quantum/fallback and duplicate evidence remains recorded below. Full Anna Salai block remains safely rejected because scheduled flows use affected edges. J4 independent red timing remains unsupported. Supabase remains unconfigured in the broader project audit; it was out of scope for this feature task.
- **Evidence:** See the reports referenced below, direct HTTP/API outputs, browser DOM/screenshot/console inspection, and test outputs.
- **Result:** **PARTIAL**.

## Overall status

**PARTIALLY VERIFIED**. End-to-end Quantum → Digital Twin → TraCI → SUMO → WebSocket → Three.js was re-run successfully. The remaining genuine limitations are a full corridor block, independent J4 red timing, and absent Supabase credentials. Cloud persistence is therefore untested.

## Issue disposition

| Issue | Result | Evidence |
|---|---|---|
| AUD-04 full corridor block | BLOCKED | Safe rejection before mutation; affected scheduled route edges listed; SUMO remained connected. No successful scheduled-flow diversion implemented or proven. |
| AUD-09 independent red signal timing | PARTIAL | J4 returned `success:false`, `status:partial`, `unsupported_timings:[red]`; actual phase durations read back. |
| AUD-10 Supabase | BLOCKED | Credentials absent; only local in-memory fallback. No cloud transaction claim. |
| AUD-14 desktop viewports | PASS | 1440×900, 1600×900, 1920×1080 DOM/canvas geometry and 1440 screenshot; console clean. |
| Test runner cleanup | PASS | `python run_test_runner.py` returned exit code 0 and ASGI shutdown completed. |

## Live Quantum evidence

- Message ID: `FINAL-HARDENING-20261006-01`
- Optimizer: `Quantum`
- Bitstring: `101011110000000001` (18 binary bits)
- Objective: `-391.06`
- Runtime: `17.46 s`
- TraCI commands: `24/24`, no command failures
- Result: `completed`, `applied_to_sumo=true`
- Duplicate: same request returned `status=skipped`, `error=already_processed`, `applied_to_sumo=true`; no second command application.
- Browser showed `QUANTUM RESULT · APPLIED`, the same bitstring/objective/runtime, Event Day, advancing time, live counts, and two rendered maps. Console warning/error query was empty.

## Classical fallback evidence

- Quantum API was stopped; the Digital Twin endpoint invoked the existing classical optimizer.
- Message ID: `FINAL-HARDENING-20261006-FALLBACK`
- Optimizer: `Classical (Fallback)`
- Bitstring: `110011011000000000` (18 bits)
- Objective: `-431.2`; runtime: `5.21 s`
- Result: completed and applied; 22/22 TraCI commands succeeded with zero command failures.
- Browser WebSocket showed `CLASSICAL FALLBACK · APPLIED` while Event Day SUMO continued advancing.

## Tests

| Test | Result | Evidence |
|---|---|---|
| Complete pytest suite | PASS | `python -m pytest tests -q`: 43 passed, 11 deprecation warnings, 27.12 s |
| Real Quantum API | PASS | `python -m pytest -s tests/test_real_quantum_api.py -q`: 2 passed; QAOA bitstring above; runtime 15.95 s in that standalone test run |
| Live Quantum → SUMO | PASS | Event Day HTTP trigger, 24/24 TraCI commands; actual system status reported both SUMO instances connected |
| Duplicate request | PASS | Same message ID skipped |
| Classical fallback | PASS | Quantum service stopped; classical result applied 22/22 commands and browser showed fallback label |
| Test runner | PASS | Exit code 0; live REST/WebSocket, scenario switch and graceful ASGI cleanup; repeated after latest changes |
| WebSocket/Three.js | PASS | Browser connected; actual Event Day metrics and real Quantum result rendered; two canvases |
| Desktop viewports | PASS | All three sizes as recorded in `DESKTOP_UI_VALIDATION.md` |
| Theme desktop viewports | PASS | Both themes: equal side-by-side maps at 1440/1600/1920, two canvases, no horizontal overflow |
| Positive live route diversion | FAIL | Wallajah Road via Anna Salai could not be read back; pair rejected; repaired rollback response and subsequent status showed both SUMO sessions connected |
| Theme refresh persistence | PASS | Light and Dark each remained selected after a page reload; browser error/warning logs empty |
| Corridor closure | BLOCKED | Safe rejection; full block not supported by current scheduled route setup |
| J4 red timing | PARTIAL | Independent red unsupported; no false success |
| Supabase cloud persistence | BLOCKED | Missing credentials |

## Latest dynamic-input and serialization evidence

- Real Quantum Event Day request `DTC-LIVE-20261006-02`: optimizer `Quantum`; bitstring `001111100000100000`; objective `-287.1`; applied to live paired SUMO/TraCI.
- Pair experiment input readback: event `event_day`, venue MA Chidambaram Stadium, live vehicle count 13; configured vehicle demand; intersection loads from current TraCI vehicle positions; actual active constraint values.
- Runtime and per-command count are not retained in this pair experiment snapshot; no number is inferred here.
- After the real run exposed NaN telemetry serialization, `/api/simulation/state` was fixed to serialize non-finite values safely. New regression test passes and post-optimization state retrieval returned HTTP 200.
- Latest static validation: Python compileall and JS syntax checks all passed. Temporary local listeners on 8001/8010 were stopped after the run.
- Live route operation `Wallajah Road → Anna Salai`, 100% diversion: failed in both contexts; operation returned `applied=false`. The first run exposed unsafe stale-route replay during rollback. The rollback now computes from live vehicle edge to the captured destination; unit tests and a repeated live rejection confirmed both contexts were restored and remained healthy.
- Theme: explicit Light/Dark preference persisted across reload; browser readback confirmed computed CSS backgrounds, two rendered canvases, and no error or warning logs. All three recorded desktop widths were measured with maps side by side in both themes.

## Files changed in this hardening pass

- `.gitignore`
- `FINAL_REMAINING_FIX_PLAN.md`
- `python/server.py`
- `ui/js/app.js`
- `ui/index.html`
- `run_test_runner.py`
- `Audit/run_test_runner.py`
- `ui/js/renderer3d.js`
- `python/traci_controller.py`
- `tests/test_dynamic_operator_controls.py`
- `tests/test_theme_contract.py`
- `Audit/THEME_VALIDATION.md`
- `Audit/FINAL_DYNAMIC_CONTROL_HARDCODE_AUDIT.md`
- six validation reports listed below
- existing audit reports received a dated evidence addendum.

## Reports generated or updated

`CORRIDOR_BLOCK_VALIDATION.md`, `SIGNAL_CONTROL_VALIDATION.md`, `SUPABASE_VALIDATION.md`, `DESKTOP_UI_VALIDATION.md`, `TEST_RUNNER_CLEANUP.md`, `FINAL_ACCEPTANCE_REPORT.md`, and the existing audit reports in `Audit/`.
