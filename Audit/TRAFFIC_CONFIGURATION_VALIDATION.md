# Traffic Configuration Validation

- **Test ID:** DTC-TRAFFIC-20261006
- **Date/time:** 2026-10-06, 14:35–14:47 Asia/Kolkata
- **Feature:** Scenario demand, vehicle mix, speed and traffic configuration endpoint.
- **Input:** `GET /api/traffic/config` for `normal_day`; `POST /api/traffic/configure` with cars set to 1000 veh/h and other mode values preserved; then restore the configured normal-day demand.
- **Expected:** Existing scenario flows are scaled, active pair restarts with requested demand, and backend state/readback reports applied values.
- **Actual:** Capability data reported cars, buses, two-wheelers, pedestrians and train flows supported from the active scenario route definitions. The live pair accepted 1000 cars/h and `/api/operator/state` read back 1000; the pair remained RUNNING. Restore read back 2575 cars/h.
- **TraCI command:** Generated route-variant XML was loaded into both SUMO sessions by existing `TraCIController.start`; pair startup/readback was performed through the existing SUMO/TraCI lifecycle.
- **Readback:** `configure_success=true`, requested/active cars `1000`, `pair_id=pair_ae7113dc7249`, status `RUNNING`; restore succeeded at the original demand.
- **Evidence:** Live REST responses; `tests/test_scenario_inputs.py`; `tests/test_dynamic_operator_controls.py`; prior controlled density audit (`Audit/DENSITY_CONTROL_TEST.md`) measured 1000 vs 2000 veh/h departures.
- **Result:** **PASS** for scenario flow scaling and active-density readback. Speed remains verified by the existing live speed audit; unavailable modes are rejected when nonzero demand is requested.

## Limitation

Vehicle-type family names are mapped by the existing scenario model to configured SUMO vTypes; capability support is discovered per scenario from actual flow/personFlow definitions. There is no independent railway network simulation beyond configured SUMO train flows.
