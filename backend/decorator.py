"""Trace capture for SentinelMind.

Wrap any function in an LLM pipeline with ``@monitor`` and every call emits a
structured trace event to the local event stream. Subscribers (the meta-agent,
the WebSocket server) pick events up from there.

    from decorator import monitor

    @monitor(tool_name="search_docs")
    def search_docs(query: str) -> str:
        ...

Guard mode (``enable_guard(server_url)``) adds a check *before* each call: the
server can allow it, block it (the function never runs and ``GuardBlocked`` is
raised with an instruction for the agent), hold it for a human's approval, or
halt the run (``GuardHalt``). Mark side-effect tools with ``risky=True`` (judged
before they run) or ``approval=True`` (a human decides).
"""

from __future__ import annotations

import functools
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

# Subscribers are plain callables taking one trace event dict. The server
# registers one; tests register a list-appender.
_subscribers: list[Callable[[dict], None]] = []


def subscribe(handler: Callable[[dict], None]) -> Callable[[dict], None]:
    """Register a handler to receive every trace event. Returns the handler."""
    _subscribers.append(handler)
    return handler


def unsubscribe(handler: Callable[[dict], None]) -> None:
    """Remove a previously registered handler. No-op if not registered."""
    if handler in _subscribers:
        _subscribers.remove(handler)


def clear_subscribers() -> None:
    """Drop all handlers. Used between tests."""
    _subscribers.clear()


def emit(event: dict) -> None:
    """Push an event to every subscriber.

    A broken subscriber must never take down the monitored agent -- that would
    make the observability tool the outage. Failures are swallowed per handler.
    """
    for handler in list(_subscribers):
        try:
            handler(event)
        except Exception:
            pass


class GuardBlocked(Exception):
    """The guard stopped this call before it ran. ``str(exc)`` is the
    instruction for the agent -- feed it back as the tool's result."""

    def __init__(self, reason: str, rule: str = "") -> None:
        super().__init__(reason)
        self.rule = rule


class GuardHalt(GuardBlocked):
    """The guard stopped the whole run. The agent loop should end."""


_guard: dict = {"url": None, "approval_timeout": 60.0, "poll": 1.0}


def enable_guard(server_url: str, approval_timeout: float = 60.0, poll: float = 1.0) -> None:
    """Ask ``server_url`` before every monitored call from now on."""
    _guard.update(url=server_url.rstrip("/"), approval_timeout=approval_timeout, poll=poll)


def disable_guard() -> None:
    _guard["url"] = None


def guard_enabled() -> bool:
    return bool(_guard["url"])


def _post(path: str, body: dict, timeout: float = 30.0) -> dict | None:
    req = urllib.request.Request(
        _guard["url"] + path, data=json.dumps(body, default=str).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _get(path: str, timeout: float = 10.0) -> dict | None:
    try:
        with urllib.request.urlopen(_guard["url"] + path, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _ask_guard(call: dict, risky: bool, approval: bool) -> dict:
    """The server's decision for ``call``. Waits out a pending approval.

    If the server cannot be reached, ordinary tools run anyway -- monitoring
    must not become the outage -- but risky and approval tools do not: an
    unverified irreversible action is exactly what guard mode exists to stop.
    """
    decision = _post("/guard/check", {**call, "risky": risky, "approval": approval})
    if decision is None:
        if risky or approval:
            return {"action": "block", "rule": "unreachable",
                    "reason": "Blocked: SentinelMind could not be reached to check this action, "
                              "and it has side effects. Do not retry it; tell the user a human "
                              "will review the request."}
        return {"action": "allow", "rule": "unreachable"}

    if decision.get("action") != "pending":
        return decision

    approval_id = decision.get("approval_id")
    deadline = time.monotonic() + _guard["approval_timeout"]
    while time.monotonic() < deadline:
        status = (_get(f"/guard/approval/{approval_id}") or {}).get("status")
        if status == "approved":
            return {"action": "allow", "rule": "approval", "approval_id": approval_id}
        if status == "denied":
            return (_get(f"/guard/approval/{approval_id}") or {}).get("decision") or {
                "action": "block", "rule": "approval_denied",
                "reason": "Blocked by SentinelMind: a human reviewer did not approve this action."}
        time.sleep(_guard["poll"])
    # Nobody answered: deny. An unattended run must not default to "yes".
    return _post(f"/guard/approval/{approval_id}", {"decision": "deny", "timed_out": True}) or {
        "action": "block", "rule": "approval_timeout",
        "reason": "Blocked by SentinelMind: no human approved this action in time. Do not retry it."}


def _describe(value: Any, limit: int = 500) -> Any:
    """Make a value safe to put in a JSON event.

    Long strings are truncated and unserializable objects fall back to repr, so
    the trace never fails on an exotic return type.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[truncated]"
    if isinstance(value, (list, tuple)):
        return [_describe(v, limit) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k): _describe(v, limit) for k, v in list(value.items())[:20]}
    return _describe(repr(value), limit)


def monitor(
    tool_name: str | None = None,
    step_type: str = "tool_call",
    risky: bool = False,
    approval: bool = False,
) -> Callable:
    """Decorator that emits a trace event for each call of the wrapped function.

    Args:
        tool_name: Name reported in the trace. Defaults to the function name.
        step_type: One of ``tool_call``, ``model_call``, ``memory_read``.
        risky: Has side effects; in guard mode it is judged before it runs.
        approval: In guard mode, a human must approve each call.

    The wrapped function's return value and exceptions pass through untouched --
    monitoring observes, it never changes behaviour. If the function raises, the
    event is emitted with ``error`` populated and the exception re-raised.
    """

    def decorator(func: Callable) -> Callable:
        name = tool_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            event = {
                "id": f"evt_{uuid.uuid4().hex[:12]}",
                "tool": name,
                "step_type": step_type,
                "input": {
                    "args": _describe(list(args)),
                    "kwargs": _describe(kwargs),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "output": None,
                "error": None,
                "duration_ms": 0.0,
            }

            if _guard["url"]:
                decision = _ask_guard(
                    {"tool": name, "step_type": step_type, "input": event["input"]},
                    risky, approval,
                )
                event["guard"] = {k: decision[k] for k in ("action", "rule", "reason", "verdict", "approval_id") if k in decision}
                if decision.get("action") in ("block", "halt"):
                    # Never ran. Reported so the dashboard and the failure memory see
                    # the attempt, then raised so the agent gets the instruction back.
                    reason = decision.get("reason", "Blocked by SentinelMind.")
                    exc_type = GuardHalt if decision["action"] == "halt" or decision.get("halted") else GuardBlocked
                    event["error"] = f"{exc_type.__name__}: {reason}"
                    emit(event)
                    raise exc_type(reason, decision.get("rule", ""))

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                event["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
                event["error"] = f"{type(exc).__name__}: {exc}"
                emit(event)
                raise

            event["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            event["output"] = _describe(result)
            emit(event)
            return result

        return wrapper

    return decorator
