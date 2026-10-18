"""Connecting an agent: registering its tools on the server, and sentinel.connect()."""

from __future__ import annotations

import pytest

import decorator
import sentinel
from app import create_app
from guard import Guard
from knowledge_graph import KnowledgeGraph


class Judge:
    model = "fake"
    structured_output_mode = "fake"

    def __init__(self) -> None:
        self.known_tools = ["search_docs"]

    def evaluate(self, event, context=None):
        return {"status": "OK", "explanation": "fine", "confidence": 0.9, "latency_ms": 1}


@pytest.fixture
def server(tmp_path):
    judge = Judge()
    guard = Guard(["search_docs"], meta_agent=judge, risky_tools={"refund_order"})
    app, _ = create_app(meta_agent=judge, knowledge_graph=KnowledgeGraph(path=tmp_path / "g.json"), guard=guard)
    app.config["TESTING"] = True
    return app, app.test_client(), judge, guard


def test_a_registered_tool_is_no_longer_blocked_as_invented(server):
    _, client, judge, _ = server
    assert client.post("/guard/check", json={"tool": "book_flight", "input": {}}).get_json()["rule"] == "unregistered"

    resp = client.post("/session/tools", json={"tools": ["book_flight"]})

    assert resp.status_code == 200 and resp.get_json()["added"] == ["book_flight"]
    assert client.post("/guard/check", json={"tool": "book_flight", "input": {}}).get_json()["action"] == "allow"
    assert "book_flight" in judge.known_tools
    assert "book_flight" in client.get("/session").get_json()["tools"]


def test_registering_marks_risky_and_approval_tools(server):
    _, client, _, guard = server
    client.post("/session/tools", json={"tools": ["cancel_booking"], "risky": ["charge_card"],
                                        "approval": ["delete_account"]})
    assert {"charge_card", "cancel_booking", "delete_account"} <= guard.known_tools
    assert "charge_card" in guard.risky_tools and "delete_account" in guard.approval_tools


def test_registering_can_never_unmark_a_risky_tool(server):
    _, client, _, guard = server
    body = client.post("/session/tools", json={"tools": ["refund_order"], "risky": []}).get_json()
    assert "refund_order" in body["risky"] and "refund_order" in guard.risky_tools


@pytest.mark.parametrize("payload", [
    {"tools": "book_flight"},
    {"tools": [1, 2]},
    {"tools": ["has space"]},
    {"tools": ["x" * 81]},
    {"risky": ["rm -rf /"]},
])
def test_bad_tool_lists_are_refused(server, payload):
    _, client, _, guard = server
    assert client.post("/session/tools", json=payload).status_code == 400
    assert guard.known_tools == {"search_docs"}


def test_the_registry_is_capped(server):
    app, client, _, _ = server
    too_many = [f"tool_{i}" for i in range(400)]
    assert client.post("/session/tools", json={"tools": too_many}).status_code == 400
    assert "tool_0" not in app.config["TOOLS"]


@pytest.fixture
def connected(server, monkeypatch):
    """sentinel.connect() talking to the test server instead of the network."""
    app, client, judge, guard = server

    def fake_request(base, path, body=None, timeout=5.0):
        resp = client.get(path) if body is None else client.post(path, json=body)
        if resp.status_code >= 400:
            raise sentinel.SentinelUnavailable(resp.get_json().get("error", "refused"))
        return resp.get_json()

    monkeypatch.setattr(sentinel, "_request", fake_request)
    yield app, client, guard
    sentinel.disconnect()


def test_connect_registers_decorated_tools_with_their_flags(connected):
    app, client, guard = connected

    @decorator.monitor(tool_name="lookup_booking")
    def lookup(ref):
        return {"ref": ref}

    @decorator.monitor(tool_name="charge_card", risky=True)
    def charge(amount):
        return "charged"

    @decorator.monitor(tool_name="delete_account", approval=True)
    def delete(user):
        return "deleted"

    sentinel.connect("http://test", goal="Rebook the customer's cancelled flight",
                     tools=[lookup, charge, delete, "send_email"])

    assert {"lookup_booking", "charge_card", "delete_account", "send_email"} <= guard.known_tools
    assert "charge_card" in guard.risky_tools and "delete_account" in guard.approval_tools
    assert client.get("/session").get_json()["goal"] == "Rebook the customer's cancelled flight"


def test_connect_sends_every_monitored_step(connected):
    app, client, _ = connected

    @decorator.monitor(tool_name="lookup_booking")
    def lookup(ref):
        return {"ref": ref}

    sentinel.connect("http://test", tools=[lookup])
    lookup("AB12")
    app.config["WORK_QUEUE"].join()

    entries = client.get("/audit").get_json()["entries"]
    assert [e["event"]["tool"] for e in entries] == ["lookup_booking"]


def test_connecting_twice_does_not_send_steps_twice(connected):
    app, client, _ = connected

    @decorator.monitor(tool_name="lookup_booking")
    def lookup(ref):
        return ref

    sentinel.connect("http://test", tools=[lookup])
    sentinel.connect("http://test", tools=[lookup])
    lookup("AB12")
    app.config["WORK_QUEUE"].join()

    assert client.get("/audit").get_json()["summary"]["total"] == 1


def test_connect_with_guard_turns_guard_mode_on(connected):
    sentinel.connect("http://test", guard=True)
    assert decorator.guard_enabled()
    sentinel.disconnect()
    assert not decorator.guard_enabled()


def test_connect_rejects_something_that_is_not_a_tool(connected):
    with pytest.raises(TypeError):
        sentinel.connect("http://test", tools=[lambda: None])


def test_connect_fails_loudly_when_the_server_is_down():
    with pytest.raises(sentinel.SentinelUnavailable, match="not reachable"):
        sentinel.connect("http://127.0.0.1:9", goal="anything")
