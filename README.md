# T078 — Hybrid Quantum Traffic Optimization with a Digital Twin

A Chepauk traffic research system integrating SUMO, TraCI, a Python Digital Twin service, Quantum/QAOA optimization, a Classical fallback, WebSocket telemetry, and a Three.js dashboard. The target study area includes MA Chidambaram Stadium, Chepauk MRTS, and the Marina Beach coastal network.

## Project contents

# Chepauk Quantum Traffic Digital Twin

A **Quantum-Enhanced Traffic Digital Twin** for the MA Chidambaram Stadium (Chepauk), Chennai. The project combines **SUMO microscopic traffic simulation, TraCI-based control, Python backend services, Three.js 3D visualization, and quantum traffic optimization** to simulate and optimize traffic during normal and event-day conditions.

The system supports multimodal traffic including **cars, buses, two-wheelers, pedestrians, and local trains**, with configurable traffic demand, route operations, traffic-signal timing, weather, VIP routes, and construction constraints.

---

## 1. Project Overview

The system is divided into three major layers:

```text
                    CHEPAUK TRAFFIC DIGITAL TWIN
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        SUMO / TraCI      Integration      Three.js UI
        Digital Twin         Layer          Visualization
              │               │               │
              │          Quantum Module      │
              │               │               │
              └───────────────┼───────────────┘
                              │
                       Traffic Simulation
                         & Optimization
```

### Main workflow

```text
Traffic Scenario
       ↓
SUMO Simulation
       ↓
TraCI Controller
       ↓
Digital Twin Backend
       ↓
Traffic Condition / Optimization Trigger
       ↓
Quantum Optimization
       ↓
Optimization Result
       ↓
ID Mapping & Traffic Actions
       ↓
TraCI Commands
       ↓
SUMO State Updated
       ↓
WebSocket
       ↓
Three.js Digital Twin
```

---

# 2. Main Modules

## 2.1 SUMO–Digital Twin Module

The **SUMO–Digital Twin module** is primarily located in:

```text
sumo/
python/
ui/
```

It is responsible for:

- Microscopic traffic simulation
- Road-network representation
- Vehicle and pedestrian movement
- Traffic-signal simulation
- Scenario management
- TraCI communication
- Live traffic metrics
- 3D Digital Twin visualization
- Classical and optimized traffic views

### Core technologies

- SUMO
- TraCI
- Python
- FastAPI/Uvicorn
- WebSocket
- Three.js
- HTML/CSS/JavaScript

---

## 2.2 Quantum Module

The Quantum-related part of this repository is primarily represented by the **integration layer**:

```text
python/integration/
```

Important Quantum-related files are:

```text
quantum_client.py
quantum_sumo_adapter.py
schemas.py
constraint_engine.py
id_mapper.py
job_manager.py
```

The integration layer communicates with the Quantum optimization service, validates its results, maps optimization decisions to SUMO identifiers, and converts them into traffic-control actions.

> **Note:** `python/integration/` is the Quantum–Digital Twin integration layer. The standalone Quantum/QAOA optimizer service itself may be maintained as a separate module/repository depending on the deployment setup. This repository contains the client/API integration required to connect that optimizer to SUMO.

---

# 3. Project Structure

