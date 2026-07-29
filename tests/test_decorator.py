"""The decorator must observe without interfering."""

from __future__ import annotations

import time

import pytest

import decorator
from decorator import monitor, subscribe


def test_calls_original_function():
    """Wrapping must not change what the function does or returns."""
    captured = []

    @monitor(tool_name="adder")
    def add(a, b):
        captured.append((a, b))
        return a + b

    assert add(2, 3) == 5
    assert captured == [(2, 3)]


def test_emits_trace_event():
    """Every call produces one event carrying tool, input, and output."""
    events = []
    subscribe(events.append)

    @monitor(tool_name="search_docs")
    def search(query):
        return f"results for {query}"

    search("refund policy")

    assert len(events) == 1
    event = events[0]
    assert event["tool"] == "search_docs"
    assert event["input"]["args"] == ["refund policy"]
    assert event["output"] == "results for refund policy"
    assert event["error"] is None
    assert event["id"].startswith("evt_")


def test_captures_errors_and_reraises():
    """A raising function still emits an event -- and still raises.

    Swallowing the exception would change the monitored agent's behaviour, which
    a monitoring tool must never do.
    """
    events = []
    subscribe(events.append)

    @monitor(tool_name="flaky_tool")
    def boom():
        raise ValueError("upstream timeout")

    with pytest.raises(ValueError, match="upstream timeout"):
        boom()

    assert len(events) == 1
    assert events[0]["error"] == "ValueError: upstream timeout"
    assert events[0]["output"] is None


def test_records_duration():
    """Duration is measured in milliseconds and reflects real elapsed time."""
    events = []
    subscribe(events.append)

    @monitor(tool_name="slow_tool")
    def slow():
        time.sleep(0.05)
        return "done"

    slow()

    assert events[0]["duration_ms"] >= 45
