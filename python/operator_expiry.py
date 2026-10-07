"""Backend-owned expiry scheduling for temporary operator constraints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class OperatorExpiryManager:
    def __init__(self, on_expire: Callable[[str, dict[str, Any]], Awaitable[None]]):
        self._on_expire = on_expire
        self._records: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    def _now(self) -> float:
        import time
        return time.monotonic()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def activate(self, key: str, duration_seconds: float, original_state: dict[str, Any],
                 metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = self._now()
        started_at = datetime.now(timezone.utc).isoformat()
        record = {"key": key, "status": "ACTIVE", "duration_seconds": float(duration_seconds),
                  "expires_monotonic": now + float(duration_seconds),
                  "started_at": started_at, "activated_at": started_at,
                  "expires_at": datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + duration_seconds,
                                                        timezone.utc).isoformat(),
                  "original_state": original_state}
        record.update(metadata or {})
        self._records[key] = record
        self.start()
        self._wake.set()
        return self.public_record(key)

    def cancel(self, key: str) -> None:
        self._records.pop(key, None)
        self._wake.set()

    def finish(self, key: str, status: str) -> None:
        record = self._records.get(key)
        if record:
            record["status"] = status
            record.pop("expires_monotonic", None)
            self._wake.set()

    def public_record(self, key: str) -> dict[str, Any] | None:
        record = self._records.get(key)
        if not record:
            return None
        remaining = max(0, round(record.get("expires_monotonic", self._now()) - self._now(), 1))
        return {k: v for k, v in record.items() if k not in {"expires_monotonic", "original_state"}} | {
            "remaining_seconds": remaining}

    def original_state(self, key: str) -> dict[str, Any] | None:
        record = self._records.get(key)
        return record.get("original_state") if record else None

    def remaining_seconds(self, key: str) -> float | None:
        record = self._records.get(key)
        if not record or record.get("status") != "ACTIVE":
            return None
        return max(0.0, record["expires_monotonic"] - self._now())

    def snapshot(self) -> dict[str, Any]:
        return {key: self.public_record(key) for key in tuple(self._records)}

    async def _run(self) -> None:
        while True:
            now = self._now()
            expired = [key for key, record in self._records.items()
                       if record.get("status") == "ACTIVE" and record.get("expires_monotonic", float("inf")) <= now]
            for key in expired:
                record = self._records.get(key)
                if record is None:
                    continue
                try:
                    await self._on_expire(key, record["original_state"])
                    record["status"] = "EXPIRED"
                    record.pop("expires_monotonic", None)
                except Exception as exc:
                    record["status"] = "RESTORATION_ERROR"
                    record["error"] = str(exc)
                    record.pop("expires_monotonic", None)
                    self._records[key] = record
            waits = [max(0.05, record["expires_monotonic"] - self._now())
                     for record in self._records.values() if record.get("status") == "ACTIVE"]
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=min(waits, default=60.0))
            except asyncio.TimeoutError:
                pass