```text
project Traffic/
│
├── .git/
├── .github/                         # Git/GitHub configuration if present
│
├── Audit/                           # Project audit and verification documents
│
├── migrations/                      # Database migration files
│
├── node_modules/                    # Node.js dependencies
│
├── python/                           # Main Python backend
│   │
│   ├── __init__.py
│   ├── main.py
│   ├── server.py
│   ├── config.py
│   ├── comparison.py
│   ├── input_validation.py
│   ├── metrics_collector.py
│   ├── network_exporter.py
│   ├── network_routing_service.py
│   ├── operator_profiles.json
│   ├── scenario_inputs.py
│   ├── scenario_manager.py
│   ├── simulation_pair.py
│   ├── traci_controller.py
│   ├── traci_session.py
│   ├── traffic_light_manager.py
│   │
│   └── integration/
│       ├── __init__.py
│       ├── constraint_engine.py
│       ├── id_mapper.py
│       ├── job_manager.py
│       ├── quantum_client.py
│       ├── quantum_sumo_adapter.py
│       ├── schemas.py
│       └── supabase_repository.py
│
├── sumo/                            # SUMO traffic simulation
│   ├── additional.add.xml
│   ├── event_day.rou.xml
│   ├── event_day.sumocfg
│   ├── network.con
│   ├── network.edg.xml
│   ├── network.net.xml
│   ├── network.nod.xml
│   ├── networktyp.xml
│   ├── normal_day.rou.xml
│   └── normal_day.sumocfg
│
├── ui/                              # Three.js Digital Twin frontend
│   ├── index.html
│   │
│   ├── css/
│   │   └── style.css
│   │
│   └── js/
│       ├── app.js
│       ├── controls.js
│       ├── dashboard.js
│       ├── renderer.js
│       ├── renderer3d.js
│       │
│       └── libs/
│           ├── three.min.js
│           ├── OrbitControls.js
│           └── chart.umd.min.js
│
├── supabase/                        # Supabase project configuration
│   └── .temp/
│
├── tests/                           # Automated test suite
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
│
├── .env.example
├── .gitignore
├── package.json
├── package-lock.json
├── README.md
├── requirements.txt
├── run_test_runner.py
│
├── DYNAMIC_TRAFFIC_CONTROL_PLAN.md
├── FINAL_REMAINING_FIX_PLAN.md
└── FINAL_REMAINING_IMPLEMENTATION_PLAN.md
```

---

# 4. SUMO Module

The `sumo/` directory contains the actual traffic simulation environment.

```text
sumo/
├── network.net.xml
├── network.nod.xml
├── network.edg.xml
├── network.con
├── networktyp.xml
├── additional.add.xml
├── normal_day.rou.xml
├── normal_day.sumocfg
├── event_day.rou.xml
└── event_day.sumocfg
```

### `network.nod.xml`

Defines the **nodes/junctions** of the road network.

### `network.edg.xml`

Defines the **road edges and connections** between network nodes.

### `network.net.xml`

The compiled SUMO network used by the simulator.

### `network.con`

Contains network connection information used during network construction.

### `networktyp.xml`

Contains SUMO network type definitions.

### `additional.add.xml`

Contains additional SUMO objects such as traffic-related configurations.

### `normal_day.rou.xml`

Defines traffic routes and demand for the **Normal Day** scenario.

### `event_day.rou.xml`

Defines traffic routes and demand for the **Event Day** scenario.

### `normal_day.sumocfg`

SUMO configuration file for the Normal Day simulation.

### `event_day.sumocfg`

SUMO configuration file for the Event Day simulation.

---

# 5. Python Digital Twin Backend

The main Digital Twin backend is inside:

```text
python/
```

## `server.py`

Main backend/server for the Digital Twin.

It provides APIs and WebSocket communication for:

- Simulation state
- Optimization triggering
- Comparison information
- Run information
- Latest optimization plan
- Frontend communication

The Digital Twin frontend communicates with this backend rather than directly communicating with the Quantum API.

---

## `traci_controller.py`

One of the most important files in the project.

It manages communication between:

```text
Python ↔ TraCI ↔ SUMO
```

Responsibilities include:

- Starting SUMO
- Connecting through TraCI
- Advancing simulation time
- Reading simulation state
- Reading vehicles
- Reading traffic lights
- Applying traffic-control actions
- Updating SUMO during optimization

---

## `traci_session.py`

Provides session-level management for the TraCI connection and simulation lifecycle.

---

## `traffic_light_manager.py`

Manages traffic-signal-related operations.

It is responsible for:

- Junction signals
- Signal timing
- Signal phases
- Applying signal changes to SUMO

---

## `scenario_manager.py`

Manages the selected simulation scenario.

Examples:

```text
Normal Day
Event Day
```

---

## `scenario_inputs.py`

Handles configurable traffic and scenario inputs such as:

- Cars
- Buses
- Two-wheelers
- Pedestrians
- Local trains
- Weather
- VIP conditions
- Construction conditions

---

## `metrics_collector.py`

Collects traffic metrics from the simulation.

Examples include:

