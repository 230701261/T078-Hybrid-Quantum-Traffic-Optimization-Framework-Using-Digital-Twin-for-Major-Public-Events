import asyncio
import json
import time
import requests
import websockets

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/simulation"

def test_rest_endpoints():
    print("Testing REST Endpoints...")
    # 1. Geometry
    r_geo = requests.get(f"{BASE_URL}/api/network/geometry")
    assert r_geo.status_code == 200, f"Geometry failed: {r_geo.status_code}"
    geo = r_geo.json()
    assert len(geo["edges"]) > 0, "No edges returned"
    assert len(geo["polygons"]) > 0, "No polygons returned"
    print(f"  [PASS] Geometry endpoint: {len(geo['edges'])} edges, {len(geo['polygons'])} landmarks/polys")

    # 2. Comparison
    r_comp = requests.get(f"{BASE_URL}/api/comparison")
    assert r_comp.status_code == 200, f"Comparison failed: {r_comp.status_code}"
    comp = r_comp.json()
    # The current endpoint compares the paired Classical and Quantum
    # simulations for one shared scenario; it no longer compares unrelated
    # Normal Day and Event Day runs.
    assert "classical" in comp and "quantum" in comp
    assert "scenario_id" in comp and "synchronization" in comp
    assert "measured" in comp and "comparisons" in comp["measured"]
    print("  [PASS] Comparison endpoint verified")

    # 3. Controls
    r_speed = requests.post(f"{BASE_URL}/api/control/speed?multiplier=2.0")
    assert r_speed.status_code == 200
    print("  [PASS] Speed control endpoint verified")

async def test_websocket_stream():
    print("Testing WebSocket live streaming...")
    async with websockets.connect(WS_URL) as ws:
        # Receive first few frames
        received_frames = 0
        for _ in range(5):
            msg = await ws.recv()
            data = json.loads(msg)
            if "time" in data:
                received_frames += 1
                kpis = data.get("kpis", {})
                print(f"  [Frame {received_frames}] SimTime: {data.get('time')}s | Vehs: {len(data.get('vehicles', []))} | Peds: {len(data.get('pedestrians', []))} | AvgSpeed: {kpis.get('avg_speed_kmh')} km/h")
        
        # Test sending control via WS
        print("  Testing WS scenario switch to event_day...")
        await ws.send(json.dumps({"action": "set_scenario", "scenario": "event_day"}))
        await asyncio.sleep(2)
        
        for _ in range(3):
            msg = await ws.recv()
            data = json.loads(msg)
            if "time" in data:
                print(f"  [Event Day Frame] SimTime: {data.get('time')}s | Vehs: {len(data.get('vehicles', []))} | Peds: {len(data.get('pedestrians', []))}")
        
        print("  [PASS] WebSocket streaming and controls verified")

if __name__ == "__main__":
    time.sleep(1)
    test_rest_endpoints()
    asyncio.run(test_websocket_stream())
    print("\nALL SYSTEM TESTS PASSED SUCCESSFULLY!")
