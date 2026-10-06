# Signal Control Validation

- **Test ID:** AUD-09-LIVE-20261006
- **Date/time:** 2026-10-06, approx. 13:51 Asia/Kolkata
- **Configuration:** Live paired Normal Day SUMO/TraCI using the project's existing J4 TLS `J_CENTRAL_STAD`.
- **Input:** `POST /api/simulation/apply` with J4 timing `{red:30, green:45, yellow:5}`.
- **Expected:** Supported phase timings read back; unsupported timing is explicitly rejected/limited and never shown as successful.
- **Actual:** HTTP 200 with `status: partial`, `success: false`. Both SUMO readbacks reported `unsupported_timings:["red"]`; pre-phase durations were `[37,5,3,37,5,3]`, actual durations `[45,45,5,45,45,5]`. Thus green/yellow changes were applied and read back; independent red was not represented. The UI now displays the specific unsupported phase in its failure toast based on response `limitations`.
- **Evidence:** Live endpoint response and subsequent browser interaction against the patched UI. After cache-busting the changed script, the operator toast read: `Scenario rejected: Partial application: J4 cannot represent independent red timing. Other controls are shown in live SUMO readback.` Browser console had no errors/warnings.
- **Result:** **PARTIAL**, with the limitation visibly reported.

The original TLS is preserved. This pass does not redesign or replace its signal program.
