"""Session context is what makes loop and drift detection possible at all."""

from __future__ import annotations

from session_context import SessionContext


def _call(tool: str, args: list, eid: str = "evt_x") -> dict:
    return {
        "id": eid,
        "tool": tool,
        "input": {"args": args, "kwargs": {}},
        "duration_ms": 60.0,
        "error": None,
    }


def test_counts_identical_repeats_and_ignores_different_calls():
    """The loop signal must be deterministic -- we count, the model doesn't."""
    ctx = SessionContext(goal="answer a refund question")
    call = _call("fetch_pricing", ["SKU-9000"])

    assert ctx.repeat_count(call) == 0

    ctx.record(call, {"status": "OK"})
    ctx.record(call, {"status": "WARN"})
    assert ctx.repeat_count(call) == 2

    # A different input is a different call, not a repeat.
    assert ctx.repeat_count(_call("fetch_pricing", ["SKU-0001"])) == 0
    # Same input, different tool, likewise.
    assert ctx.repeat_count(_call("search_docs", ["SKU-9000"])) == 0


def test_fingerprint_is_stable_across_key_order():
    """Two identical calls whose kwargs serialize in a different order must hash
    the same, or the loop goes undetected."""
    a = {"tool": "t", "input": {"kwargs": {"x": 1, "y": 2}, "args": []}}
    b = {"tool": "t", "input": {"args": [], "kwargs": {"y": 2, "x": 1}}}

    assert SessionContext.fingerprint(a) == SessionContext.fingerprint(b)


def test_window_is_bounded():
    """A long run must not grow the prompt without limit."""
    ctx = SessionContext(window=3)
    for i in range(10):
        ctx.record(_call("tool_a", [i]), {"status": "OK"})

    assert len(ctx.recent()) == 3
    # Oldest dropped: the first call is no longer counted as a repeat.
    assert ctx.repeat_count(_call("tool_a", [0])) == 0


def test_render_carries_goal_repeats_and_history():
    """The prompt block must state the goal, the run so far, and the repeat count."""
    ctx = SessionContext(goal="answer a refund question")
    call = _call("fetch_pricing", ["SKU-9000"])
    ctx.record(_call("search_docs", ["refund policy"]), {"status": "OK"})
    ctx.record(call, {"status": "OK"})

    rendered = ctx.render(call)

    assert "answer a refund question" in rendered
    assert "search_docs" in rendered
    assert "occurred 1 time(s)" in rendered


def test_render_says_drift_is_unassessable_without_a_goal():
    """Never let the model invent a goal to measure drift against."""
    rendered = SessionContext().render(_call("search_docs", ["x"]))

    assert "not declared" in rendered
    assert "first step" in rendered
