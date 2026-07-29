"""Session context: what the agent is *supposed* to be doing, and what it just did.

A verdict on a single isolated step cannot detect two of the three failure modes
SentinelMind claims to catch:

- **Infinite loops** exist only across steps. One ``fetch_pricing`` call is healthy;
  the same call three times in a row is the bug. In isolation the third call looks
  exactly like the first.
- **Goal drift** needs a goal. Without knowing what the agent was asked to do,
  "drifted off-task" is not a judgement anyone can make.

So the meta-agent gets a window of recent steps plus the session's stated goal.

Repeat detection is **deterministic**, not left to the model. We fingerprint each
call and count exact recurrences ourselves, then hand the model that count as a
fact. LLM judgement is for the parts that need judgement -- whether the output is
consistent, whether the agent is wandering -- not for counting.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import deque


class SessionContext:
    """Rolling view of one monitored run.

    Args:
        goal: What the agent was asked to accomplish. Drift is measured against
            this; if it is empty the meta-agent is told drift can't be assessed.
        window: How many recent steps to keep. Bounded so a long-running session
            can't grow the prompt without limit -- context cost is per request,
            and a stale step from 200 calls ago is noise, not signal.
    """

    def __init__(self, goal: str = "", window: int = 8) -> None:
        self.goal = goal
        self.window = window
        self._steps: deque[dict] = deque(maxlen=window)
        self._lock = threading.Lock()

    # -- fingerprinting -----------------------------------------------------

    @staticmethod
    def fingerprint(event: dict) -> str:
        """Stable hash of (tool, input). Two calls with the same fingerprint are
        the same call -- which is what makes a repeat a repeat.

        ``sort_keys`` matters: without it, two identical calls whose kwargs
        happened to serialize in a different order would hash differently and the
        loop would go undetected.
        """
        payload = json.dumps(
            {"tool": event.get("tool"), "input": event.get("input")},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def repeat_count(self, event: dict) -> int:
        """How many times this exact call already appears in the window.

        0 means it is new. 2 or more is a strong loop signal -- the same tool with
        byte-identical input, three times, is not a coincidence.
        """
        target = self.fingerprint(event)
        with self._lock:
            return sum(1 for s in self._steps if s["fingerprint"] == target)

    # -- window -------------------------------------------------------------

    def record(self, event: dict, verdict: dict | None = None) -> None:
        """Add a step to the window after it has been judged."""
        with self._lock:
            self._steps.append(
                {
                    "fingerprint": self.fingerprint(event),
                    "tool": event.get("tool", "?"),
                    "duration_ms": event.get("duration_ms", 0),
                    "error": event.get("error"),
                    "status": (verdict or {}).get("status", "?"),
                }
            )

    def recent(self) -> list[dict]:
        with self._lock:
            return list(self._steps)

    def clear(self) -> None:
        with self._lock:
            self._steps.clear()

    # -- prompt rendering ---------------------------------------------------

    def render(self, event: dict) -> str:
        """The context block handed to the meta-agent alongside the step.

        Written as plain statements of fact rather than instructions -- the
        system prompt already says how to judge; this says what is true.
        """
        lines: list[str] = []

        if self.goal:
            lines.append(f"Session goal: {self.goal}")
        else:
            lines.append(
                "Session goal: (not declared -- you cannot assess goal drift for this step)"
            )

        steps = self.recent()
        if steps:
            lines.append(f"\nPreceding {len(steps)} step(s), oldest first:")
            for i, s in enumerate(steps, 1):
                flag = f" ERROR: {s['error']}" if s["error"] else ""
                lines.append(
                    f"  {i}. {s['tool']} ({s['duration_ms']}ms) -> {s['status']}{flag}"
                )
        else:
            lines.append("\nThis is the first step of the session.")

        repeats = self.repeat_count(event)
        if repeats:
            lines.append(
                f"\nRepeat signal: this exact call (same tool, byte-identical input) has "
                f"already occurred {repeats} time(s) in the last {len(steps)} step(s). "
                f"Repeated identical calls with no changing input indicate an infinite loop."
            )
        else:
            lines.append("\nRepeat signal: this exact call has not occurred before in this window.")

        return "\n".join(lines)
