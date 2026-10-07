"""Safe preflight checks for the single local HTTP server."""

from __future__ import annotations

import csv
import io
import json
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any


PROJECT_SERVER_ID = "traffic-digital-twin"


class StartupCheckError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.details = details or {}
        super().__init__(message)


def _project_server_is_running(host: str, port: int) -> bool:
    url = f"http://{host}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=0.8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        payload = None
    if isinstance(payload, dict) and payload.get("service_id") == PROJECT_SERVER_ID:
        return True

    # Existing project processes started before /api/health was introduced
    # still expose the app's stable OpenAPI title and dashboard title. Treat
    # both matching together as the legacy project identity.
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/openapi.json", timeout=0.8) as response:
            openapi = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=0.8) as response:
            dashboard = response.read().decode("utf-8", errors="replace")
        return (openapi.get("info", {}).get("title") ==
                "SUMO TraCI + Quantum Traffic Digital Twin Server" and
                "Chepauk Traffic Digital Twin | Operations Center" in dashboard)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _port_owners(port: int) -> list[dict[str, Any]]:
    """Best-effort Windows listener identification; never terminates a process."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
            timeout=2, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    owners: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
            continue
        if fields[1].rsplit(":", 1)[-1] != str(port):
            continue
        try:
            pid = int(fields[-1])
        except ValueError:
            continue
        owner: dict[str, Any] = {"pid": pid, "name": None, "address": fields[1]}
        try:
            process = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=2, check=False
            )
            rows = list(csv.reader(io.StringIO(process.stdout)))
            if rows and len(rows[0]) > 1 and rows[0][1].isdigit():
                owner["name"] = rows[0][0]
        except (OSError, subprocess.SubprocessError):
            pass
        owners[pid] = owner
    return list(owners.values())


def get_port_owners(port: int) -> list[dict[str, Any]]:
    """Return best-effort listener details for user-facing startup diagnostics."""
    return _port_owners(port)


def ensure_server_port_available(host: str, port: int) -> bool:
    """Return false for the existing app; refuse unrelated listeners safely."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError as exc:
        is_project = _project_server_is_running(host, port)
        owners = _port_owners(port)
        details = {"host": host, "port": port, "project_server": is_project, "owners": owners}
        if is_project:
            return False
        elif owners:
            owner = owners[0]
            message = (f"Port {host}:{port} is already in use by PID {owner['pid']} "
                       f"({owner.get('name') or 'process name unavailable'}); no process was stopped.")
        else:
            message = f"Unable to bind {host}:{port}; listener owner could not be identified."
        raise StartupCheckError("SERVER_PORT_IN_USE", message, details) from exc
    return True
