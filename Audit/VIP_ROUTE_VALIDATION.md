# VIP Route Validation

- **Test ID:** DTC-VIP-20261006
- **Date/time:** 2026-10-06, 14:40–14:46 Asia/Kolkata
- **Feature:** VIP route priority configuration and constraint interaction.
- **Input:** Enable the configured `Anna Salai` VIP corridor, verify readback, then disable it. Separately request VIP and construction on the same corridor.
- **Expected:** Current network mapping is validated, live route costs read back, disabling restores the non-VIP state, and hard constraint conflicts are rejected before restarting/mutation.
- **Actual:** VIP enable returned verified true with 3 edge-cost readbacks; disable returned `enabled=false`. Same-corridor VIP+construction request was rejected before a pair restart. Both SUMO contexts remained connected after the live control sequence.
- **TraCI command:** Existing VIP operation uses `edge.adaptTraveltime`; readback uses `edge.getAdaptedTraveltime`. Pair restart applies shared operator inputs to both contexts.
- **Readback:** `vip.enabled=true`, `verified=true`, 3 configured edge costs; final disabled readback false. Conflict rejection was observed.
- **Evidence:** Live `/api/constraints/vip`, `/api/operator/state`, and conflict response; prior `Audit/OPERATOR_CONTROL_TEST.md`.
- **Result:** **PARTIAL**. Configured corridor travel-cost preference is real and read back; a VIP vehicle, origin/destination, time window, chosen route, or signal reservation is not implemented or claimed.
