# Controlled Density Test

Two separate live Normal Day SUMO instances used the same non-car inputs (buses 20/h, two-wheelers 150/h, pedestrians 300/h, local trains 4/h), seed defaults and 4× speed. Each measurement covered 60 simulated seconds.

| Cars configured | Simulated window | Wall time | SUMO departures | Active vehicles at capture | Completed trips |
|---:|---:|---:|---:|---:|---:|
| 1,000 veh/h | 60 s | 15.42 s | 29 | 29 | 0 |
| 2,000 veh/h | 60 s | 15.45 s | 47 | 47 | 0 |

The generated route files had distinct configuration hashes. Doubling configured car demand increased actual SUMO departures by 18 during the matched short window. No trips completed in this window, so completed-trip time is unavailable.

Result: **PASS — configured hourly demand changes actual generated vehicles.**

Final hardening pass (2026-10-06): no density logic changed. Full suite passed 32 tests; live Event Day telemetry displayed actual counts. Matched-run measurements in the original evidence remain the density acceptance evidence.
