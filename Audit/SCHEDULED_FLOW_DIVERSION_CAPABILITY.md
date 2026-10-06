# Scheduled Flow Diversion — Implementation Notes

**Verification status:** Deferred. This file records implementation behavior and known limitations only; it does not claim acceptance.

## Current demand model

The normal/event scenario route inputs use loaded SUMO `flow` and `personFlow` records associated with static route definitions. At runtime, future departures do not yet exist as vehicle IDs. The integration can read those loaded route edges but has no supported path here to replace the route reference for a not-yet-inserted flow.

## TraCI mechanisms considered

- `vehicle.setRoute`, `vehicle.rerouteTraveltime`, and `vehicle.rerouteEffort` operate on active vehicles.
- `simulation.findRoute` plans a route but does not change a loaded flow definition.
- Runtime route registration does not itself rebind existing loaded flows to a replacement route.
- Rewriting route XML or restarting SUMO is outside the allowed live-diversion operation.

## Implemented behavior

- Loaded future-flow edge membership is part of the shared live constraint context.
- An edge closure request that conflicts with a loaded flow is rejected before any TraCI mutation.
- The closure endpoint returns structured `rejected` details; closure is not reported as successful after flow conflict.
- No XML rewrite or simulation restart is used to simulate runtime diversion.

## Remaining limitation

Runtime diversion of loaded future flows is not implemented for the current demand model. The safest supported path remains explicit rejection. A future approach would require a demand model that creates future vehicles under controller ownership (or another SUMO-supported live demand API), followed by a separate live test proving route assignment and subsequent departures avoid the target edge.

## Final verification phase

Deferred: do not treat implementation presence as live acceptance. Verify the exact installed SUMO/TraCI version's flow APIs and exercise closure rejection plus any supported diversion in a controlled live instance.
