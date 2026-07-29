"""Trace capture for SentinelMind.

Wrap any function in an LLM pipeline with ``@monitor`` and every call emits a
structured trace event to the local event stream. Subscribers (the meta-agent,
the WebSocket server) pick events up from there.

    from decorator import monitor

    @monitor(tool_name="search_docs")
    def search_docs(query: str) -> str:
        ...
"""

from __future__ import annotations

import functools
import time
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
) -> Callable:
    """Decorator that emits a trace event for each call of the wrapped function.

    Args:
        tool_name: Name reported in the trace. Defaults to the function name.
        step_type: One of ``tool_call``, ``model_call``, ``memory_read``.

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
