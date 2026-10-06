# VIP Assignment — Implementation Notes

**Verification status:** Deferred. This is a capability note, not an acceptance result.

## Current data-model support

The current normal/event demand model contains no VIP vehicle type, VIP vehicle instance, or VIP flow. Creating an entity implicitly would introduce synthetic production traffic, so the implementation does not do that.

## Implemented behavior

- Existing VIP corridor cost preference remains in the operator profile and scenario configuration.
- `POST /api/operator/vip/assign` returns HTTP 501 with `status=unsupported` and reason code `VIP_ENTITY_NOT_CONFIGURED`.
- The UI labels the existing control as a corridor preference and explains that assignment needs a real SUMO demand entity.

## Remaining work

To support assignment, first add an explicit operator-controlled VIP vehicle/flow to the demand model. Then compute origin-to-destination routing from the live network, pass the route through `ConstraintEngine`, apply it to the real entity, and require `vehicle.getRoute()` readback before reporting success. That model change and live verification are deferred.
