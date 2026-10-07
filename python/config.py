import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
SUMO_DIR = BASE_DIR / "sumo"
UI_DIR = BASE_DIR / "ui"

NET_FILE = str(SUMO_DIR / "network.net.xml")
ADDITIONAL_FILE = str(SUMO_DIR / "additional.add.xml")
NORMAL_CFG = str(SUMO_DIR / "normal_day.sumocfg")
EVENT_CFG = str(SUMO_DIR / "event_day.sumocfg")

# Server config
HOST = "127.0.0.1"
PORT = 8000

# Simulation constants
SIM_STEP_LENGTH = 0.5  # seconds
TARGET_FPS = 30
QUANTUM_HEALTH_TIMEOUT_SECONDS = 1.0

# Configurable Train Timetable and Dwell Durations
TRAIN_INTERVAL_NORMAL = 140.0  # seconds between train arrivals on Normal Day
TRAIN_INTERVAL_EVENT = 90.0    # seconds between train arrivals on Event Day
TRAIN_DWELL_TIME = 35.0        # seconds stopped at Chepauk station platform
TRAIN_PASSENGER_BURST_EVENT = 35  # passengers disembarking per train on Event Day
TRAIN_PASSENGER_BURST_NORMAL = 8  # passengers disembarking per train on Normal Day
