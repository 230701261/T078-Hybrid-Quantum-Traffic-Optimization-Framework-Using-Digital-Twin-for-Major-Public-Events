# Dynamic Control Implementation Notes

**Purpose:** Record implementation decisions and known capability boundaries before the separately requested verification phase. This is not an acceptance report; no final PASS/PARTIAL/FAIL assessment is made here.

## Implementation decisions

- Quantum results and Classical fallback results use the same `ConstraintEngine` batch validation through the integration adapter. Live context includes SUMO edge/TLS/vehicle IDs, remaining active vehicle routes, loaded route-backed flow edges, and lane-permission closures. Validation completes before the adapter's first TraCI write.
- Active vehicle rerouting uses `NetworkRoutingService`; candidate routes are built from the live network, validated against current position and destination, and checked by SUMO readback.
- Paired edge closure/restoration uses actual lane permissions. Both contexts are planned before mutation. Loaded future-flow conflicts are rejected. Active vehicles whose remaining route uses a target edge are rerouted from their current position if a valid alternative exists; vehicles already on a target edge or without an alternative cause pre-mutation rejection. Failed paired application triggers permission and route rollback.
- The construction profile remains speed/cost based. `mode=closure` is a separate runtime permission operation governed by the same flow, route, alternative-route, and readback checks.
- TLS phase updates remain bounded by the active program's actual `minDur`/`maxDur`. Fixed phases are rejected; independent red/green/yellow timing is not claimed.
- VIP corridor preference remains a configured routing-cost preference. No VIP entity is synthesized; assignment requests return explicit unsupported status because the current demand model has no VIP entity.

## Deferred verification

The complete pytest suite, `run_test_runner.py`, final browser checks, live Quantum/Classical optimization under active constraints, live closure/restoration, and final acceptance reporting are intentionally deferred to the next verification phase.

## Known capability boundaries

- Loaded `flow`/`personFlow` route references do not have a safe current-runtime replacement path. Edges used by those flows remain ineligible for closure.
- A closure can proceed only if loaded future flows do not use the edge, affected active vehicles can be safely rerouted or are absent, and permission mutation/readback succeeds in both SUMO contexts.
- VIP assignment requires a real VIP entity in the loaded SUMO demand model.
- Independent color timing requires a TLS program whose live phase bounds permit the requested duration.
- Supabase credentials and persistence are not part of this implementation phase and are not claimed configured.
