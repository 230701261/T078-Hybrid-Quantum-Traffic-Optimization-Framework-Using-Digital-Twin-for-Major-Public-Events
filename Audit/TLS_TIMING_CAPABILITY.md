# TLS Timing — Implementation Notes

**Verification status:** Deferred. This document states current runtime behavior and does not claim final acceptance.

## Implemented behavior

- TLS IDs and active programs are discovered from live TraCI.
- Operator phase-duration changes use the active program's phase index, duration, `minDur`, and `maxDur` as validation inputs.
- Fixed phases (`minDur == maxDur`) and out-of-range requests are rejected before `setCompleteRedYellowGreenDefinition`.
- Mutable phases are updated only within declared bounds, then read back from the active live logic. Paired updates retain rollback behavior if the other SUMO context fails.
- The Quantum/Classical adapter uses the shared hard-constraint gate before applying a command batch.

## Capability boundary

The active project programs include phases with fixed duration bounds and mixed movement-state strings. The implementation does not infer independent red/green/yellow controls from those strings and does not alter the TLS topology or bypass safety bounds. Programmable TLS generation is not added because safe movement-conflict reconstruction is not established by the existing model.

## Final verification phase

Inspect all live TLS programs and verify a mutable phase update/readback where available, plus truthful rejection for fixed phases. Independent color timing remains unsupported unless a safe program transformation is separately designed and proven.
