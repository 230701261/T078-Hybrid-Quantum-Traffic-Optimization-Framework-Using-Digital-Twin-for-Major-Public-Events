# UI Quality Audit

## Layout and rendering

- The Chepauk operations UI loaded from the integrated server. It presents left scenario controls, classical and quantum canvas panels side by side, right-side live metrics/inspector, and bottom operation tabs.
- Browser showed two canvas map viewports using the existing SUMO geometry endpoint. The actual road network is provided by backend geometry; this audit did not establish a visual route-by-route topology comparison from a screenshot.
- The browser viewport was approximately **870×668**, below required desktop targets. The two maps were side by side but each was only around 190–203 px wide in that viewport. Desktop widths 1440×900, 1600×900, and 1920×1080 remain unverified.
- The UI console error/warning log was empty at the time inspected. No persistent JS rendering error was observed. Network requests were functional enough to populate live state; a full HAR/per-endpoint error inventory was not captured.

## Real telemetry / stale state

- Browser received actual Event Day telemetry: simulation time, vehicles, pedestrians, mode counts, trains, signal count, speed, queue, congestion, and stadium pedestrian count changed in the dashboard.
- Two SUMO IDs and actual pair IDs were displayed. Classical and Quantum KPI rows updated from different snapshots.
- In one bounded 8-second DOM poll the simulation clock string stayed at `13:57.5`, but a later accessibility-tree refresh showed `14:25.5` with updated counts and KPIs. That points to a slow/stale update observation rather than proof of a permanently frozen clock. The UI updates when classical snapshot frames arrive; speed-rate probe remains unreliable.
- No console errors or warnings were returned by browser inspection.

## Interactions / issues

| Control/area | Wiring found | Audit result |
|---|---|---|
| Normal/Event Day | Loads scenario config, apply submits scenario to paired SUMO contexts. | Backend route transition covered by runner; Event Day live. Full fresh Normal Day QAOA run not captured. |
| Density fields | Numeric values sent to `/api/simulation/apply`; server validates and scales actual route flows. | Request accepted at altered Event Day density and defaults restored. Did not quantify resulting vehicle generation under matched timed windows. |
| Apply both | Sends density, weather, VIP, construction, signal timings, route modifications; starts/restarts pair. | Endpoint code and successful live density apply observed. |
| Route controls | `/api/simulation/routes`; acts on actual lanes/edges and tries vehicle reroute. | No successful operator vehicle route-change observation. Block is a 0.1 m/s cap, not entry prohibition. |
| Start | `/api/control/resume`. | Resume works; label/function mismatch if simulations are stopped. |
| Pause/Resume | Real paired controller endpoints. | Pause held queue and average-speed snapshot unchanged over 3 seconds; resume returned not-paused. |
| Restart/Reset | `/api/control/reset` restarts pair with stored inputs. | Backend wiring; pair restart observed by apply operation. No separate UI click/readback test. |
| Speed | `/api/control/speed?multiplier=N`. | Handler exists. 1×–4× proportional wall-time rates were not established; measurement probes stalled. |
| Quantum | Calls Digital Twin endpoint (not direct browser-to-Quantum). | Live Quantum result and fallback both observed. UI shows returned optimizer/bitstring/result. Granular lifecycle stages are mostly client-side transition text, not backend stage stream. |
| Bottom map layers/camera sync | Renderer layer toggles and camera change forwarding. | Source wired; not exhaustively toggled and visually verified. |
| Supabase | Status from system status API. | Correctly showed NOT CONFIGURED; no cloud indication of connected. |

## Accessibility and usability

- Main controls use labels/buttons and native selects/inputs. Browser accessibility tree exposed changing telemetry and controls.
- The very dense layout is compressed below desktop width, and primary desktop breakpoints were not validated.
- Comparison badge overstates synchronization because it tests only that two simulation IDs exist.
- The initial status labels in HTML default to LIVE/RUNNING before asynchronous checks finish.
- Route explainability explicitly presents N/A for route-level measured travel time / queue comparison; useful honesty, but the separate benefit strip presents modeled benefit estimates without an explicit “estimated” label.

## UI verdict

**PARTIAL.** Final hardening verified desktop layouts at 1440×900, 1600×900, and 1920×1080 and a clean browser console. Real WebSocket telemetry and both maps render; remaining partial areas are full corridor closure, independent red timing, cloud persistence without credentials, and matched causal performance measurement.
