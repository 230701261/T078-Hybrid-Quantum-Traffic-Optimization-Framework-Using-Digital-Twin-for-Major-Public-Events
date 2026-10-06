# Fix Implementation and Verification

## Changes made

- Replaced seeded scenario statistics with live SUMO measurements: active speed/wait/queue/congestion, departures, arrivals, measured trip durations, completed-travel-time totals, waiting, throughput and configuration/network identity.
- Separated simulation stepping from 0.5 s telemetry extraction; reports requested and measured simulation rates.
- Added paired comparison checks for simulation IDs, scenario, input/config hash, network hash and clock tolerance. The API separates measured deltas from plan/model estimates.
- Route blocking now checks scheduled SUMO flow paths before mutation. Conflict-free lanes can use permissions and restore readback; current Chepauk flow paths traverse requested corridors, so unsafe closure is rejected before commands. Reroute attempts return bounded diagnostics and failure reasons.
- Added accurate STOPPED/STARTING/RUNNING/PAUSED/ERROR lifecycle paths and backend-driven optimization stages.
- Made local run creation atomic by message ID; live duplicate calls are skipped before a second application.
- Corrected traffic-signal TraCI readback to check the active phase’s next-switch time, not configured phase duration. Serialized TraCI command/readback using a shared reentrant session lock.
- Operator input readbacks are retained for weather, VIP, construction and signal phases. Unsupported phase classes now report as unsupported; they do not count as verified.
- Supabase health distinguishes NOT CONFIGURED, CONNECTED and UNAVAILABLE. No credentials were added.
- Density fields identify hourly flows and snapshots distinguish departures, current active vehicles and completions.
- UI initial statuses no longer claim live health before backend/socket responses; metrics distinguish model estimates from measured deltas.
- Added the objective already computed by QAOA to the original Quantum API response; no QUBO/QAOA mathematics changed.

## Live verification summary

- Real Quantum API health: HTTP 200, `healthy`, 18 decision variables.
- UI-triggered real QAOA before the response-field fix: run `8f52c1d7-88ab-4002-afce-105d890a99de`, bitstring `010111000100000000`, runtime 19.41 s, 21/21 commands applied.
- After the response-field fix, direct Event Day API result returned objective `-394.64`; live UI run `a332cf4e-c22d-4e2d-9872-16aca174ecbc` displayed objective `-367.74`, bitstring `110000011000100000`, runtime 10.94 s and COMPLETED · APPLIED.
- Real API + live SUMO E2E test passed; duplicate apply skipped.
- Quantum API unavailable: `FALLBACK-AUDIT-001` used `Classical (Fallback)`, returned valid 18-bit result, applied 21/21 commands; repeat returned `skipped / already_processed`.
- Speed, density, pause/resume/start/reset, route restriction/reopen, weather, VIP, construction and signal readback evidence is in the dedicated reports.

## Limits

- No Supabase URL/key is configured; persistence was local-memory only.
- Chepauk signal phase programs do not expose all three requested independent red/green/yellow phase classes for the tested junction. Red timing is therefore reported unsupported, and the operator control cannot be called fully applied.
- Scheduled route definitions traverse all tested corridors; closing those lanes causes SUMO to reject future vehicles. Safe live route blocking remains blocked pending route-file diversion/restart support.
- No trips completed during the short controlled windows; completed-trip time is correctly N/A.
- Desktop viewports 1440×900, 1600×900 and 1920×1080 were not available for runtime testing. Browser was inspected at 1280×720.
- `run_test_runner.py` served actual UI and WebSocket telemetry, but emitted a SUMO socket-reset message during scenario switching and did not exit cleanly in the first conflicting-port attempt. See `SYSTEM_TEST_MATRIX.md`.

Verdict: **PARTIALLY VERIFIED**.

## Final hardening pass — 2026-10-06

- Replaced abrupt daemon-process termination in `Audit/run_test_runner.py` with an orderly Uvicorn lifecycle; added root `run_test_runner.py` entry point. Live run exited 0 and invoked the ASGI shutdown hook.
- Added root `.gitignore` protections for `.env` and environment override files while allowing `.env.example`.
- Added structured signal `limitations` in `/api/simulation/apply`; the UI now states which requested phase class the active TLS cannot represent instead of using a generic rejection toast.
- Live Event Day QAOA result traversed the Job Manager and applied 24/24 commands to SUMO; same message ID replay skipped.
- Live block remained safely rejected; cloud persistence remains unconfigured. No topology/QUBO/UI architecture changes were made.
- With Quantum API stopped, the real classical fallback applied 22/22 commands and the browser showed `CLASSICAL FALLBACK · APPLIED`. A browser cache test exposed stale app.js; its query token was bumped, and the specific J4 limitation message was verified live.
