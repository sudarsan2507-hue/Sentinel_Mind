"""Connect an agent to SentinelMind in one call.

    import sentinel
    from decorator import monitor

    @monitor(tool_name="get_order")
    def get_order(order_id): ...

    @monitor(tool_name="refund_order", risky=True)
    def refund_order(order_id, amount): ...

    sentinel.connect("http://127.0.0.1:5000",
                     goal="Resolve the customer's refund complaint",
                     tools=[get_order, refund_order],
                     guard=True)

``connect`` checks the server is up, registers the tools (so they are not taken
for invented ones), declares the goal, and starts sending every monitored step.
Tools can be the decorated functions themselves -- their names and risky /
approval flags are read from ``@monitor`` -- or plain names.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Iterable

import decorator

_sender: Callable[[dict], None] | None = None


class SentinelUnavailable(ConnectionError):
    """The SentinelMind server could not be reached or refused the request."""


def _request(server: str, path: str, body: dict | None = None, timeout: float = 5.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{server}{path}", data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise SentinelUnavailable(f"SentinelMind refused {path}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SentinelUnavailable(
            f"SentinelMind is not reachable at {server} ({exc}). Start it with: python backend/app.py"
        ) from exc


def _split(tools: Iterable[Any]) -> tuple[list[str], list[str], list[str]]:
    names, risky, approval = [], [], []
    for tool in tools:
        name = tool if isinstance(tool, str) else getattr(tool, "sentinel_tool", None)
        if not name:
            raise TypeError(f"{tool!r} is neither a tool name nor a function wrapped with @monitor")
        names.append(name)
        if getattr(tool, "sentinel_risky", False):
            risky.append(name)
        if getattr(tool, "sentinel_approval", False):
            approval.append(name)
    return names, risky, approval


def connect(
    server: str = "http://127.0.0.1:5000",
    goal: str | None = None,
    tools: Iterable[Any] = (),
    guard: bool = False,
    approval_timeout: float = 60.0,
) -> dict:
    """Point every ``@monitor``-ed function at ``server``. Safe to call again.

    Args:
        server: The SentinelMind server URL.
        goal: What the agent is supposed to achieve. Starts a new run; without
            one the judge cannot tell when the agent drifts.
        tools: The agent's tools -- decorated functions or names.
        guard: Ask the server before each tool runs, so bad steps are stopped
            rather than only reported.
        approval_timeout: Seconds a tool that needs approval waits for a human.

    Returns what the server registered. Raises ``SentinelUnavailable`` if the
    server is down -- a misconfigured monitor should fail loudly at start-up,
    not silently watch nothing.
    """
    global _sender
    server = server.rstrip("/")
    _request(server, "/health")

    registered: dict = {}
    names, risky, approval = _split(tools)
    if names:
        registered = _request(server, "/session/tools",
                              {"tools": names, "risky": risky, "approval": approval})
    if goal:
        _request(server, "/session/goal", {"goal": goal})

    if _sender is not None:
        decorator.unsubscribe(_sender)
    warned = []

    def send(event: dict) -> None:
        try:
            _request(server, "/trace", event)
        except SentinelUnavailable as exc:
            # Monitoring must never break the agent; say so once, not every step.
            if not warned:
                warned.append(True)
                print(f"SentinelMind: {exc}", file=sys.stderr)

    _sender = decorator.subscribe(send)

    if guard:
        decorator.enable_guard(server, approval_timeout=approval_timeout)
    else:
        decorator.disable_guard()
    return registered


def disconnect() -> None:
    """Stop sending steps and turn guard mode off."""
    global _sender
    if _sender is not None:
        decorator.unsubscribe(_sender)
        _sender = None
    decorator.disable_guard()
