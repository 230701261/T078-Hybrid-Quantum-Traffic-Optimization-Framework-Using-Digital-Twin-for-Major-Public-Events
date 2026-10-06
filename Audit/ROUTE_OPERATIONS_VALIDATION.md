# Route Operations Validation

- **Test ID:** DTC-ROUTE-20261006
- **Date/time:** 2026-10-06, 14:28–14:44 Asia/Kolkata
- **Feature:** Dynamic route metadata, rerouting, entry block/restrict and restore.
- **Input:** Live `GET /api/network/routes`; live `GET /api/network/edges`; block request for configured corridor `Anna Salai` while scenario flows are active.
- **Expected:** Route/edge metadata comes from loaded route files and live TraCI; unsafe scheduled-flow closures are rejected before mutation; operations that do mutate require readback and paired rollback.
- **Actual:** Metadata returned 15 route definitions and 60 live edges. The flow-conflicting block returned HTTP 422 with a `ROUTE_BLOCK_REJECTED` event; both SUMO sessions remained CONNECTED and Digital Twin RUNNING. Pair-level preflight and snapshots/rollback were added for edge permissions, speeds, costs and vehicle routes. No successful positive diversion was demonstrated in this live run.
- **TraCI command:** Readback uses `vehicle.getRoute`, `edge.getIDList`, `edge.getLaneNumber`, `lane.getAllowed`, `lane.getDisallowed`, `lane.getMaxSpeed`; route modifications use existing lane permission and reroute calls.
- **Readback:** Live route/edge counts; structured rejection event; `/api/system/status` returned both SUMO sessions CONNECTED after rejection.
- **Evidence:** `python -m pytest tests -q`: 37 passed; live REST metadata and rejection responses; `Audit/CORRIDOR_BLOCK_VALIDATION.md` records the same scheduled-flow constraint.
- **Result:** **PARTIAL**. Dynamic metadata and safe refusal are verified. Complete corridor closure, scheduled-flow diversion, and a successful positive route change are not proven; the UI must not label an unsafe request applied.

## Limitation

Operator route controls still accept the existing configured corridor topology, not arbitrary route IDs returned by route discovery. Full block is rejected where scheduled flows use the corridor. No hardcoded alternative path is claimed.

## Additional live reroute and rollback test — 2026-10-06

- **Input:** `POST /api/simulation/routes` with `source=Wallajah Road`, `alternative=Anna Salai`, `diversion_percent=100`, `blocked=false` against live Normal Day pair `pair_bf8ae7e1c25d`.
- **Expected:** Valid replacement routes are read back, or the operation is rejected and both simulation contexts are restored without losing SUMO health.
- **Actual:** SUMO could not read back the requested route in either context. API returned `success=false`, `applied=false`; it rejected the pair. The first attempt exposed stale full-route replay errors during rollback. Rollback now recalculates from each vehicle's current external edge to the saved destination and avoids rewriting vehicles on transient internal lanes. Repeating the request returned that both contexts were restored; `/api/system/status` showed classical and quantum CONNECTED and Digital Twin RUNNING.
- **TraCI operation/readback:** Route search uses live `simulation.findRoute` from the current edge to the captured destination; applies a connected route via `vehicle.setRoute`; reads back `vehicle.getRoute`. A route selection/readback failure is not reported as applied.
- **Evidence:** Live HTTP response for the repeated request; subsequent live system-status response; two new rollback unit tests in `tests/test_dynamic_operator_controls.py`.
- **Result:** **PASS** for safe rejection, rollback, and SUMO survival; **FAIL** for positive reroute acceptance. No successful active vehicle diversion is claimed.
