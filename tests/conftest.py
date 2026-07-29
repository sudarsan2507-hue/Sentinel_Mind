"""Shared test fixtures.

Puts ``backend/`` on the import path so tests import the modules the same way
``app.py`` does, and provides a fake Anthropic client so the suite runs offline
with no API key and no network latency.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str | None, finish_reason: str = "stop") -> None:
        self.message = FakeMessage(content)
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, text: str | None, finish_reason: str = "stop") -> None:
        self.choices = [FakeChoice(text, finish_reason)]


class FakeCompletions:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


class FakeGroq:
    """Stands in for the OpenAI-compatible Groq client -- canned verdict."""

    def __init__(self, verdict: dict | None = None, *, raw=None, error=None,
                 finish_reason: str = "stop") -> None:
        if error is not None:
            completions = FakeCompletions(error=error)
        else:
            text = raw if raw is not None else json.dumps(verdict or {})
            completions = FakeCompletions(response=FakeResponse(text, finish_reason))
        self.chat = FakeChat(completions)
        self.completions = completions  # convenience handle for assertions


@pytest.fixture
def sample_event() -> dict:
    return {
        "id": "evt_test000001",
        "tool": "search_docs",
        "step_type": "tool_call",
        "input": {"args": ["refund policy"], "kwargs": {}},
        "output": "Refunds are accepted within 30 days.",
        "error": None,
        "timestamp": "2026-07-29T12:00:00+00:00",
        "duration_ms": 41.7,
    }


@pytest.fixture(autouse=True)
def _clean_subscribers():
    """Trace subscribers are module-level state; reset around every test."""
    import decorator

    decorator.clear_subscribers()
    yield
    decorator.clear_subscribers()
