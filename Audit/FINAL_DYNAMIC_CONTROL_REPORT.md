# Dynamic Traffic Control — Implementation Notes

This file records implementation scope before the separately requested final verification phase. It contains no final PASS/PARTIAL/FAIL verdict.

## Shared validation boundary

Both the Quantum result path and Classical fallback path use the same integration mapper and `TraCIAdapter`. The adapter obtains live SUMO IDs, remaining active routes, loaded flow route edges, and closed/restricted edge state before calling `ConstraintEngine.validate_batch`. The entire batch is rejected before its first write if validation returns errors. Runtime readback failure triggers best-effort rollback of prior writes in that batch.

## Operator controls

- Active vehicle routing uses live route discovery and retains current-edge, destination, accessibility, and readback checks.
- Paired edge closure/restoration uses lane permissions and saved original permissions. Both contexts are preflighted. Loaded future flows conflict; affected active vehicles are rerouted around the closure if a valid current-position route exists. A vehicle already on the target edge or without an alternative rejects closure.
- Construction keeps the configured speed/cost profile and provides a separate guarded closure mode.
- VIP corridor preference remains configured; real entity assignment returns unsupported while no VIP entity is modeled.
- TLS timing remains bounded by the active program; fixed phase durations are rejected.
- Weather, construction, VIP preference, and optimization parameters continue to load from `python/operator_profiles.json`.

## API contracts

- `GET /api/operator/capabilities` reports available, conditional, and unavailable modes.
- `POST /api/operator/edge-closure` accepts `{ "edges": [...], "closed": true|false }` and returns structured readback or rejection.
- `POST /api/operator/construction` accepts `mode=profile` or `mode=closure`.
- `POST /api/operator/vip/assign` returns HTTP 501 while the current demand has no VIP entity.
- Existing route, signal, optimization, telemetry, and scenario contracts remain in place; additive outcome fields distinguish success, partial, and rejection.

## Deferred verification and limitations

The full suite, test runner, browser acceptance, live paired closure/restore, active-constraint Quantum/Classical runs, and final acceptance report are intentionally deferred. The current demand has no supported runtime flow-route replacement path; affected flows block closure. Independent color timing and VIP dispatch remain unavailable under the current model.
