"""Structured audit log for SentinelMind.

Every verdict the meta-agent produces is recorded here alongside the trace event
that triggered it. This is the "structured audit log of every decision made up to
that point" that gets surfaced when an ANOMALY fires.

In-memory by default so the demo runs on a laptop with no database. ``export()``
gives you a JSON string suitable for writing to disk.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone


class AuditLog:
    """Thread-safe, append-only record of trace events and their verdicts.

    Thread-safe because the Flask request thread reads it while the meta-agent
    worker thread writes to it.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: list[dict] = []
        self._lock = threading.Lock()
        self.max_entries = max_entries

    def record(self, event: dict, verdict: dict) -> dict:
        """Append one event/verdict pair. Returns the stored entry."""
        entry = {
            "sequence": len(self._entries),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "verdict": verdict,
            "status": verdict.get("status", "WARN"),
        }
        with self._lock:
            self._entries.append(entry)
            # Bound memory on a long-running session; drop oldest first.
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[-self.max_entries :]
        return entry

    def all(self) -> list[dict]:
        """Every entry, oldest first."""
        with self._lock:
            return list(self._entries)

    def filter(self, status: str) -> list[dict]:
        """Entries whose verdict status matches (case-insensitive)."""
        target = status.upper()
        with self._lock:
            return [e for e in self._entries if e["status"].upper() == target]

    def anomalies(self) -> list[dict]:
        """Just the ANOMALY entries -- what a developer actually opens first."""
        return self.filter("ANOMALY")

    def summary(self) -> dict:
        """Counts per status, for the dashboard header."""
        with self._lock:
            entries = list(self._entries)
        counts = {"OK": 0, "WARN": 0, "ANOMALY": 0}
        for entry in entries:
            status = entry["status"].upper()
            counts[status] = counts.get(status, 0) + 1
        return {"total": len(entries), "counts": counts}

    def export(self) -> str:
        """Serialize the whole log to a JSON string."""
        return json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "summary": self.summary(),
                "entries": self.all(),
            },
            indent=2,
            default=str,
        )

    def clear(self) -> None:
        """Drop every entry."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# Shared instance used by the server. Tests construct their own.
audit_log = AuditLog()
