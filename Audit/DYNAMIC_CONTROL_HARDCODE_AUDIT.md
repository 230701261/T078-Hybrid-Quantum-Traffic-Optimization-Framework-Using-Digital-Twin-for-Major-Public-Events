# Dynamic Control Hard-Code Audit

- **Test ID:** DTC-HARDCODE-20261006
- **Date/time:** 2026-10-06, 14:47 Asia/Kolkata
- **Feature:** Check operator controls for fixed behavior, fake successes and UI literals.
- **Input:** Source scan of `python/`, `ui/`, tests; review of new metadata/configuration and live endpoints.
- **Expected:** Operational choices derive from live SUMO/configuration; explicit profile values live in configuration; no fake success or fabricated outcomes.
- **Actual:** TLS IDs/phases and edge/route inventory are served from live TraCI/loaded route XML. UI selectors are populated from backend metadata. Weather/construction/VIP effect factors are externalized in `python/operator_profiles.json`. Existing canonical corridor/junction mapping remains a static topology configuration needed by optimization, not discovered operation behavior. Unsupported weather, fixed TLS timings, scheduled-flow block conflicts and VIP/construction conflict return rejection. The stale `ui/js/dashboard.js` hardcoded five-road list/fake zero fallback was removed in favor of telemetry-sorted live edges. The old `ui/js/renderer.js` is not imported by the active `ui/index.html`; it contains legacy canvas drawing/labels, while active mapping uses `renderer3d.js` and SUMO geometry.
- **TraCI command:** Read-only discovery uses route XML and TraCI ID/phase/lane/permission calls; mutations are accepted only with live readback.
- **Readback:** Browser showed actual TLS IDs and phase timing capabilities; live route/edge/TLS metadata returned 15/60/7 objects, respectively.
- **Evidence:** `rg` review of `python/`, `ui/`, `tests/`; browser live DOM; API readback; `python/operator_profiles.json`; `ui/index.html` script references.
- **Result:** **PARTIAL**. No fake result was introduced by this pass. Static four-corridor canonical mapping and mode/type aliases remain legitimate configured topology/domain metadata. Existing speed factors/caps are now explicit profile configuration, but they remain simplified model values, not physically validated weather/construction behavior.

## Remaining fixed/configured domain values

- Canonical corridor-to-edge and junction-to-TLS mappings remain in `python/integration/id_mapper.py` for the fixed Chepauk model and Quantum schema.
- Traffic demand bounds and SUMO type families remain configured in `python/scenario_inputs.py`.
- Weather speed factors, construction speed/cost factor, and VIP travel-cost factor are explicit values in `python/operator_profiles.json`.
- Quantum decision variables and SUMO topology remain unchanged.
