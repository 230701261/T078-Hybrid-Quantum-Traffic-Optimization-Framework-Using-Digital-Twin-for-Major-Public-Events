# Chepauk Traffic Digital Twin

**Hybrid Quantum Traffic Optimization Framework Using a Digital Twin for Major Public Events**
Project ID: T078

This repository is a research and engineering prototype for studying traffic operations around **MA Chidambaram Stadium (Chepauk), Chepauk MRTS station, and the Marina Beach coastal area in Chennai**. It combines a SUMO microscopic traffic network, TraCI control, a Python/FastAPI Digital Twin, a separate Quantum Optimization API, an operator dashboard built with Three.js, and an optional Supabase persistence layer.

The project supports normal-day and event-day scenarios, matched Classical/Quantum SUMO contexts, live telemetry, traffic-demand configuration, optimization application, route and signal inspection, operator constraints, and a Classical optimizer fallback. It is intended for local development, demonstrations, and research. Treat the audit records and the capability notes below as the source of truth for what has and has not been demonstrated; a working endpoint or UI status alone is not proof of a live traffic effect.

## Contents

- [System overview](#system-overview)
- [Repository structure and file guide](#repository-structure-and-file-guide)
- [Requirements](#requirements)
- [Installation](#installation)
- [Run the complete local system](#run-the-complete-local-system)
- [Use the dashboard](#use-the-dashboard)
- [HTTP and WebSocket API](#http-and-websocket-api)
- [Configuration and persistence](#configuration-and-persistence)
- [Tests and audit documents](#tests-and-audit-documents)
- [Current behavior and limitations](#current-behavior-and-limitations)
- [Troubleshooting](#troubleshooting)

## System overview

### Runtime data flows

**Simulation and visualization**

```text
SUMO network + demand files
        ↕ TraCI
Two coordinated SUMO contexts (Classical baseline and Quantum comparison)
        ↕
Python Digital Twin / FastAPI
        ├── REST controls and measured comparison
        └── /ws/simulation ──> browser app ──> Three.js renderers
```

**Optimization and application**

```text
Operator/API trigger
  → Integration Job Manager
  → QuantumOptimizationClient ──HTTP──> separate Quantum API (port 8001)
       └── if unavailable: existing in-process Classical optimizer fallback
  → result schema/18-bit validation
  → logical Quantum IDs mapped to SUMO IDs
  → shared ConstraintEngine checks the complete command batch
  → TraCI adapter applies supported commands to the Quantum SUMO context
  → live readback and result/status stream
```

The Quantum module is included in this repository under `quantum_module/Quantum-main`. The Digital Twin client prefers this bundled copy for its in-process Classical fallback and retains support for the legacy sibling checkout. The Quantum HTTP API remains a separate process on port 8001; the Digital Twin listener is on port 8000.

The Classical and Quantum map viewports use the same SUMO network geometry and coordinate system. They are backed by separate SUMO runs coordinated by the `SimulationPair`, not by a decorative duplicate map. The baseline receives the selected scenario and demand inputs; validated optimization actions are applied to the Quantum context. The comparison endpoint reports live measured values separately from optimizer/model estimates.

## Repository structure and file guide

The following inventory describes the checked-in source/configuration and audit files. Python caches, `.venv`, `.env`, generated outputs, and `node_modules` are local/generated artifacts and are not project source.

### Complete checked-in project tree

This tree is generated from the Git-tracked project files. The tables below explain the purpose and use of every file.

```text
project Traffic/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── package.json
├── package-lock.json
├── run_test_runner.py
├── restart_digital_twin.ps1
├── DYNAMIC_TRAFFIC_CONTROL_PLAN.md
├── FINAL_REMAINING_FIX_PLAN.md
├── FINAL_REMAINING_IMPLEMENTATION_PLAN.md
├── Audit/
│   ├── CLASSICAL_CONSTRAINT_VALIDATION.md
│   ├── CONSTRAINT_ENGINE_VALIDATION.md
│   ├── CONSTRAINT_INTERACTION_VALIDATION.md
│   ├── CONSTRUCTION_FINAL_VALIDATION.md
│   ├── CONSTRUCTION_RESTRICTION_VALIDATION.md
│   ├── CORRIDOR_BLOCK_VALIDATION.md
│   ├── CORRIDOR_DIVERSION_VALIDATION.md
│   ├── DATAFLOW_AUDIT.md
│   ├── DENSITY_CONTROL_TEST.md
│   ├── DESKTOP_UI_VALIDATION.md
│   ├── DYNAMIC_CONTROL_HARDCODE_AUDIT.md
│   ├── FINAL_ACCEPTANCE_REPORT.md
│   ├── FINAL_DYNAMIC_CONTROL_HARDCODE_AUDIT.md
│   ├── FINAL_DYNAMIC_CONTROL_REPORT.md
│   ├── FINAL_SYSTEM_HEALTH.md
│   ├── FIX_IMPLEMENTATION.md
│   ├── FIX_PLAN.md
│   ├── HARDCODE_AUDIT.md
│   ├── ISSUE_REGISTER.md
│   ├── LOCAL_INTEGRATION_AUDIT.md
│   ├── LOCAL_INTEGRATION_AUDIT_V2.md
│   ├── OPERATOR_CONTROL_TEST.md
│   ├── PARTIAL_FEATURE_COMPLETION_REPORT.md
│   ├── QUANTUM_CONSTRAINT_VALIDATION.md
│   ├── QUANTUM_E2E_VALIDATION.md
│   ├── QUANTUM_MAP_VALIDATION.md
│   ├── ROUTE_OPERATIONS_FINAL_VALIDATION.md
│   ├── ROUTE_OPERATIONS_VALIDATION.md
│   ├── SCHEDULED_FLOW_DIVERSION_CAPABILITY.md
│   ├── SIGNAL_CONTROL_VALIDATION.md
│   ├── SIGNAL_TIMING_FINAL_VALIDATION.md
│   ├── SIGNAL_TIMING_VALIDATION.md
│   ├── SPEED_CONTROL_TEST.md
│   ├── SUPABASE_VALIDATION.md
│   ├── SYSTEM_TEST_MATRIX.md
│   ├── TEST_RUNNER_CLEANUP.md
│   ├── THEME_VALIDATION.md
│   ├── TLS_TIMING_CAPABILITY.md
│   ├── TRAFFIC_CONFIGURATION_VALIDATION.md
│   ├── UI_QUALITY_AUDIT.md
│   ├── VIP_ASSIGNMENT_CAPABILITY.md
│   ├── VIP_ROUTE_FINAL_VALIDATION.md
│   ├── VIP_ROUTE_VALIDATION.md
│   ├── WEATHER_CONSTRAINT_VALIDATION.md
│   ├── run_test_runner.py
│   └── test_full_system.py
├── migrations/
│   └── 001_initial_supabase.sql
├── python/
│   ├── __init__.py
│   ├── comparison.py
│   ├── config.py
│   ├── input_validation.py
│   ├── main.py
│   ├── metrics_collector.py
│   ├── network_exporter.py
│   ├── network_routing_service.py
│   ├── operator_profiles.json
│   ├── scenario_inputs.py
│   ├── scenario_manager.py
│   ├── server.py
│   ├── simulation_pair.py
│   ├── traci_controller.py
│   ├── traci_session.py
│   ├── traffic_light_manager.py
│   └── integration/
│       ├── __init__.py
│       ├── constraint_engine.py
│       ├── id_mapper.py
│       ├── job_manager.py
│       ├── quantum_client.py
│       ├── quantum_sumo_adapter.py
│       ├── schemas.py
│       └── supabase_repository.py
├── sumo/
│   ├── additional.add.xml
│   ├── event_day.rou.xml
│   ├── event_day.sumocfg
│   ├── network.con.xml
│   ├── network.edg.xml
│   ├── network.net.xml
│   ├── network.nod.xml
│   ├── network.typ.xml
│   ├── normal_day.rou.xml
│   └── normal_day.sumocfg
├── tests/
│   ├── test_constraint_engine.py
│   ├── test_dynamic_operator_controls.py
│   ├── test_e2e_sumo_quantum_live.py
│   ├── test_edge_closure.py
│   ├── test_issue_resolution.py
│   ├── test_negative_and_idempotency.py
│   ├── test_quantum_digital_twin_integration.py
│   ├── test_quantum_fallback.py
│   ├── test_real_quantum_api.py
│   ├── test_routing_service.py
│   ├── test_scenario_inputs.py
│   ├── test_supabase_real.py
│   ├── test_theme_contract.py
│   └── test_tls_timing.py
└── ui/
    ├── index.html
    ├── css/
    │   └── style.css
    └── js/
        ├── app.js
        ├── controls.js
        ├── dashboard.js
        ├── renderer.js
        ├── renderer3d.js
        └── libs/
            ├── OrbitControls.js
            ├── chart.umd.min.js
            └── three.min.js
```

### Root files

| Path | Purpose |
|---|---|
| `README.md` | Project overview, architecture, setup, usage, file guide, and capability boundaries. |
| `.env.example` | Example environment variable names and placeholder values; contains no project credentials. |
| `.gitignore` | Keeps local environment secrets, Python caches, frontend dependencies, and Supabase CLI temporary state out of Git. |
| `requirements.txt` | Python runtime and test dependency ranges (FastAPI, Uvicorn, Pydantic, TraCI, sumolib, pytest). |
| `package.json` | Node package metadata; declares the Supabase JavaScript development dependency. The dashboard itself loads checked-in JS assets and does not require npm to run. |
| `package-lock.json` | Locks the Node dependency tree for reproducible npm installs. |
| `run_test_runner.py` | Root-level local REST/WebSocket smoke runner with cleanup for its server/SUMO resources. |
| `restart_digital_twin.ps1` | Gracefully restarts this project's server through its localhost control endpoint; it never kills a process and refuses unknown or legacy listeners. |
| `DYNAMIC_TRAFFIC_CONTROL_PLAN.md` | Design/implementation plan for operator traffic controls and their capability boundaries. |
| `FINAL_REMAINING_FIX_PLAN.md` | Remaining-issue analysis and proposed implementation work. |
| `FINAL_REMAINING_IMPLEMENTATION_PLAN.md` | Implementation-phase notes for the remaining dynamic traffic-control gaps. |

### `python/` — backend and simulation coordination

| Path | Purpose |
|---|---|
| `python/__init__.py` | Marks the backend as a Python package. |
| `python/main.py` | Direct startup entry point; supports `python python\\main.py`, starts one controllable Uvicorn server, and opens the dashboard in a browser. |
| `python/server.py` | FastAPI application, paired SUMO startup/shutdown, REST endpoints, optimization orchestration, event recording, and WebSocket telemetry broadcasting. |
| `python/config.py` | Resolves project/SUMO/UI paths and defines server host/port and simulation constants, including Quantum health timeout. Current host and port defaults are `127.0.0.1:8000`. |
| `python/traci_controller.py` | Owns a SUMO process and its TraCI connection; advances simulation steps and collects current state. |
| `python/traci_session.py` | Shared synchronization/locking helper for TraCI calls across worker threads and simulation contexts. |
| `python/simulation_pair.py` | Starts, controls, synchronizes, snapshots, and shuts down the Classical and Quantum SUMO instances using matched inputs. |
| `python/scenario_manager.py` | Scenario and simulation coordination helpers, including train and pedestrian behavior used by the Digital Twin. |
| `python/scenario_inputs.py` | Validates scenario demand and prepares scaled route-file inputs for configurable vehicles/pedestrians. |
| `python/metrics_collector.py` | Computes live SUMO-derived counts, speed, queues, congestion, and completed-trip measurements. |
| `python/comparison.py` | Pure helpers for deciding whether paired measurements are comparable and calculating measured deltas. |
| `python/network_exporter.py` | Reads the configured SUMO network and exports static geometry and junction/signal data for the browser renderer. |
| `python/network_routing_service.py` | Discovers and validates routes against the live SUMO network and provides active vehicle rerouting with readback. |
| `python/traffic_light_manager.py` | Traffic-light discovery, state inspection, and supported signal control helpers. |
| `python/input_validation.py` | Shared request validation helpers, including message/request identity checks. |
| `python/operator_profiles.json` | Data-driven weather, construction, VIP, and optimization effect profiles used by operator controls. |

### `python/integration/` — optimization, validation, mapping, and persistence

| Path | Purpose |
|---|---|
| `python/integration/__init__.py` | Exposes the integration package types/services. |
| `python/integration/schemas.py` | Pydantic request/response and action models exchanged by the Digital Twin, optimizer, and persistence layer. |
| `python/integration/quantum_client.py` | Calls the standalone Quantum API and invokes the existing Classical optimizer when the API is unreachable. |
| `python/integration/job_manager.py` | Runs optimization jobs, enforces request idempotency, tracks lifecycle state, validates results, and coordinates application. |
| `python/integration/id_mapper.py` | Maps the optimization module’s logical corridors/junctions to canonical and actual SUMO identifiers. |
| `python/integration/constraint_engine.py` | Shared hard-constraint validation boundary for a complete traffic-action batch before TraCI mutation. |
| `python/integration/quantum_sumo_adapter.py` | Converts validated optimization actions into SUMO/TraCI operations and gathers application/readback results. |
| `python/integration/supabase_repository.py` | Persistence abstraction: uses Supabase when configured and reachable; otherwise operates in local in-memory fallback mode. |

### `sumo/` — authoritative road network and demand

| Path | Purpose |
|---|---|
| `sumo/network.net.xml` | Compiled SUMO network loaded at runtime; authoritative roads, junctions, lanes, connections, and TLS topology. |
| `sumo/network.nod.xml` | Source node/junction geometry used to build the network. |
| `sumo/network.edg.xml` | Source road/edge definitions used to build the network. |
| `sumo/network.con.xml` | Explicit network connection definitions used by netconvert. |
| `sumo/network.typ.xml` | Shared SUMO edge/type definitions used to build the network. |
| `sumo/additional.add.xml` | Additional SUMO objects, including traffic-light and auxiliary definitions loaded by the scenario configs. |
| `sumo/normal_day.rou.xml` | Normal-day vehicle, pedestrian, route, and flow demand. |
| `sumo/event_day.rou.xml` | Event-day demand with stadium/event traffic surge behavior. |
| `sumo/normal_day.sumocfg` | SUMO configuration selecting the network, normal-day demand, step length, and runtime options. |
| `sumo/event_day.sumocfg` | SUMO configuration selecting the same network and event-day demand. |

Do not edit the compiled network or source topology casually: road connectivity and SUMO IDs are part of the integration contract. Scenario controls operate on generated/runtime demand inputs; the checked-in route files are the baseline definitions.

### `ui/` — browser dashboard

| Path | Purpose |
|---|---|
| `ui/index.html` | Dashboard document and structural containers for the operations panels, maps, controls, metrics, logs, and theme. |
| `ui/css/style.css` | Dashboard layout, responsive breakpoints, visual states, and Dark/Light theme CSS variables. |
| `ui/js/app.js` | Main application state, REST/WebSocket connection, telemetry processing, panel updates, and coordination between controls and renderers. |
| `ui/js/controls.js` | Operator UI controls that call the backend and display returned states/results. |
| `ui/js/dashboard.js` | KPI, chart, and Classical-vs-Quantum comparison presentation logic. |
| `ui/js/renderer.js` | Canvas/2D renderer support for the digital twin. |
| `ui/js/renderer3d.js` | Three.js scene, camera, road network, vehicles, pedestrians, signals, and map visualization. |
| `ui/js/libs/three.min.js` | Checked-in Three.js runtime library used by the renderer. |
| `ui/js/libs/OrbitControls.js` | Three.js camera orbit/pan/zoom controls. |
| `ui/js/libs/chart.umd.min.js` | Checked-in Chart.js browser bundle used for dashboard charts. |

### `migrations/` and `tests/`

| Path | Purpose |
|---|---|
| `migrations/001_initial_supabase.sql` | The repository’s initial Supabase/PostgreSQL schema migration for simulations, scenarios, optimization runs, traffic actions, and benefits. Apply this migration to a Supabase project before cloud persistence testing. |
| `tests/test_constraint_engine.py` | Constraint batch validation and rejection behavior. |
| `tests/test_dynamic_operator_controls.py` | Operator metadata and configured control-effect behavior. |
| `tests/test_e2e_sumo_quantum_live.py` | Live end-to-end integration test using SUMO/TraCI and the Quantum API when the external Quantum repository is available. |
| `tests/test_edge_closure.py` | Safety behavior and supported/unsupported edge closure handling. |
| `tests/test_issue_resolution.py` | Regression tests for previously identified integration/runtime issues. |
| `tests/test_negative_and_idempotency.py` | Invalid-input handling and duplicate optimization request behavior. |
| `tests/test_quantum_digital_twin_integration.py` | Integration-layer schemas, mapping, job lifecycle, and traffic action behavior. |
| `tests/test_quantum_fallback.py` | Classical fallback behavior when the Quantum API is unavailable. |
| `tests/test_real_quantum_api.py` | Starts/checks the Quantum API health and optimization response using the bundled Quantum module. |
| `tests/test_routing_service.py` | Routing-service behavior and active vehicle rerouting validation. |
| `tests/test_scenario_inputs.py` | Scenario demand validation and configured input scaling. |
| `tests/test_supabase_real.py` | Cloud persistence test; performs real database operations only when valid Supabase credentials and schema are configured. |
| `tests/test_theme_contract.py` | Static contract checks for the Dark/Light theme implementation. |
| `tests/test_tls_timing.py` | Supported TLS timing behavior and truthful handling of unsupported timing changes. |

### `Audit/` — validation records and capability notes

These are evidence/implementation records, not runtime source and not a guarantee that every listed feature is complete. Read the current health and issue records first; some documents describe completed checks while capability notes explicitly defer live verification.

| Path | Purpose |
|---|---|
| `Audit/CLASSICAL_CONSTRAINT_VALIDATION.md` | Evidence and status for constraint checks on Classical optimizer results. |
| `Audit/CONSTRAINT_ENGINE_VALIDATION.md` | ConstraintEngine implementation and validation record. |
| `Audit/CONSTRAINT_INTERACTION_VALIDATION.md` | Interactions among operator constraints and their validation behavior. |
| `Audit/CONSTRUCTION_FINAL_VALIDATION.md` | Current construction-control validation record. |
| `Audit/CONSTRUCTION_RESTRICTION_VALIDATION.md` | Construction restriction behavior and safety evidence. |
| `Audit/CORRIDOR_BLOCK_VALIDATION.md` | Corridor-block request handling, current rejection/safety behavior, and evidence. |
| `Audit/CORRIDOR_DIVERSION_VALIDATION.md` | Scheduled-flow diversion implementation notes and deferred verification scope. |
| `Audit/DATAFLOW_AUDIT.md` | Recorded control, telemetry, optimization, and persistence data flows. |
| `Audit/DENSITY_CONTROL_TEST.md` | Measured SUMO demand/density control experiment. |
| `Audit/DESKTOP_UI_VALIDATION.md` | Browser layout and viewport verification record. |
| `Audit/DYNAMIC_CONTROL_HARDCODE_AUDIT.md` | Review of configurable versus fixed dynamic-control parameters. |
| `Audit/FINAL_ACCEPTANCE_REPORT.md` | Overall acceptance snapshot and remaining blockers. |
| `Audit/FINAL_DYNAMIC_CONTROL_HARDCODE_AUDIT.md` | Follow-up hardcoding/configuration audit for dynamic controls. |
| `Audit/FINAL_DYNAMIC_CONTROL_REPORT.md` | Dynamic-control implementation scope and known limitations. |
| `Audit/FINAL_SYSTEM_HEALTH.md` | Latest system-health summary; currently records partial verification and blockers. |
| `Audit/FIX_IMPLEMENTATION.md` | Fixes implemented and supporting verification notes. |
| `Audit/FIX_PLAN.md` | Issue list and planned fixes with implementation disposition. |
| `Audit/HARDCODE_AUDIT.md` | Static configuration and dynamic-value audit. |
| `Audit/ISSUE_REGISTER.md` | Tracked issue register and current dispositions. |
| `Audit/LOCAL_INTEGRATION_AUDIT.md` | Earlier local integration audit covering components and runtime flow. |
| `Audit/LOCAL_INTEGRATION_AUDIT_V2.md` | Follow-up local audit with corrected startup, artifact, idempotency, fallback, and telemetry checks. |
| `Audit/OPERATOR_CONTROL_TEST.md` | Operator control test evidence for supported weather, VIP preference, and construction profile inputs. |
| `Audit/PARTIAL_FEATURE_COMPLETION_REPORT.md` | Implementation notes for dynamic controls that are partial or unsupported. |
| `Audit/QUANTUM_CONSTRAINT_VALIDATION.md` | Constraint validation behavior for Quantum optimization results. |
| `Audit/QUANTUM_E2E_VALIDATION.md` | Quantum API through validation, mapping, TraCI, and SUMO evidence. |
| `Audit/QUANTUM_MAP_VALIDATION.md` | Paired Classical/Quantum simulation and map comparison evidence. |
| `Audit/ROUTE_OPERATIONS_FINAL_VALIDATION.md` | Route-control implementation notes; consult the document for its stated verification scope. |
| `Audit/ROUTE_OPERATIONS_VALIDATION.md` | Route operation test evidence, including rerouting and restrictions. |
| `Audit/run_test_runner.py` | Audit-local REST/WebSocket smoke runner with orderly SUMO/TraCI shutdown. |
| `Audit/SCHEDULED_FLOW_DIVERSION_CAPABILITY.md` | Explains what is known about runtime diversion of loaded future flows and remaining limits. |
| `Audit/SIGNAL_CONTROL_VALIDATION.md` | Live signal-control/readback checks and current limitations. |
| `Audit/SIGNAL_TIMING_FINAL_VALIDATION.md` | Signal timing final status and evidence. |
| `Audit/SIGNAL_TIMING_VALIDATION.md` | Earlier signal timing validation record. |
| `Audit/SPEED_CONTROL_TEST.md` | Measured simulation speed multiplier behavior. |
| `Audit/SUPABASE_VALIDATION.md` | Supabase configuration and persistence status; distinguishes cloud from local fallback. |
| `Audit/SYSTEM_TEST_MATRIX.md` | Test matrix across local, runtime, UI, and integration behavior. |
| `Audit/test_full_system.py` | Audit-local full-system test harness. |
| `Audit/TEST_RUNNER_CLEANUP.md` | Test-runner process/TraCI cleanup changes and validation. |
| `Audit/THEME_VALIDATION.md` | Dark/Light theme and persistence verification. |
| `Audit/TLS_TIMING_CAPABILITY.md` | Active TLS program timing capability notes and limitations. |
| `Audit/TRAFFIC_CONFIGURATION_VALIDATION.md` | Configurable traffic demand validation evidence. |
| `Audit/UI_QUALITY_AUDIT.md` | UI layout, rendering, and quality observations. |
| `Audit/VIP_ASSIGNMENT_CAPABILITY.md` | Distinguishes VIP corridor preference from real VIP entity assignment capability. |
| `Audit/VIP_ROUTE_FINAL_VALIDATION.md` | VIP route implementation/validation status. |
| `Audit/VIP_ROUTE_VALIDATION.md` | VIP control test evidence and limitations. |
| `Audit/WEATHER_CONSTRAINT_VALIDATION.md` | Weather simulation profile control and readback validation. |

## Requirements

- **Windows, Linux, or macOS**. Commands below use PowerShell on Windows; adapt path separators and activation syntax for other shells.
- **Python 3.10 or newer** (the code uses modern Python type syntax).
- **SUMO** installed, with `sumo` available on `PATH` and its Python TraCI tools importable by the selected Python interpreter. SUMO and Python `traci`/`sumolib` versions should be compatible.
- **Node.js/npm** only if you want to run the JavaScript syntax check or manage the optional Node dependency. The dashboard’s checked-in libraries do not require `npm install` to serve.
- The bundled Quantum module under `quantum_module/Quantum-main` supplies the API and local Classical fallback. Its Python dependencies are listed in that folder's `requirements.txt`.
- A **Supabase project** only for cloud persistence. Local operation does not require Supabase.

## Installation

### 1. Get the project and bundled Quantum module

Clone this repository. Both modules are in the same checkout:

```text
project Traffic/
├── python/                      # Digital Twin backend
├── sumo/                        # SUMO network and scenarios
├── ui/                          # Dashboard and Three.js renderer
└── quantum_module/Quantum-main/ # Quantum API and optimizer
```

The client prefers the bundled source for its in-process Classical fallback and still recognizes a legacy sibling checkout. Set `QUANTUM_SERVICE_URL` only when the Quantum API is served at a non-default URL.

### 2. Install SUMO

Install SUMO for your operating system and ensure the SUMO executable and Python tools are available. On Windows, verify from a new PowerShell window:

```powershell
sumo --version
python -c "import traci, sumolib; print('TraCI and sumolib imports OK')"
```

If the second command fails, install/configure the SUMO Python tools for the same Python environment used below. Do not install a random `traci` package version that conflicts with your SUMO installation.

### 3. Create a Python environment

Run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r quantum_module\Quantum-main\requirements.txt
```

If PowerShell blocks virtual-environment activation, use the Python executable directly at `.venv\Scripts\python.exe`, or follow your organization’s normal PowerShell policy. The application’s configured HTTP host/port are in `python/config.py` (`127.0.0.1:8000` at present).

### 4. Configure optional environment variables

Use environment variables for service URLs and credentials. `.env.example` is a template only; its Supabase values are placeholders. Never commit `.env` or put service keys in browser files.

PowerShell for the current terminal session:

```powershell
$env:QUANTUM_SERVICE_URL = "http://127.0.0.1:8001"
$env:QUANTUM_TIMEOUT_SECONDS = "60"
# Optional; set real values only when you have a Supabase project and have applied the migration.
$env:SUPABASE_URL = "https://<your-project-ref>.supabase.co"
$env:SUPABASE_ANON_KEY = "<your-supabase-anon-key>"
```

The Supabase repository can load a root `.env` file when `python-dotenv` is installed. `python-dotenv` and the Python Supabase client are optional and are **not currently listed in `requirements.txt`**. To use `.env` loading and cloud persistence, install them explicitly:

```powershell
pip install python-dotenv supabase
Copy-Item .env.example .env
# Edit .env locally; do not commit it.
```

For reliable Quantum URL configuration, export `QUANTUM_SERVICE_URL` in the shell as shown above; the Quantum client reads the process environment directly. Supabase needs `SUPABASE_URL` and either `SUPABASE_ANON_KEY` or `SUPABASE_SERVICE_ROLE_KEY`. Keep service-role keys server-side and use the least-privileged key compatible with your database policies.

## Run the complete local system

Use **separate terminal windows** and activate the same project `.venv` in each. Both modules are in this checkout. Start the Quantum API before the Digital Twin if you want Quantum optimization rather than fallback.

### Terminal 1 — Quantum API

From this repository root:

```powershell
cd .\quantum_module\Quantum-main
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

Check that it is live and reports its decision-variable count:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

This API uses the included Quantum module source and its own requirements file. The Digital Twin can fall back to the module's Classical optimizer when the HTTP service is offline, but QAOA service operation requires the API process and its dependencies.

### Terminal 2 — Digital Twin backend and SUMO pair

From this repository root, activate `.venv`, then run either supported startup method:

```powershell
python python\main.py
```

To load changed Python source safely, run `./restart_digital_twin.ps1` from this repository root. It asks the current project server to shut down through its loopback-only shutdown endpoint, waits for SUMO cleanup and port 8000 release, then starts `python -m python.main` in the current terminal. It never kills a process. If the existing server is an older build without that endpoint, stop it with Ctrl+C in the PowerShell window that launched it, then rerun the script. A second `python -m python.main` invocation intentionally reuses the existing server and does not reload source code.

Use the dashboard's Reset control or `POST /api/control/reset` to restart only the Classical/Quantum SUMO pair from simulation time zero without restarting the HTTP server. `/api/simulation/state` includes live demand counters and `vehicle_demand_status`; `SIMULATION_RUNNING_NO_ACTIVE_VEHICLES` means vehicle demand has completed while the Digital Twin process remains available.

or:

```powershell
python -m uvicorn python.server:app --host 127.0.0.1 --port 8000
```

The FastAPI startup hook starts **two real SUMO/TraCI contexts** using the Normal Day scenario by default, computes the network geometry, and begins WebSocket telemetry. The direct script also opens the dashboard in the default browser. Keep this process running while using the UI/API. On shutdown, the application closes both SUMO contexts.

Open:

```text
http://127.0.0.1:8000/
```

The server mounts the dashboard assets from `ui/`; no separate frontend development server is required.

### Select scenarios and control the simulation

Use the dashboard or API to start/switch scenarios, pause, resume, stop, reset, and adjust simulation speed. Normal Day and Event Day both use the checked-in SUMO network, with their respective route/demand files. Traffic configuration is applied through the backend; changing a number in the browser is not itself evidence until the backend accepts and applies it.

### Run without the Quantum API

The optimization client attempts the configured Quantum endpoint first. If unavailable, it invokes the bundled Classical optimizer and labels the result `Classical (Fallback)`. This fallback is not Quantum execution. If both the API and bundled optimizer source are unavailable, optimization cannot complete.

## Use the dashboard

1. Start SUMO contexts by starting the Digital Twin backend.
2. Open the dashboard at `http://127.0.0.1:8000/`.
3. Confirm the actual connection/system status before interpreting any metrics.
4. Select Normal Day or Event Day and configure supported traffic/operator inputs.
5. Start/pause/resume/reset and adjust speed through the operations controls.
6. Use the optimization action to submit a request through the Digital Twin. The browser does not call the Quantum API directly.
7. Review optimization lifecycle, selected optimizer, bitstring, action counts, and application result. Check the returned status and live readback rather than treating a button response as proof of SUMO mutation.
8. Compare the side-by-side baseline/optimized map and measurements only when the backend reports the pair as synchronized. Travel-time measures remain unavailable until vehicles complete trips.

The dashboard consumes live simulation state via `/ws/simulation`, and uses REST endpoints for control/configuration. The Dark/Light theme preference is saved in browser local storage.

## HTTP and WebSocket API

FastAPI’s interactive endpoint reference is available at:

```text
http://127.0.0.1:8000/docs
```

Main routes implemented in `python/server.py` include:

| Method and path | Purpose |
|---|---|
| `GET /api/system/status` | Backend, Quantum-service, and persistence status information. |
| `GET /api/simulation/state` | Current paired simulation state. |
| `GET /api/comparison` | Paired live measurements, synchronization validity, and separately labeled model estimates. |
| `GET /api/network/geometry` | Static geometry exported from the loaded SUMO network for Three.js. |
| `GET /api/network/mappings` | Logical-to-SUMO mapping information. |
| `GET /api/network/routes` | Available route metadata. |
| `GET /api/network/edges` | Live network edge metadata for operator selection. |
| `GET /api/network/signals` | Live traffic-light metadata. |
| `GET /api/simulation/config` | Scenario/simulation configuration. |
| `GET /api/traffic/config` | Current traffic-demand configuration. |
| `GET /api/constraints` | Current constraints. |
| `GET /api/operator/state` | Current operator-control state. |
| `GET /api/operator/capabilities` | Reports supported/partial/unavailable operator capabilities. |
| `GET /api/operator/route-explainability` | Returns advisory recommendations from the latest optimizer response, decoded variables, live SUMO telemetry, and constraint checks. |
| `POST /api/control/start` | Starts or resumes the paired simulation. Optional `scenario=normal_day` or `event_day`. |
| `POST /api/control/pause` | Pauses both simulation contexts. |
| `POST /api/control/resume` | Resumes both simulation contexts. |
| `POST /api/control/stop` | Stops both contexts. |
| `POST /api/control/reset` | Resets/restarts the configured simulation pair. |
| `POST /api/control/speed?multiplier=2` | Sets simulation speed multiplier within backend validation limits. |
| `POST /api/control/scenario?scenario=event_day` | Changes the scenario. |
| `POST /api/traffic/configure` | Applies validated demand configuration. |
| `POST /api/constraints/weather` | Configures the simulation weather profile. |
| `POST /api/constraints/weather/reset` | Restores the configured baseline weather profile. |
| `POST /api/constraints/vip` | Applies supported VIP route/corridor preference settings. |
| `POST /api/constraints/construction` | Applies the supported construction profile. |
| `POST /api/operator/edge-closure` | Requests safe edge closure; may reject when live demand cannot be safely diverted. |
| `POST /api/operator/construction` | Applies supported construction mode; consult capability response for closure support. |
| `POST /api/operator/vip/assign` | Requests VIP entity route assignment; rejected if the demand model has no suitable live VIP entity. |
| `POST /api/signals/configure` | Requests supported signal control; active TLS program limits are enforced. |
| `POST /api/simulation/apply` | Applies a scenario/configuration to the paired simulation. |
| `POST /api/simulation/routes` | Applies supported route operations. |
| `POST /api/integration/trigger_optimization` | Starts or deduplicates an optimization request through the integration manager. |
| `GET /api/integration/runs` | Lists optimization runs. |
| `GET /api/integration/runs/{run_id}` | Retrieves a run. |
| `GET /api/integration/latest_plan` | Retrieves the latest plan/result available to the server. |
| `GET /api/operations/events` | Retrieves recorded system, traffic, and optimization events. |
| `WS /ws/simulation` | Streams live SUMO telemetry, paired states, events, operator timer state, optimization status, and the latest optimizer response. |

For exact request bodies, query constraints, response schemas, and current OpenAPI behavior, use `/docs`; the route list above is a navigation aid, not a replacement for the API schema.

## Configuration and persistence

### Supabase

Cloud storage is optional. To configure it:

1. Create a Supabase project.
2. Apply [`migrations/001_initial_supabase.sql`](migrations/001_initial_supabase.sql) to that project once.
3. Configure `SUPABASE_URL` and `SUPABASE_ANON_KEY` (or the server-only service role key where appropriate) in the backend environment.
4. Install optional Python dependencies `supabase` and `python-dotenv` if needed.
5. Start the server and check `/api/system/status` and the Supabase validation record.

Without credentials, or when cloud access/schema operations fail, the current repository abstraction uses a **process-local in-memory fallback**. That mode is not cloud persistence and its records do not survive process restart. Do not report cloud persistence as verified unless a real database transaction and subsequent query succeeded.

### Operator profiles and SUMO files

`python/operator_profiles.json` contains editable operator effect profiles. The SUMO `.sumocfg` files point to the matching route/demand and `additional.add.xml` files. Relative SUMO file paths are resolved from the SUMO configuration directory. Use the API and dashboard for normal operations; direct edits to generated/loaded simulation state can invalidate paired-run comparisons.

## Tests and audit documents

Run commands from the repository root with the project environment activated:

```powershell
# Focused test suite (includes local/unit tests; tests that need external services may be skipped or fail if dependencies are absent)
python -m pytest

# Named integration checks
python tests\test_quantum_digital_twin_integration.py
python tests\test_e2e_sumo_quantum_live.py

# REST/WebSocket smoke runner with SUMO cleanup
python run_test_runner.py
```

Some tests start live SUMO processes; the real Quantum API test uses the bundled Quantum source. The test suite is not a substitute for measuring actual traffic outcomes or checking runtime readback.

Start with [`Audit/FINAL_SYSTEM_HEALTH.md`](Audit/FINAL_SYSTEM_HEALTH.md), [`Audit/ISSUE_REGISTER.md`](Audit/ISSUE_REGISTER.md), and [`Audit/SYSTEM_TEST_MATRIX.md`](Audit/SYSTEM_TEST_MATRIX.md). Then consult the topic-specific audit documents listed in the repository guide. Audit files have different dates/scopes, so use the latest record for the feature and preserve distinctions between PASS, PARTIAL, BLOCKED, local fallback, and cloud mode.

## Current behavior and limitations

- **Quantum execution:** The standalone Quantum API is a separate dependency. Its client validates the response schema and the integration validates the 18-bit decision result before mapping/applying actions.
- **Fallback:** When the API is unavailable, the integration uses the bundled Classical optimizer and identifies it as `Classical (Fallback)`.
- **SUMO/TraCI:** The server starts two SUMO runs against the same network and scenario inputs. Dynamic behavior must be confirmed from TraCI readback; a generated command alone is not proof.
- **Constraint checks:** Quantum and Classical-generated commands pass through the shared `ConstraintEngine` batch validation boundary before supported commands are applied.
- **Rerouting:** Active rerouting is network-derived and requires a valid alternative and successful route readback. Requests without a valid alternative should be rejected.
- **Scheduled demand and full closure:** Loaded future flows may still reference the corridor requested for closure. The system preserves safety and can reject a closure rather than claim an unsupported diversion. Review `Audit/SCHEDULED_FLOW_DIVERSION_CAPABILITY.md` and `Audit/CORRIDOR_BLOCK_VALIDATION.md` before relying on closures.
- **Construction:** The configured construction speed/cost profile is distinct from actual arbitrary edge closure; only the latter would constitute a physical access block.
- **VIP:** Corridor preference/cost bias is distinct from assigning a route to a real VIP vehicle. Assignment requires an actual modeled entity; consult `Audit/VIP_ASSIGNMENT_CAPABILITY.md`.
- **Signal timing:** SUMO TLS phases enforce their configured min/max duration and movement state. Independent red/green/yellow timing is only available if represented by the active program; unsupported requests should not be treated as applied. Consult `Audit/TLS_TIMING_CAPABILITY.md`.
- **Metrics:** Counts, speed, queue, congestion, and completed-trip measures come from simulation telemetry. Model-estimated optimization benefits are separate from measured Classical-vs-Quantum deltas. Travel-time comparisons can be `N/A` when there are no completed trips.
- **Supabase:** Cloud persistence is unavailable until configured and transactionally verified. In-memory fallback is process-local and non-persistent.

The intended status of this checkout is **partially verified**, not an unconditional production certification. Re-check the relevant audit evidence on the machine and configuration where you run it.

## Troubleshooting

| Symptom | Checks |
|---|---|
| `sumo` not found | Install SUMO and add its binary directory to `PATH`; open a new shell and check `sumo --version`. |
| `No module named traci` / `sumolib` | Configure the SUMO tools for the same Python interpreter used by the virtual environment; check `python -c "import traci, sumolib"`. |
| Dashboard opens but simulation is offline | Check the backend console for SUMO startup errors and inspect `GET /api/system/status`; ensure port 8000 is available. |
| Quantum shows offline or Classical fallback | Check Quantum API process, `GET http://127.0.0.1:8001/health`, and `QUANTUM_SERVICE_URL`. Confirm Quantum repository dependencies are installed. |
| Fallback cannot import optimizer | Ensure the bundled `quantum_module/Quantum-main/optimization/` package is present; the legacy sibling checkout is also supported. |
| Optimization action is rejected | Inspect the structured API response, `/api/operations/events`, optimization run status, and SUMO/TraCI logs; validation rejection is intentional when an ID/action is invalid or unsafe. |
| Supabase says NOT CONFIGURED/UNAVAILABLE | Check environment variables without printing their values, install `supabase`/`python-dotenv` if using `.env`, apply the SQL migration, and verify network/database permissions. |
| Browser maps render blank | Check `/api/network/geometry`, browser console/WebGL support, and WebSocket status; use a current browser with hardware acceleration enabled. |

## License and third-party assets

Check repository licensing and upstream terms before redistribution. The browser bundles under `ui/js/libs/` are third-party libraries; their notices and licenses should be preserved when these assets are redistributed.
