# Construction Restriction Validation

- **Test ID:** DTC-CONSTRUCTION-20261006
- **Date/time:** 2026-10-06, 14:40–14:47 Asia/Kolkata
- **Feature:** Construction corridor reduced-speed/cost effect, interaction and disable.
- **Input:** Enable construction on configured corridor `Kamarajar Salai`, read affected lanes and costs, then disable. Request same-corridor VIP/construction conflict.
- **Expected:** Configured corridor is present; lane speed and routing cost are modified/read back; disable removes effect; overlapping hard preference conflicts are rejected.
- **Actual:** Construction enable returned verified true with 18 lane readbacks and configured edge costs. Disable returned verified false for active construction. Same-corridor VIP/construction request was rejected before restarting SUMO.
- **TraCI command:** `lane.setMaxSpeed` using the configured construction cap; `edge.adaptTraveltime` using configured travel-time factor; readback via `lane.getMaxSpeed` and `edge.getAdaptedTraveltime`.
- **Readback:** 18 affected lane values and edge costs verified for the selected mapped corridor; both SUMO sessions remained connected after restoration.
- **Evidence:** Live `/api/constraints/construction` responses and constraint conflict response; `python/operator_profiles.json`.
- **Result:** **PARTIAL**. Reduced-speed/cost control is live. Arbitrary edge selection and full closure/diversion are not supported; active-flow conflicts remain protected.

## Limitation

Construction is still selected by the existing configured corridor mapping; closure, severity, start/end window and arbitrary edge choices are not implemented. A speed/cost restriction is not represented as a full road closure.
