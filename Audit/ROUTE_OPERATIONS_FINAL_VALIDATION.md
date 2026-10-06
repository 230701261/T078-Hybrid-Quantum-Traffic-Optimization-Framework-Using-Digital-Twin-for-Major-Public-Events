# Route Operations — Implementation Notes

**Verification status:** Deferred to the requested final test phase.

- Active-vehicle routing uses `NetworkRoutingService`, which discovers alternatives through live SUMO route computation, starts at the current edge, preserves destination, validates access/connectivity/constraints, and requires route readback.
- Operator reroute commands and candidate routes pass through `ConstraintEngine` before mutation.
- Runtime edge closure uses actual lane permission restrictions with per-controller original permission snapshots.
- Paired closure preflights both SUMO contexts. Loaded future-flow conflicts reject before mutation. Affected active vehicles are routed around requested edges using current position and destination; a vehicle already on a target edge or with no safe alternative rejects the operation before mutation.
- Permission readback and route readback are required. If paired application fails, the operation attempts to restore original permissions and routes; the API distinguishes rejection from partial rollback.
- No live closure acceptance claim is made here. Final verification must exercise an eligible edge, an active-vehicle diversion, a flow-conflict rejection, and permission restoration.
