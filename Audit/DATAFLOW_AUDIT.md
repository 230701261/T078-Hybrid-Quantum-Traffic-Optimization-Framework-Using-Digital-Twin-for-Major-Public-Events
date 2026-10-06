# Data Flow Audit — Post-Fix

## Live telemetry

| UI field | WebSocket snapshot | Python source | SUMO/TraCI source |
|---|---|---|---|
| Simulation time | `time` | controller snapshot / metrics | `traci.simulation.getTime()` |
| Vehicles and modes | `vehicles`, `kpis` | `_extract_snapshot`, `MetricsCollector` | `vehicle.getIDList`, vehicle type/position/speed/route/lane APIs |
| Pedestrians | `pedestrians`, count KPI | `_extract_snapshot` | TraCI vehicle IDs/types/persons from SUMO context |
| Signal count/state | `traffic_lights` | controller snapshot | traffic-light IDs, phase/state APIs |
| Average speed | `kpis.avg_speed_kmh` | `MetricsCollector.update` | actual active vehicle speeds |
| Queue | `kpis.total_queue_length_m` | metrics collector | lane halting counts/vehicle lengths from SUMO |
| Congestion | `edges_congestion` | controller snapshot | lane/edge occupancy, queue and speed |
| Demand/departures/completions | snapshot demand/count fields | `scenario_inputs`, controller counters | generated SUMO route flows, departed/arrived TraCI events |
| Active map geometry | network geometry endpoint | network exporter | loaded SUMO network file |

UI consumes the Digital Twin server WebSocket `/ws/simulation`; it does not call the Quantum API directly for telemetry or optimization.

## Optimization control flow

```text
UI button
  -> POST /api/integration/trigger_optimization (message_id, scenario/pair identity)
  -> request validation + idempotency lookup
  -> OptimizationJobManager lifecycle events
  -> QuantumOptimizationClient HTTP POST :8001/api/quantum/optimize
       or actual Classical (Fallback) when endpoint unavailable
  -> response/18-bit/ID validation
  -> logical corridor/junction mapping
  -> atomic TraCI action + readback under shared session lock
  -> repository records run state (cloud only if configured; otherwise local memory)
  -> optimization status and simulation snapshots over WebSocket
  -> app.js state -> renderer3d.js canvases/HUD
```

## Pair comparison

Classical and Quantum contexts start from shared scenario inputs and seed-derived route configuration. Comparison returns measured speed, queue, congestion, completed trip and waiting metrics only when pair identities, scenario, configuration/network hashes, and clocks meet synchronization checks. Model-derived optimizer benefits are returned and displayed separately with explicit `Model estimate` labels.

## Persistence flow

`OptimizationJobManager -> SupabaseRepository -> Supabase` only when credentials are configured and the health probe succeeds. This environment had no Supabase credentials: live runs used local in-memory fallback. Cloud persistence remains unverified.

## Gaps

- Completed-trip time is N/A when no arrivals have occurred in the measured window.
- Full corridor lane closure is rejected when scheduled flow routes use those edges; direct closure was observed to terminate SUMO. Safe blocking requires rerouting the configured flow paths before closure.
- Independent red duration cannot be applied when the loaded TLS program has no red-only phase class; the control now reports unsupported instead of a false success.
- At the time of the earlier report, required desktop viewport overrides had not been verified; the final pass now verifies 1440×900, 1600×900, and 1920×1080 in `DESKTOP_UI_VALIDATION.md`.

## Final hardening evidence — 2026-10-06

- A live Event Day trigger used the actual Quantum API and applied 24/24 commands through the active Quantum TraCI session; the duplicate message was skipped.
- Browser received live telemetry plus the actual Quantum bitstring/objective/status over the existing Digital Twin WebSocket.
- Full closure remains blocked before mutation for scheduled-flow corridors; J4 red timing remains unsupported; Supabase remains local-only because credentials are missing.
- Desktop viewports were verified at 1440×900, 1600×900 and 1920×1080. Runner shutdown now completes cleanly.
