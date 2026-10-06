# T078 — Hybrid Quantum Traffic Optimization with a Digital Twin

A Chepauk traffic research system integrating SUMO, TraCI, a Python Digital Twin service, Quantum/QAOA optimization, a Classical fallback, WebSocket telemetry, and a Three.js dashboard. The target study area includes MA Chidambaram Stadium, Chepauk MRTS, and the Marina Beach coastal network.

## Project contents

- `sumo/` — Chepauk network, scenario configurations, route and demand files.
- `python/` — FastAPI server, TraCI controllers, paired simulations, routing, operator controls, and integration services.
- `python/integration/` — Quantum result validation/mapping, shared constraint validation, job management, and persistence abstraction.
- `ui/` — Existing dashboard, Three.js renderers, controls, WebSocket client, and Dark/Light theme.
- `tests/` and `Audit/` — Automated test sources and implementation/validation records.
- `migrations/` and `supabase/` — Optional persistence schema and Supabase integration assets.

The standalone Quantum optimization API is configured separately through `QUANTUM_SERVICE_URL` (default local URL in `.env.example`). It is not recreated by this repository.

## Local setup

Requirements: Python 3.10+, SUMO with TraCI Python tools, Node.js for JavaScript syntax checks, and a separately running Quantum API for Quantum optimization.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with environment-specific values; never commit .env.
python python\main.py
```

The integrated Digital Twin serves its dashboard and REST/WebSocket API on the configured server host/port. Start the standalone Quantum API from its own repository when Quantum optimization is required. If Supabase credentials are not configured, the existing local persistence fallback is used; that is not cloud persistence.

## Dynamic control behavior

Quantum results and Classical fallback results share the integration validation and TraCI application path. Active vehicle rerouting uses live SUMO route computation and route readback. Edge closure uses lane permissions and is rejected when loaded future flows cannot be safely diverted. The current demand model does not support runtime reassignment of already-loaded flow route references. VIP corridor preference is available, while assignment to a VIP vehicle requires a real modeled entity. TLS timing is limited by the active SUMO program's declared phase bounds.

The repository includes implementation and audit notes. They distinguish code paths from features that still require full live verification; consult `Audit/` before making research or production claims.

## Configuration and credentials

Copy `.env.example` to `.env` and configure only the environment variables needed for your deployment. `.env` is ignored by Git. Never put real credentials in source files, reports, commits, browser JavaScript, or issue text.
