# Signal Timing Validation

- **Test ID:** DTC-SIGNAL-20261006
- **Date/time:** 2026-10-06, 14:30–14:46 Asia/Kolkata
- **Feature:** Dynamic TLS discovery and safe duration changes.
- **Input:** Live TLS metadata; attempt to change the active `J_CENTRAL_STAD` phase duration from 37 s to 38 s, then test a same-value request before the fixed-phase guard was tightened.
- **Expected:** TLS/program/phases/links come from TraCI. Duration is accepted only when live phase min/max bounds permit it; unsupported timing is rejected without claiming success.
- **Actual:** Seven live TLS programs were discovered, including phase states and controlled links. Loaded phases had equal min/max values (e.g. `J_CENTRAL_STAD` phase 0: 37/37 s; phase 2: 3/3 s). A 38 s request was rejected by live TraCI bounds. The UI now displays fixed duration and disables the apply button for fixed phases. The API now rejects all fixed min=max phases, including no-op same-value “changes.”
- **TraCI command:** `trafficlight.getIDList`, `getProgram`, `getAllProgramLogics`/complete program definition, `getPhase`, `getPhaseDuration`, `getNextSwitch`, `getRedYellowGreenState`, `getControlledLinks`; mutation through `setCompleteRedYellowGreenDefinition` only for supported phases.
- **Readback:** Live discovery returned 7 TLS IDs and actual phase definitions. The 38 s mutation was rejected; both SUMO sessions remained connected. Browser showed actual TLS and phase and disabled control with the fixed-bound reason.
- **Evidence:** Live `/api/network/signals` response and `/api/signals/configure` 422; browser accessibility state; final live status; existing `Audit/SIGNAL_CONTROL_VALIDATION.md`.
- **Result:** **PARTIAL / NOT SUPPORTED** for duration mutation in this current network because all tested phase intervals are fixed. Dynamic TLS discovery and truthful rejection pass.

## Limitation

Independent red/green/yellow timing is not represented by the tested active TLS program. The UI exposes discovered phase duration instead of pretending independent color timers exist.