- Vehicle counts
- Pedestrian counts
- Average speed
- Queue information
- Traffic conditions
- Traffic-signal state

---

## `network_exporter.py`

Exports or prepares SUMO network information for use by the Digital Twin and frontend.

---

## `network_routing_service.py`

Provides routing-related services for the simulated road network.

It handles route-related operations and supports traffic-routing decisions.

---

## `simulation_pair.py`

Supports the paired simulation concept used by the interface:

```text
Classical Baseline
        VS
Quantum Optimized
```

---

## `comparison.py`

Provides comparison information between simulation states and optimization results.

---

## `input_validation.py`

Validates traffic and scenario inputs before they are passed into the simulation.

---

## `config.py`

Contains backend configuration and simulation-related settings.

---

## `main.py`

Application entry point/module initialization.

For the current project structure, the backend is preferably started through Uvicorn rather than executing `python main.py` directly.

---

# 6. Quantum–Digital Twin Integration

The following directory is the central integration layer:

```text
python/integration/
```

---

## `quantum_client.py`

Connects the Digital Twin backend to the external Quantum optimization API.

Main flow:

```text
Digital Twin
     ↓
Quantum Client
     ↓
Quantum API
     ↓
Optimization Result
```

---

## `quantum_sumo_adapter.py`

Converts Quantum optimization results into SUMO/TraCI-compatible traffic actions.

For example:

```text
Quantum Decision
       ↓
Traffic Action
       ↓
SUMO/TraCI Command
```

---

## `constraint_engine.py`

Handles traffic constraints used by the optimization and traffic-control workflow.

Examples include:

- Weather
- VIP priority
- Construction
- Route restrictions
- Operational constraints

---

## `id_mapper.py`

Maps the logical identifiers used by the Quantum module to the actual SUMO network identifiers.

For example:

```text
Quantum Corridor
       ↓
Canonical Corridor ID
       ↓
SUMO Edge IDs
```

It also maps traffic junction identifiers to SUMO traffic-light IDs.

---

## `job_manager.py`

Controls the optimization-job lifecycle.

It manages:

- Optimization requests
- Job execution
- Result processing
- Application of results
- Duplicate/same-run protection
- Job status

---

## `schemas.py`

Defines the data contracts used between the modules.

It validates:

- Optimization requests
- Optimization responses
- Bitstrings
- Traffic actions
- Job information
- Result structures

---

## `supabase_repository.py`

Provides the persistence layer for:

- Simulation runs
- Optimization runs
- Traffic actions
- Optimization benefits

The implementation also supports local/in-memory fallback when cloud persistence is unavailable.

---

# 7. Frontend / Digital Twin Visualization

The frontend is inside:

```text
ui/
```

---

## `index.html`

Main HTML page for the Digital Twin dashboard.

It contains the dashboard structure, panels, controls, maps, metrics, and simulation interface.

---

## `css/style.css`

Contains the complete visual styling for the dashboard.

It controls:

- Layout
- Colors
- Panels
- Cards
- Buttons
- Typography
- Traffic indicators
- Responsive structure
- Dark/light interface elements

---

## `js/app.js`

Main frontend application logic.

Responsible for connecting the UI to the backend and managing application state.

---

## `js/controls.js`

Handles user controls such as:

- Scenario selection
- Simulation controls
- Optimization controls
- Configuration changes
- User interactions

---

## `js/dashboard.js`

Manages dashboard-specific information and live metrics.

---

## `js/renderer.js`

Handles general rendering functionality.

---

## `js/renderer3d.js`

Main **Three.js Digital Twin rendering module**.

Responsible for:

- 3D road network
- Vehicles
- Traffic objects
- Camera
- Scene rendering
- Visualization updates

---

# 8. Frontend Libraries

```text
ui/js/libs/
├── three.min.js
├── OrbitControls.js
└── chart.umd.min.js
```

### `three.min.js`

Three.js library used for the 3D Digital Twin.

### `OrbitControls.js`

Provides camera navigation and interaction with the 3D scene.

### `chart.umd.min.js`

Used for chart/graph-based visualization.

---

# 9. Tests

The `tests/` directory contains unit, integration, and end-to-end tests.

