# Quantum Map Validation

## Matched live pair

- Pair: `pair_89c185f9772f`
- Classical simulation: `pair_89c185f9772f_classical`
- Quantum simulation: `pair_89c185f9772f_quantum`
- Scenario: `normal_day`
- Same network/config identity was validated by the paired-run synchronization check; browser showed SYNCHRONIZED before and after the optimization, with transient SYNCING as clocks advanced.
- Both viewports rendered the SUMO network geometry from the same backend geometry endpoint. Separate live simulation states and TraCI contexts feed each canvas.

## Actual optimization

- UI-triggered real API/QAOA run: `8f52c1d7-88ab-4002-afce-105d890a99de`
- Bitstring: `010111000100000000` (18 binary bits)
- Runtime: 19.41 s
- Actions: 2 corridor decisions, 3 signal changes, 0 restrictions
- TraCI application: 21/21 commands succeeded with readback; UI displayed QUANTUM RESULT · APPLIED.

## Measured state

The browser received independent classical/quantum live telemetry and showed measured average speed, queue and congested-road comparisons; values continued changing while SUMO ran. At a sampled post-application frame: average speed 25.6 vs 25.9 km/h, queue 136.5 vs 110.5 m, congested roads 11 vs 10. These are snapshots, not a controlled causal improvement estimate: the pair clocks continued advancing and traffic is stochastic/stateful. Completed-trip travel time was N/A because no completed trips were in the paired sample window.

Quantum map verdict: **PASS for independent live SUMO state, same network and real applied actions; PARTIAL for controlled causal benefit attribution.** No improvement claim is made from the transient sample.

Final hardening pass (2026-10-06): the browser showed two rendered canvases on the same network while live paired SUMO ran Event Day. The Quantum API returned bitstring `101011110000000001`, objective `-391.06`, runtime `17.46 s`; 24/24 commands applied. Live metrics showed distinct baseline/optimized values after application. No causal benefit claim is made from this single run; model-derived savings remain labeled estimates.
