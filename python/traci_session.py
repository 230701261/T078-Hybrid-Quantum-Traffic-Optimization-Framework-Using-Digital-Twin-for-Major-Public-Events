"""Shared lock for serializing labeled TraCI calls across worker threads."""

import threading

TRACI_SESSION_LOCK = threading.RLock()
