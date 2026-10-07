import errno
import uvicorn
import webbrowser
import threading
import time
import sys
from pathlib import Path

# Support both `python -m python.main` and the documented
# `python python\main.py` invocation.
if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from python.config import HOST, PORT
    from python.scenario_inputs import RouteValidationError, validate_scenario_routes
    from python.startup_checks import StartupCheckError, ensure_server_port_available, get_port_owners
else:
    from .config import HOST, PORT
    from .scenario_inputs import RouteValidationError, validate_scenario_routes
    from .startup_checks import StartupCheckError, ensure_server_port_available, get_port_owners

def open_browser():
    time.sleep(1.2)
    webbrowser.open(f"http://{HOST}:{PORT}")

def main():
    print("=" * 70)
    print("  SUMO + TraCI Traffic Simulation Digital Twin Engine")
    print(f"  Starting web dashboard at: http://{HOST}:{PORT}")
    print("=" * 70)
    
    # Refuse duplicate launchers before FastAPI startup can create either SUMO
    # process. Reuse this project's existing server, but never stop it here.
    try:
        port_available = ensure_server_port_available(HOST, PORT)
    except StartupCheckError as ex:
        print(f"[{ex.code}] {ex}", file=sys.stderr)
        raise SystemExit(2) from ex
    if not port_available:
        owners = get_port_owners(PORT)
        print(f"[Server] Port {PORT} already in use by an identified Digital Twin server.")
        if owners:
            owner = owners[0]
            print(f"[Server] PID: {owner['pid']} ({owner.get('name') or 'process name unavailable'}).")
        print("[Server] No duplicate server started; the existing process was not stopped.")
        print("[Server] To load current source, use restart_digital_twin.ps1 or Ctrl+C in the original server terminal.")
        webbrowser.open(f"http://{HOST}:{PORT}")
        return

    # Validate both demand scenarios before binding the server or starting SUMO.
    try:
        for scenario in ("normal_day", "event_day"):
            report = validate_scenario_routes(scenario)
            print(f"[RouteValidation] {scenario}: {len(report['errors'])} invalid routes")
    except RouteValidationError as ex:
        print(f"[ROUTE_INVALID] {ex}", file=sys.stderr)
        for error in ex.report.get("errors", []):
            print(f"[RouteValidation] {error.get('route_id')}: {error.get('message')}", file=sys.stderr)
        raise SystemExit(2) from ex

    # Import one FastAPI app and give that object to one Uvicorn listener.
    if __package__ in (None, ""):
        from python.server import app
    else:
        from .server import app

    # Launch browser automatically only after preflight passes.
    threading.Thread(target=open_browser, daemon=True).start()

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="info"))
    app.state.uvicorn_server = server
    print(f"[Server] Starting Digital Twin on {HOST}:{PORT}")
    try:
        server.run()
    except OSError as ex:
        if getattr(ex, "winerror", None) == 10048 or ex.errno == errno.EADDRINUSE:
            try:
                port_available = ensure_server_port_available(HOST, PORT)
            except StartupCheckError as conflict:
                print(f"[{conflict.code}] {conflict}", file=sys.stderr)
            else:
                if not port_available:
                    print(f"[Server] Digital Twin server already running at http://{HOST}:{PORT}; reusing it.")
                    webbrowser.open(f"http://{HOST}:{PORT}")
                    return
                print(f"[SERVER_PORT_IN_USE] Port {HOST}:{PORT} became occupied before Uvicorn bound it", file=sys.stderr)
            raise SystemExit(2) from ex
        raise

if __name__ == "__main__":
    main()
