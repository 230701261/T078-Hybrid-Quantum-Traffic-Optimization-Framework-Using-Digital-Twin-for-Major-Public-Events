# Remaining Dynamic-Control Implementation Plan

## Current source-of-truth assessment

| Gap | Current implementation | Safe next change | Verification boundary |
|---|---|---|---|
| Active rerouting | `rerouteTraveltime` after corridor cost changes; latest real request failed route readback. Rollback replans from the live edge. | Add live alternative-route preflight and explicit route continuity/access checks before any vehicle mutation. | Must observe an actual changed route and retained destination; otherwise remain rejected. |
| Scheduled flow diversion/full closure | Block preflight rejects when any loaded future flow route uses target edges. SUMO flow route IDs are loaded from the active route file. | Keep rejection until a runtime-supported route-distribution/flow update is proven; do not edit route XML and imply an in-place update. | Future departure must be observed on new route before closure. |
| Construction | Configured corridor speed/cost only; lane permissions can represent closure. | Centralize hard-closure validation; expose actual edges only after transactional edge API exists. | Arbitrary edge selection and future-flow diversion remain unverified. |
| VIP | Configured corridor travel-time preference; no VIP entity, OD route, or assignment. | Keep the existing soft preference and reject VIP assignment requests until the model has a real VIP vehicle/flow input. | No UI success without an assigned SUMO entity and route readback. |
| Signal timing | Live TLS discovery and guarded phase duration; active loaded programs have fixed min/max and mixed movement states. | Keep truthful phase-duration limitations; independent color timing requires a safe TLS program configuration and transition review. | Readback of phase, next switch, and signal state required. |
| Weather | Explicit speed-factor profile only. | Preserve profile file; do not invent capacity/friction effects absent in SUMO model. | Speed and active profile readback only. |
| Constraint validation | Schema/ID validation precedes command mapping; no single live hard-constraint gate covers both optimizer outputs. | Add a shared pre-mutation `ConstraintEngine` at the shared TraCI adapter boundary. | Invalid/closed target must reject the entire command set before the first mutation. |
| Theme | Browser-verified Dark/Light, persistence, renderer background, desktop widths. | Preserve unchanged. | Existing theme tests and browser evidence. |

## Implementation order

1. Introduce a shared live TraCI constraint validator for all commands from either optimizer.
2. Move adapter effect factors into explicit operator configuration rather than inline values.
3. Add unit tests proving complete preflight rejection and no mutation for a hard-constraint conflict.
4. Retest current SUMO route alternatives using live edge/class data. Keep active reroute rejected unless a real alternative is read back.
5. Do not claim scheduled-flow diversion, full corridor closure, VIP dispatch, arbitrary-edge construction, or independent TLS color timing without a runtime mechanism and live readback.

## Acceptance

Overall result remains **PARTIALLY VERIFIED** until live alternate route, scheduled flow diversion, closed-edge behavior, dynamic VIP assignment, supported signal timing, and optimizer constraint enforcement are each demonstrated against SUMO/TraCI.
