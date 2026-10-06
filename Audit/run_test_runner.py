"""Local REST/WebSocket smoke runner with orderly SUMO/TraCI shutdown."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import requests
import uvicorn
import websockets

from python.server import app


HOST = "127.0.0.1"
BASE_URL = ""
WS_URL = ""


async def test_websocket_stream() -> None:
    print("Testing WebSocket live streaming...")
    async with websockets.connect(WS_URL, open_timeout=10, close_timeout=5) as ws:
        frames = 0
        deadline = time.monotonic() + 15
        while frames < 5 and time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(raw)
            if data.get("type") == "geometry":
                continue
            if "time" in data:
                frames += 1
                print(
                    f"  [Frame {frames}] SimTime: {data.get('time')}s | "
                    f"Vehicles: {len(data.get('vehicles', []))} | "
                    f"Pedestrians: {len(data.get('pedestrians', []))}"
                )
        assert frames >= 5, "Timed out waiting for live telemetry frames"

        print("  Testing WebSocket scenario switch to event_day...")
        await ws.send(json.dumps({"action": "set_scenario", "scenario": "event_day"}))
        event_frames = 0
        deadline = time.monotonic() + 30
        while event_frames < 2 and time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(raw)
            if data.get("scenario_id") == "event_day" and "time" in data:
                event_frames += 1
                print(
                    f"  [Event Day Frame {event_frames}] SimTime: {data['time']}s | "
                    f"Vehicles: {len(data.get('vehicles', []))}"
                )
        assert event_frames >= 1, "Event Day telemetry was not observed after scenario switch"
        print("  [PASS] WebSocket streaming and scenario control verified")


def main() -> int:
    global BASE_URL, WS_URL
    # Bind an OS-selected free port before starting Uvicorn. A fixed port used
    # to let this smoke test accidentally probe an unrelated running server.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    BASE_URL = f"http://{HOST}:{port}"
    WS_URL = f"ws://{HOST}:{port}/ws/simulation"
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=lambda: server.run(sockets=[listener]),
                                     name="digital-twin-uvicorn", daemon=False)
    server_thread.start()
    started_at = time.monotonic()
    try:
        while time.monotonic() - started_at < 45:
            if not server_thread.is_alive():
                raise RuntimeError("Uvicorn exited before becoming ready")
            try:
                response = requests.get(f"{BASE_URL}/api/system/status", timeout=2)
                if response.ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.25)
        else:
            raise TimeoutError("Digital Twin server did not become ready within 45 seconds")

        print("Testing REST endpoints...")
        geometry = requests.get(f"{BASE_URL}/api/network/geometry", timeout=10)
        geometry.raise_for_status()
        geometry_data = geometry.json()
        assert geometry_data.get("edges"), "Network geometry returned no edges"
        print(f"  [PASS] Geometry endpoint: {len(geometry_data['edges'])} edges")

        comparison = requests.get(f"{BASE_URL}/api/comparison", timeout=10)
        comparison.raise_for_status()
        print("  [PASS] Comparison endpoint verified")

        page = requests.get(f"{BASE_URL}/", timeout=10)
        page.raise_for_status()
        assert "<html" in page.text.lower(), "UI root did not return HTML"
        print("  [PASS] UI static files served successfully")

        asyncio.run(test_websocket_stream())
        return 0
    finally:
        # Let FastAPI's shutdown hook close both SUMO/TraCI controllers.
        server.should_exit = True
        server_thread.join(timeout=30)
        if server_thread.is_alive():
            server.force_exit = True
            server_thread.join(timeout=5)
            raise RuntimeError("Uvicorn did not stop cleanly; inspect SUMO/TraCI cleanup")
        try:
            listener.close()
        except OSError:
            pass
        print("Server shutdown completed through the ASGI lifespan.")


if __name__ == "__main__":
    raise SystemExit(main())
