# Operator Control Test

Live SUMO controller with Normal Day inputs: Heavy Rain, VIP priority on Triplicane High Road, Construction on Anna Salai, and J4 timings red=30 s / green=35 s / yellow=5 s.

| Control | Before | Input / TraCI action | Readback after | Result |
|---|---|---|---|---|
| Weather | Base lane max speeds | Heavy Rain factor 0.75 applied to each lane | 20 sampled lanes matched expected speed; `verified=true` | PASS |
| VIP | Base adapted travel times | Triplicane High Road priority factor 0.75 | 6 mapped edges matched requested adapted costs | PASS |
| Construction | Base lane speeds/costs | Anna Salai lane cap 2 m/s and adapted cost ×2 | 18 lanes and 6 edges matched | PASS |
| Route block | Active SUMO flows explicitly traverse Anna Salai edges | Live closure terminated SUMO with “vehicle has no valid route”; safe preflight now rejects before TraCI mutation | Controller remains RUNNING; zero closure commands sent | BLOCKED — requires flow-route diversion before closure |
| Route reopen | No live block applied after safe preflight | Not applicable in live flow-conflict case | Unit test with no scheduled-flow conflict verifies permission restoration | PARTIAL |
| Signal J4 | phase durations `[37,5,3,37,5,3]` | red=30, green=35, yellow=5 | SUMO program reported `[35,35,5,35,35,5]`; current program lacks a separate red-only phase class | PARTIAL / unsupported red timing |

Signal readback currently records what SUMO phase program can represent. A timing request is not considered fully applied unless each requested phase class can be represented and read back. No false successful red-timing claim is made. The safe route preflight prevents the earlier SUMO termination.

Final live check (2026-10-06): J4 request red=30/green=45/yellow=5 returned `status=partial`, `success=false`; SUMO reported red unsupported and read back actual durations `[45,45,5,45,45,5]`. UI/backend now surface the explicit unsupported phase. Anna Salai full-block attempt returned 422 before mutation; both SUMO runs remained connected. See the dedicated validation reports.

The patched UI was exercised live and showed `J4 cannot represent independent red timing`, without a success state; browser console had no errors/warnings.
