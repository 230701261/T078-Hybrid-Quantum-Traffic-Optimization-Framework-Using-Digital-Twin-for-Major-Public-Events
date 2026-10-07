# Quantum Traffic Optimization Module

This folder contains the Quantum Optimization API and solver source bundled with the Chepauk Traffic Digital Twin repository.

## Run with the Digital Twin

Install the module requirements into the same Python environment used for the Digital Twin. This is required for both the API and the Digital Twin's in-process Classical fallback.

From the repository root:

```powershell
python -m pip install -r quantum_module\Quantum-main\requirements.txt
```

Start the Quantum API in its own terminal, from the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
Set-Location quantum_module\Quantum-main
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

Check the service:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

The Digital Twin API is a separate process on port 8000. Its Quantum client uses port 8001 by default and prefers this bundled module for local Classical fallback. Configure `QUANTUM_SERVICE_URL` if the Quantum API is hosted at another URL.

The service writes solver, plan and export artifacts under `results/` at runtime. These are generated outputs and are intentionally not versioned. The API caches the latest optimization result in memory; that cache is cleared when the Quantum API process restarts.

The Quantum API returns optimization plans. The Digital Twin integration is responsible for mapping, validating and applying compatible actions to live SUMO/TraCI state; a solver response alone is not proof that SUMO was changed.