| File | Purpose |
|---|---|
| `test_constraint_engine.py` | Tests traffic constraint processing |
| `test_dynamic_operator_controls.py` | Tests dynamic operator controls |
| `test_e2e_sumo_quantum_live.py` | End-to-end Quantum + SUMO + TraCI test |
| `test_edge_closure.py` | Tests road/edge closure functionality |
| `test_issue_resolution.py` | Regression/issue-resolution tests |
| `test_negative_and_idempotency.py` | Negative cases and duplicate handling |
| `test_quantum_digital_twin_integration.py` | Quantum–Digital Twin integration tests |
| `test_quantum_fallback.py` | Quantum service fallback behaviour |
| `test_real_quantum_api.py` | Tests the real Quantum API connection |
| `test_routing_service.py` | Tests routing functionality |
| `test_scenario_inputs.py` | Tests scenario configuration |
| `test_supabase_real.py` | Tests Supabase connectivity |
| `test_theme_contract.py` | Tests frontend theme requirements |
| `test_tls_timing.py` | Tests traffic-light timing |

---

# 10. Database / Supabase

The project contains:

```text
migrations/
supabase/
```

The database layer is designed to store information related to:

```text
Simulations
Optimization Runs
Traffic Actions
Optimization Benefits
```

The `.env.example` file provides the expected environment-variable structure.

Do not commit actual Supabase credentials or API keys.

---

# 11. Root-Level Files

### `.env.example`

Example environment configuration.

Use this as the template for creating your local `.env`.

---

### `.gitignore`

Specifies files and directories that should not be committed to Git.

---

### `requirements.txt`

Python dependencies required by the backend, SUMO/TraCI integration, API, and testing environment.

---

### `package.json`

Node.js project configuration and frontend dependencies.

---

### `package-lock.json`

Locks the Node.js dependency versions.

---

### `run_test_runner.py`

Runs the project's broader integration/test workflow.

---

### `README.md`

Main project documentation.

---

### `DYNAMIC_TRAFFIC_CONTROL_PLAN.md`

Documentation related to the dynamic traffic-control implementation.

---

### `FINAL_REMAINING_FIX_PLAN.md`

Contains remaining fixes and implementation tasks.

---

### `FINAL_REMAINING_IMPLEMENTATION_PLAN.md`

Contains implementation planning and remaining development work.

---

# 12. How the Modules Connect

The most important architecture is:

```text
                         ┌───────────────────┐
                         │   Three.js UI     │
                         │   Digital Twin    │
                         └─────────▲─────────┘
                                   │
                              WebSocket
                                   │
                         ┌─────────┴─────────┐
                         │  Python Server    │
                         │    server.py      │
                         └─────────┬─────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                 TraCI       Integration      Metrics
                    │              │
                    │        ┌─────┴──────┐
                    │        │ Quantum    │
                    │        │ Client     │
                    │        └─────┬──────┘
                    │              │
                    │        Quantum API
                    │              │
                    │        Optimization
                    │              │
                    │        Result / Bitstring
                    │              │
                    │        ID Mapping
                    │              │
                    │        SUMO Adapter
                    │              │
                    └───────► SUMO ◄┘
```

---

# 13. Complete Data Flow

### Step 1 — Scenario Configuration

The user selects:

```text
Normal Day / Event Day
```

and configures:

```text
Cars
Buses
Two-wheelers
Pedestrians
Local trains
Weather
VIP routes
Construction
Signal timing
```

↓

### Step 2 — SUMO

SUMO loads the selected:

```text
*.sumocfg
*.rou.xml
network.net.xml
```

and starts the microscopic traffic simulation.

↓

### Step 3 — TraCI

`traci_controller.py` connects Python to SUMO.

It retrieves:

```text
Vehicles
Pedestrians
Traffic signals
Road states
Simulation time
Traffic conditions
```

↓

### Step 4 — Digital Twin Backend

`server.py` processes the simulation state and exposes it through APIs/WebSocket.

↓

### Step 5 — Optimization Trigger

When optimization is required:

```text
server.py
    ↓
job_manager.py
    ↓
quantum_client.py
    ↓
Quantum API
```

