# Hardcode and Dynamic-Data Audit — Post-Fix

## Intentionally static project configuration

| Configuration | Disposition | Reason |
|---|---|---|
| Chepauk location, stadium, MRTS, Marina | INTENTIONALLY STATIC | Fixed project identity/infrastructure |
| SUMO network and normal/event routes | INTENTIONALLY STATIC | Authoritative simulation topology/scenario |
| Logical corridor/junction mapping | INTENTIONALLY STATIC | Integration mapping for fixed SUMO IDs |
| 18-bit decision schema and 4/10/4 breakdown | INTENTIONALLY STATIC | Quantum model contract |
| Scenario input templates | INTENTIONALLY STATIC | Baseline route/demand definitions, scaled through validated controls |

## Dynamic values and sources

| Dynamic value | Source | Status |
|---|---|---|
| Status labels | Actual controller/Quantum health and WebSocket connection | No hardcoded initial LIVE/RUNNING/ONLINE claims remain in app shell |
| Vehicles, pedestrians, speed, queue, congestion, signals, sim time | TraCI snapshots via Digital Twin WebSocket | Live browser test showed changing values |
| Density and departures | Scenario flow rates and TraCI departure/arrival events | Live matched 1000/2000 veh/h experiment: 29/47 departures |
| Trip travel time | Actual SUMO departure-to-arrival times | N/A until vehicles complete trips; no estimate substituted |
| Optimizer, bitstring and objective | Actual Quantum API/QAOA or named Classical fallback | Live QAOA objective and 18-bit result displayed; fallback accurately labeled |
| Optimization benefits | Quantum traffic decision model | Labeled Model Estimate; not presented as measured savings |
| Logs/lifecycle | Server control actions and Job Manager stage callbacks | Backend-originated; no frontend timer fabricated stages |
| Supabase state | Credential/configuration-aware repository health | NOT CONFIGURED here; no fake cloud success |

## Search disposition

Production-path model estimates remain explicit as model estimates. Static network/route config and tests are not fake telemetry. `Math.random()` appears only when selecting decorative building materials in `renderer3d.js`; it does not generate vehicles, telemetry or optimization data. Test fixtures remain test-only.

## Remaining concern

The tested J4 SUMO signal program lacks an independently represented red-only phase. A request for red/green/yellow values now reports the missing class and cannot be reported as fully applied.

Final runtime check (2026-10-06): the live endpoint returned `success=false`, `status=partial`, and `unsupported_timings:["red"]` for J4. The browser displayed the result of live telemetry and optimization rather than seeded KPI values. Supabase reported NOT CONFIGURED; no cloud status was fabricated.
