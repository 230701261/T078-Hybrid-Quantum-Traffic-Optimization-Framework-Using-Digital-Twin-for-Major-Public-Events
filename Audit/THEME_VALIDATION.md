# Theme Validation

- **Test ID:** THEME-LIVE-20261006
- **Date/time:** 2026-10-06, Asia/Kolkata
- **Configuration:** Live Digital Twin at localhost; paired SUMO/TraCI; browser on the existing Chepauk dashboard.
- **Input:** Switch Dark → Light → refresh → Dark → refresh. Inspect computed dashboard/map colors, both WebGL canvases, viewport geometry, and console output.
- **Expected:** Theme changes without reload, persists across refresh, follows `prefers-color-scheme` only when no explicit preference is saved, affects Three.js presentation only, and keeps maps side by side.
- **Actual:** Clicking the visible theme control changed the root theme to `light`; computed body/panel/map backgrounds became `rgb(237, 242, 246)`, white, and `rgb(232, 238, 242)`. Both map canvases remained present. Refresh retained the selected Light theme. Dark mode likewise changed computed colors to `rgb(8, 13, 21)`, `rgb(16, 24, 35)`, and `rgb(7, 12, 19)` and survived refresh. Browser error/warning log was empty.
- **Operation:** Browser-local `localStorage` preference; CSS custom-property palette; renderer `setTheme()` updates scene background/fog, ground, and road materials. No backend endpoint or simulation parameter is changed.
- **Readback:** At 1440×900, 1600×900, and 1920×900, both themes had two canvases, equal-width side-by-side map panels (410, 490, and 650 px respectively), and document scroll width equal to viewport width.
- **Evidence:** Live browser interaction, computed style/layout readback, refresh persistence, screenshots, `tests/test_theme_contract.py`, and empty console warnings/errors.
- **Result:** **PASS** for live Dark/Light switch, persistence, both map canvases, and desktop layout. **PARTIAL** for system preference: default selection is implemented before page rendering, but an isolated no-preference browser context was not available to exercise that branch.

## Limits

Light/Dark changes visual presentation only. This test does not establish complete WCAG contrast conformance for every 3D object or all responsive/mobile layouts.
