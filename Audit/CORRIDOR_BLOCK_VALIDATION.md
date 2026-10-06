# Corridor Block Validation

- **Test ID:** AUD-04-LIVE-20261006
- **Date/time:** 2026-10-06, approx. 13:50 Asia/Kolkata
- **Configuration:** Live Digital Twin API, paired Normal Day SUMO/TraCI, real Event Day route definitions also inspected; Quantum API state irrelevant to the block preflight.
- **Input:** `POST /api/simulation/routes` with `{"source":"Anna Salai","blocked":true,"diversion_percent":0}`.
- **Expected:** A full closure either diverts affected demand before mutation and reads back a real closure, or rejects safely with clear reason.
- **Actual:** HTTP 422 rejected the block before lane mutation. Error named scheduled-flow conflicts: `E_WEST_1`, `E_WEST_1_rev`, `E_WEST_IN_N`, `E_WEST_IN_S`, `E_WEST_OUT_N`, `E_WEST_OUT_S`. A subsequent `/api/system/status` reported both SUMO instances `CONNECTED` and Digital Twin `RUNNING`.
- **Evidence:** Live PowerShell `Invoke-RestMethod` request/response and subsequent status response; `python/tests/test_issue_resolution.py` also passed 10 tests.
- **Result:** **BLOCKED** for full closure; **PASS** for safe rejection and SUMO survival.

## Limit

The implementation protects currently scheduled flow routes but does not reroute those flows to actual alternative paths. The current route controller can alter routing costs and reroute eligible active vehicles, but it does not rewrite scheduled route definitions. No claim of a successful full corridor block is made. Implementing scheduled-flow diversion requires a route-level preflight against SUMO permissions and endpoints, paired atomic update/rollback, and live future-departure verification.
