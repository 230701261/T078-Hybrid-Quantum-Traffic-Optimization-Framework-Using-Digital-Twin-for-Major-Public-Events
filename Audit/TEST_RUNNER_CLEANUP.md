# Test Runner Cleanup

- **Test ID:** RUNNER-CLEANUP-20261006
- **Date/time:** 2026-10-06, approx. 13:45 Asia/Kolkata
- **Configuration:** `python run_test_runner.py`; real FastAPI/Uvicorn process, two live SUMO/TraCI instances, REST and WebSocket checks.
- **Input:** Geometry, comparison, `/` HTML, five WebSocket telemetry frames, switch to Event Day, two Event Day telemetry frames; orderly shutdown in `finally`.
- **Expected:** Runner exits 0, ASGI shutdown closes SUMO/TraCI, no uncontrolled socket reset or orphan process.
- **Actual:** All checks passed; runner printed `Server shutdown completed through the ASGI lifespan.` and exited with code 0. It reported 60 geometry edges and live Normal Day/Event Day frames. A preceding in-sandbox attempt failed because Windows denied SUMO's local socket (`WinError 10013`); the same test outside the sandbox passed.
- **Evidence:** Escalated `python run_test_runner.py` command output and exit code; no runner/SUMO processes remained after graceful shutdown.
- **Result:** **PASS**.

## Change

`Audit/run_test_runner.py` now runs Uvicorn on a non-daemon thread, waits for readiness, uses bounded REST/WebSocket operations, asserts Event Day telemetry, sets `server.should_exit`, joins the server, and fails if orderly shutdown does not complete. Root `run_test_runner.py` delegates to this runner.
