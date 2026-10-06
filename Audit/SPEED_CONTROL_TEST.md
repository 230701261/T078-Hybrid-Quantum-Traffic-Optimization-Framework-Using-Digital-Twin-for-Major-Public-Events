# Controlled Speed Control Test

Live SUMO, label `speedaudit`; each setting was measured for 2.0 s wall time. Effective rate = SUMO delta / wall duration / 0.5 s configured simulation step.

| Multiplier | Wall Time | SUMO Start | SUMO End | Delta | Effective Rate |
|---:|---:|---:|---:|---:|---:|
| 1× | 2.00 s | 0.5 s | 2.5 s | 2.0 s | 2.00× |
| 2× | 2.00 s | 2.5 s | 6.0 s | 3.5 s | 3.50× |
| 3× | 2.00 s | 6.0 s | 11.5 s | 5.5 s | 5.50× |
| 4× | 2.00 s | 11.5 s | 19.5 s | 8.0 s | 8.00× |
| 1× return | 2.00 s | 19.5 s | 21.5 s | 2.0 s | 2.00× |

Observed progression is monotonic. Requested multipliers are simulation-step cadence targets, not guaranteed wall-clock factors; this host runs faster than real time and was especially above target at 3×–4×. Pause held at 21.5 s during a 0.7 s wall pause; resume advanced to 22.5 s within 0.8 s.

Result: **PASS for monotonic control and pause/resume; target rate is best-effort and exceeds the named factor on this host.**

Final hardening pass (2026-10-06): no speed-control code changed. The complete 32-test suite passed; real Event Day Digital Twin/Quantum run and runner WebSocket smoke test passed. Prior measured rate caveat is unchanged.
