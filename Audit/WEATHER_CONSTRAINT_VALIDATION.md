# Weather Constraint Validation

- **Test ID:** DTC-WEATHER-20261006
- **Date/time:** 2026-10-06, 14:36–14:45 Asia/Kolkata
- **Feature:** Configured weather profile application and restoration.
- **Input:** `POST /api/constraints/weather` with `rain`, read actual lane maximum speed, then restore `clear`; also submit unconfigured `monsoon`.
- **Expected:** Only configured profiles are accepted; effect is applied to live SUMO parameters and read back; unsupported input is rejected.
- **Actual:** `rain` returned success and a lane readback of expected 9.999 m/s / actual 9.999 m/s. The clear profile restored successfully. `monsoon` returned HTTP 422. A profile configuration file now contains effect values rather than inline behavior branches.
- **TraCI command:** Existing `_apply_initial_inputs` writes `lane.setMaxSpeed` based on the configured profile and reads back `lane.getMaxSpeed`.
- **Readback:** Live lane parameter equaled configured expectation; both sessions remained connected after restore.
- **Evidence:** Live REST response, lane sample `:J_CENTRAL_STAD_0_0`, status endpoint; `python/operator_profiles.json`.
- **Result:** **PASS** for configured speed-factor profile application/readback. This is an explicit SUMO speed/routing proxy, not a physical weather model.

## Limitation

Intensity, visibility, friction and capacity are not currently modeled independently. The configured profile changes lane speed only.