↓

### Step 6 — Quantum Optimization

The Quantum module calculates the traffic optimization decision.

The result contains the optimization information/bitstring and traffic actions.

↓

### Step 7 — Validation and Mapping

```text
schemas.py
     ↓
constraint_engine.py
     ↓
id_mapper.py
     ↓
quantum_sumo_adapter.py
```

The result is converted into valid SUMO road/junction actions.

↓

### Step 8 — TraCI Application

The generated actions are sent to the running SUMO simulation.

Possible actions include:

```text
Route changes
Traffic-signal changes
Traffic restrictions
```

↓

### Step 9 — Updated SUMO State

SUMO continues the simulation using the updated traffic-control conditions.

↓

### Step 10 — Digital Twin Visualization

The updated state is sent through:

```text
SUMO
 ↓
TraCI
 ↓
Python
 ↓
WebSocket
 ↓
app.js
 ↓
renderer3d.js
 ↓
Three.js
```

and displayed in the Digital Twin.

---

# 14. Which Files Belong to Which Module?

## 🟦 SUMO / Digital Twin Module

Primary files:

```text
sumo/

python/server.py
python/traci_controller.py
python/traci_session.py
python/traffic_light_manager.py
python/scenario_manager.py
python/scenario_inputs.py
python/metrics_collector.py
python/network_exporter.py
python/network_routing_service.py
python/simulation_pair.py
python/comparison.py

ui/
```

The **most important Digital Twin files** are:

```text
python/traci_controller.py
python/server.py
python/metrics_collector.py
python/scenario_manager.py
python/traffic_light_manager.py
ui/js/renderer3d.js
ui/js/app.js
```

---

## 🟪 Quantum Module / Quantum Integration

Within this repository, the Quantum integration is primarily:

```text
python/integration/quantum_client.py
python/integration/quantum_sumo_adapter.py
python/integration/constraint_engine.py
python/integration/id_mapper.py
python/integration/job_manager.py
python/integration/schemas.py
```

The most important files are:

```text
quantum_client.py
       ↓
quantum_sumo_adapter.py
       ↓
id_mapper.py
       ↓
job_manager.py
       ↓
TraCI / SUMO
```

The **actual QAOA/QUBO optimization service** is accessed through `quantum_client.py`; it is not represented as a standalone QAOA implementation in the file tree shown here.

---

# 15. Installation

## Requirements

Install the following:

- Python 3.x
- SUMO
- Node.js
- npm
- Git

Verify:

```bash
python --version
```

```bash
sumo --version
```

```bash
sumo-gui --version
```

```bash
node --version
```

```bash
npm --version
```

---

# 16. Python Environment

Create a virtual environment:

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
```

### Linux/macOS

```bash
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

# 17. Install Frontend Dependencies

From the project root:

```bash
npm install
```

This installs the dependencies specified in:

```text
package.json
```

---

# 18. Environment Configuration

Copy:

```text
.env.example
```

to:

```text
.env
```

Configure the required environment variables.

For example:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
QUANTUM_API_URL=http://127.0.0.1:8001
```

Use the actual variables defined in your `.env.example`.

**Never commit `.env` to Git.**

---

# 19. Running the SUMO Simulation

You can run SUMO directly using the scenario configuration.

### Normal Day

```bash
sumo-gui -c sumo/normal_day.sumocfg
```

### Event Day

```bash
sumo-gui -c sumo/event_day.sumocfg
```

For the Digital Twin, SUMO is normally started and controlled through the Python/TraCI backend rather than manually controlling the SUMO GUI.

---

# 20. Running the Digital Twin Backend

From the project root:

```bash
python -m uvicorn python.server:app --host 127.0.0.1 --port 8000
```

The Digital Twin backend will run at:

```text
http://127.0.0.1:8000
```

The backend provides the simulation APIs and WebSocket endpoint.

Example:

```text
/ws/simulation
```

---

# 21. Running the Quantum Service

The Quantum optimizer service should be started separately if it is maintained as a separate service/repository.

The integration expects the Quantum API to be available at:

```text
http://127.0.0.1:8001
```

The main optimization endpoint is:

```text
POST /api/quantum/optimize
```

The Digital Twin communicates with this service through:

```text
python/integration/quantum_client.py
```

---

# 22. Opening the Digital Twin

After starting the backend, open the frontend:

```text
ui/index.html
```

For best results, serve the `ui` directory through a local HTTP server rather than opening the HTML file directly.

For example:

```bash
python -m http.server 5500 --directory ui
```

Then open:

```text
http://127.0.0.1:5500
```

---

# 23. Recommended Startup Order

For the complete integrated system, use this order:

### 1. Start Quantum API

```text
Quantum Optimization Service
        ↓
