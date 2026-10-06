# Corridor Diversion and Closure — Implementation Notes

**Verification status:** Deferred to the requested final test phase.

- Existing corridor route-cost/diversion behavior remains available.
- Full closure uses live lane permissions, not speed or travel-time substitutes.
- Both paired contexts are preflighted before mutations. Loaded future-flow conflicts are rejected. Affected active vehicles are planned for a valid route around the target and rerouted before closure; a vehicle on the target edge or without an alternative causes rejection.
- Permission snapshots belong to the live SUMO process. A restart discards snapshots rather than restoring stale state.
- Successful closure requires permission readback in both contexts. Failure triggers rollback of permissions and any route changes already made; rollback failure is returned as partial.
- Construction `mode=closure` uses the paired edge operation; the existing speed/cost profile remains separate.
- Scheduled-flow diversion is not supported by the current loaded demand path. Edges used by those flows remain ineligible for closure.

No live closure acceptance claim is made here. Final testing must show an eligible edge close/readback/restore cycle, active-vehicle diversion, a future-flow conflict rejection, paired rollback, and SUMO health.
