# VIP Route Final Validation

- **Test ID:** DYN-VIP-2026-10-06
- **Date/time:** 2026-10-06 (Asia/Kolkata)
- **Configuration:** Existing configured VIP corridor preference
- **Input:** VIP origin/destination dispatch request
- **Expected:** Dynamically calculate a valid route and assign it to a real VIP vehicle/flow with route readback
- **Actual:** Existing VIP behavior applies a configured adapted-travel-time preference to mapped corridor edges. There is no VIP OD entity assignment.
- **API:** Existing VIP constraint endpoint accepts enabled/corridor preference, not dynamic OD dispatch.
- **TraCI:** Adapted travel-time preference only
- **Readback:** Existing operator readback confirms cost preference, not route assignment.
- **Evidence:** `python/traci_controller.py` `_apply_initial_inputs`; prior VIP corridor readback does not satisfy dynamic assignment.
- **Result:** **FAIL** — required dynamic VIP route assignment is absent.
