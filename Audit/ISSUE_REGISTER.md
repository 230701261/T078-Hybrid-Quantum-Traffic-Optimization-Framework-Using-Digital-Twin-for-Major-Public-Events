# Issue Register — Post-Fix Evidence

Disposition is based on evidence collected on 2026-10-06. `FIXED` means the identified implementation defect has a passing focused or live verification; it does not imply every broader acceptance criterion is met.

| ID | Severity | Issue | Disposition | Evidence / remaining limit |
|---|---|---|---|---|
| AUD-01 | P1 | Measured comparison vs model estimates | FIXED | `/api/comparison` uses paired live snapshots and labels plan benefits as model estimates. Browser showed measured speed/queue/congestion deltas. Average completed trip remained N/A because zero trips completed in observed interval; see `QUANTUM_MAP_VALIDATION.md`. |
| AUD-02 | P1 | Actual 1×–4× progression | FIXED | Live SUMO measured over 2 s each: SUMO deltas 2.0, 3.5, 5.5, 8.0 simulation seconds, monotonic; return to 1× gave 2.0. Pause held at 21.5 s; resume advanced to 22.5 s. |
| AUD-03 | P1 | Matched Classical/Quantum causal experiment | FIXED | Same pair and config/network identity; UI-triggered real QAOA run captured pre/post state and actual application result. Map panels are separate live SUMO contexts. No claim of guaranteed improvement; observed comparison is time-varying and not an isolated causal benchmark. |
| AUD-04 | P1 | Route block semantics | BLOCKED | Directly closing mapped edges used by scheduled SUMO flows terminated SUMO (`vehicle ... has no valid route`). Safe preflight now rejects before any TraCI command and leaves SUMO RUNNING. All tested corridors intersect scheduled flow routes; a complete safe block requires route-file diversion/restart support. |
| AUD-05 | P2 | Rerouting exceptions hidden | FIXED | Bounded per-vehicle diagnostics include attempted/success/fail/reason; live no-alternative test reported 3 failed attempts instead of swallowing them. Positive alternate-route success was not observed. |
| AUD-06 | P2 | Start/resume lifecycle | FIXED | Live API sequence returned PAUSED, RUNNING, STOPPED, STARTED/RUNNING, then reset RUNNING. UI reflects RUNNING and disables Start while active. |
| AUD-07 | P2 | Synchronization badge validates only IDs | FIXED | Pair state checks scenario, config hash, network hash, pair identity, and simulation-time tolerance. Unit mismatch test reports DESYNCHRONIZED; live UI observed SYNCHRONIZED and SYNCING as clocks drifted. |
| AUD-08 | P2 | Density to actual generated traffic | FIXED | Two matched Normal Day runs at 4× observed 60 s SUMO time: 1,000 cars/h generated 29 departures; 2,000 cars/h generated 47; active counts matched at capture. Demand is labeled veh/h. |
| AUD-09 | P2 | Operator readback | BLOCKED | Weather, VIP, and construction readbacks verified in live TraCI. Route block/reopen verified. Signal readback exposed unsupported independent red timing on the current phase program; operator cannot claim all three red/green/yellow values were applied. |
| AUD-10 | P2 | Supabase cloud persistence | BLOCKED | No configured credentials; application reports NOT CONFIGURED and local fallback. No cloud transaction was attempted or claimed. |
| AUD-11 | P2 | Request idempotency | FIXED | Live HTTP request `FALLBACK-AUDIT-001` executed once (21/21 commands applied); same ID returned `skipped / already_processed / applied=true`. Unit duplicate test also passes. |
| AUD-12 | P3 | Digital Twin status hardcoded RUNNING | FIXED | `/api/system/status` now derives status from pair/controller lifecycle and health; live state and control transitions matched actual controller state. |
| AUD-13 | P3 | False startup status defaults | FIXED | Initial UI uses CONNECTING/CHECKING/IDLE. Browser showed Connected/Running only after real API, SUMO, and WebSocket responses. Supabase showed NOT CONFIGURED. |
| AUD-14 | P3 | Desktop viewport acceptance | FIXED | Rechecked at 1440×900, 1600×900, and 1920×1080. Both canvases stayed side-by-side/equal-width with no horizontal overflow; 1440 screenshot and clean console captured. See `DESKTOP_UI_VALIDATION.md`. |
| AUD-15 | P3 | Optimization lifecycle | FIXED | Backend emits lifecycle events and WebSocket reports stages; focused lifecycle regression test checks QUEUED through COMPLETED. Live UI displayed RUNNING during QAOA, then `QUANTUM RESULT · APPLIED`, actual bitstring/runtime/run ID. |

## Counts

- FIXED: 12
- BLOCKED: 3
- INTENTIONALLY STATIC: 0 (static configuration is documented in `HARDCODE_AUDIT.md`)
- NOT APPLICABLE: 0
- Remaining: 3 blocked/partial items above (AUD-04, AUD-09, AUD-10).

## Final hardening pass addendum — 2026-10-06

- AUD-04 remains **BLOCKED** for a complete closure. A live Anna Salai block request returned HTTP 422 before mutation and listed six scheduled-flow-conflicting edges; subsequent live status showed both SUMO sessions connected and Digital Twin running. See `CORRIDOR_BLOCK_VALIDATION.md`.
- AUD-09 remains **PARTIAL**. Live J4 returned `success:false`, `status:partial`, and `unsupported_timings:["red"]`; current UI error text now surfaces that limitation. See `SIGNAL_CONTROL_VALIDATION.md`.
- AUD-10 remains **BLOCKED**. Credentials absent, `.env` absent; `.gitignore` now excludes `.env`/`.env.*` and keeps `.env.example` tracked. No cloud transaction was performed.
- AUD-14 now **PASS** at 1440×900, 1600×900 and 1920×1080; map panels remained equal-width and side-by-side with no horizontal overflow. See `DESKTOP_UI_VALIDATION.md`.
- Runner cleanup now **PASS**: `python run_test_runner.py` exited 0 after an orderly ASGI shutdown. See `TEST_RUNNER_CLEANUP.md`.
- Final disposition remains **PARTIALLY VERIFIED** because no complete corridor diversion/closure or cloud persistence was demonstrated.