Port 8001
```

### 2. Start Digital Twin backend

```bash
python -m uvicorn python.server:app --host 127.0.0.1 --port 8000
```

### 3. Open the frontend

```text
http://127.0.0.1:5500
```

### 4. Select scenario

```text
Normal Day
       or
Event Day
```

### 5. Start simulation

SUMO is connected through TraCI.

### 6. Run optimization

The workflow becomes:

```text
Digital Twin
     ↓
Quantum API
     ↓
Optimization Result
     ↓
Validation
     ↓
ID Mapping
     ↓
TraCI
     ↓
SUMO
     ↓
Updated Digital Twin
```

---

# 24. Running Tests

Install dependencies first:

```bash
pip install -r requirements.txt
```

Run all tests:

```bash
pytest
```

Run the Quantum–Digital Twin integration test:

```bash
pytest tests/test_quantum_digital_twin_integration.py
```

Run the live SUMO + Quantum integration test:

```bash
pytest tests/test_e2e_sumo_quantum_live.py
```

Run the complete project test runner:

```bash
python run_test_runner.py
```

---

# 25. Important Testing Areas

The test suite covers:

```text
SUMO / TraCI
      ↓
Quantum API
      ↓
Quantum → Digital Twin
      ↓
Digital Twin → SUMO
      ↓
Traffic signal control
      ↓
Routing
      ↓
Constraints
      ↓
Supabase
      ↓
Frontend / WebSocket
```

Important tests include:

```text
test_e2e_sumo_quantum_live.py
test_quantum_digital_twin_integration.py
test_real_quantum_api.py
test_tls_timing.py
test_routing_service.py
test_constraint_engine.py
test_scenario_inputs.py
```

---

# 26. Quick Start

For a quick local run:

```bash
# 1. Create environment
python -m venv .venv

# 2. Activate
.venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Node dependencies
npm install

# 5. Start Digital Twin backend
python -m uvicorn python.server:app --host 127.0.0.1 --port 8000

# 6. In another terminal, serve frontend
python -m http.server 5500 --directory ui

# 7. Open browser
http://127.0.0.1:5500
```

If Quantum optimization is required, start the Quantum API separately on **port 8001** before running an optimization.

---

# 27. Project Technology Stack

| Layer | Technology |
|---|---|
| Traffic Simulation | SUMO |
| Simulation Control | TraCI |
| Backend | Python |
| API | FastAPI / Uvicorn |
| Real-time Communication | WebSocket |
| 3D Visualization | Three.js |
| Frontend | HTML, CSS, JavaScript |
| Optimization | QUBO / QAOA |
| Quantum Communication | HTTP API |
| Database | Supabase / PostgreSQL |
| Testing | Pytest |
| Version Control | Git |

---

# 28. Key Project Concept

The project is **not simply a SUMO visualization** and it is **not only a Quantum optimization system**.

It connects both components:

```text
                 QUANTUM MODULE
                      │
                Optimization
                      │
                      ▼
              Integration Layer
                      │
                 ID Mapping
                      │
                Traffic Actions
                      │
                      ▼
                  TraCI
                      │
                      ▼
              SUMO DIGITAL TWIN
                      │
              Simulation State
                      │
                      ▼
                WebSocket
                      │
                      ▼
               Three.js 3D UI
```

The **SUMO–TraCI module** provides the traffic simulation and digital representation of the Chepauk environment, while the **Quantum module** provides optimization decisions. The `python/integration/` package connects these two systems and converts Quantum decisions into actions that can be applied to the live SUMO simulation.

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
