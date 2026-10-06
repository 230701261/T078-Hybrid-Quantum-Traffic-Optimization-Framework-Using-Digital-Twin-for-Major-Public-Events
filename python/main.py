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
else:
    from .config import HOST, PORT

def open_browser():
    time.sleep(1.2)
    webbrowser.open(f"http://{HOST}:{PORT}")

def main():
    print("=" * 70)
    print("  SUMO + TraCI Traffic Simulation Digital Twin Engine")
    print(f"  Starting web dashboard at: http://{HOST}:{PORT}")
    print("=" * 70)
    
    # Launch browser automatically
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run FastAPI server
    uvicorn.run("python.server:app", host=HOST, port=PORT, log_level="info")

if __name__ == "__main__":
    main()
