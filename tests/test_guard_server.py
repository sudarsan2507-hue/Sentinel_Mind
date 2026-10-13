"""Guard mode over HTTP: the check endpoint, blocked steps in the audit log,
approvals, and the halt switch."""

from __future__ import annotations

import pytest

from app import create_app
from guard import Guard
from knowledge_graph import KnowledgeGraph


class CountingJudge:
    """A judge that counts its calls, so tests can prove when it was not used."""

    model = "fake"
    structured_output_mode = "fake"

    def __init__(self, verdict: dict) -> None:
        self.verdict = verdict
        self.calls = 0

    def evaluate(self, event, context=None):
        self.calls += 1
        return dict(self.verdict)


@pytest.fixture
def server(tmp_path):
    judge = CountingJudge({"status": "OK", "explanation": "fine", "confidence": 0.9, "latency_ms": 5})
    guard = Guard(["search_docs", "refund_order", "erase_customer_data"], meta_agent=judge,
                  risky_tools={"refund_order"}, approval_tools={"erase_customer_data"}, max_strikes=3)
    app, _ = create_app(meta_agent=judge, knowledge_graph=KnowledgeGraph(path=tmp_path / "g.json"), guard=guard)
    app.config["TESTING"] = True
    return app, app.test_client(), judge


def _drain(app):
    app.config["WORK_QUEUE"].join()


def test_check_blocks_an_unregistered_tool(server):
    _, client, _ = server
    body = client.post("/guard/check", json={"tool": "internal_api:/v1/refunds/create", "input": {}}).get_json()
    assert body["action"] == "block" and body["rule"] == "unregistered"


def test_check_rejects_a_malformed_call(server):
    _, client, _ = server
    assert client.post("/guard/check", json={"nope": 1}).status_code == 400


def test_a_blocked_step_is_logged_as_blocked_without_a_judge_call(server):
    app, client, judge = server
    event = {
        "id": "evt_b", "tool": "refund_order", "step_type": "tool_call", "input": {},
        "error": "GuardBlocked: out of policy", "duration_ms": 0,
        "guard": {"action": "block", "rule": "judge", "reason": "Blocked: out of policy.",
                  "verdict": {"status": "ANOMALY", "confidence": 0.92}},
    }
    client.post("/trace", json=event)
    _drain(app)

    entry = client.get("/audit").get_json()["entries"][-1]
    assert entry["status"] == "BLOCKED"
    assert entry["verdict"]["rule"] == "judge"
    assert entry["verdict"]["confidence"] == 0.92
    assert judge.calls == 0
    assert client.get("/audit").get_json()["summary"]["counts"]["BLOCKED"] == 1


def test_a_prechecked_step_reuses_its_verdict(server):
    app, client, judge = server
    event = {"id": "evt_p", "tool": "refund_order", "step_type": "tool_call", "input": {}, "error": None,
             "duration_ms": 3, "guard": {"action": "allow", "rule": "judge",
                                         "verdict": {"status": "OK", "explanation": "in window", "confidence": 0.9}}}
    client.post("/trace", json=event)
    _drain(app)
    entry = client.get("/audit").get_json()["entries"][-1]
    assert entry["verdict"]["prechecked"] is True
    assert judge.calls == 0


def test_approval_round_trip(server):
    _, client, _ = server
    pending = client.post("/guard/check", json={"tool": "erase_customer_data", "input": {}}).get_json()
    assert pending["action"] == "pending"
    aid = pending["approval_id"]

    assert client.get(f"/guard/approval/{aid}").get_json()["status"] == "pending"
    assert client.get("/guard/state").get_json()["pending_approvals"][0]["id"] == aid

    assert client.post(f"/guard/approval/{aid}", json={"decision": "maybe"}).status_code == 400
    decided = client.post(f"/guard/approval/{aid}", json={"decision": "deny"}).get_json()
    assert decided["action"] == "block"
    status = client.get(f"/guard/approval/{aid}").get_json()
    assert status["status"] == "denied" and status["decision"]["action"] == "block"
    assert client.post(f"/guard/approval/{aid}", json={"decision": "approve"}).status_code == 409
    assert client.get("/guard/approval/apr_missing").status_code == 404


def test_a_timed_out_approval_says_so(server):
    _, client, _ = server
    aid = client.post("/guard/check", json={"tool": "erase_customer_data", "input": {}}).get_json()["approval_id"]
    body = client.post(f"/guard/approval/{aid}", json={"decision": "deny", "timed_out": True}).get_json()
    assert body["rule"] == "approval_timeout"
    assert "nobody approved erase_customer_data in time" in body["reason"]


def test_strikes_halt_and_clearing_the_session_resets_the_guard(server):
    _, client, _ = server
    for name in ("x1", "x2", "x3"):
        client.post("/guard/check", json={"tool": name, "input": {}})
    state = client.get("/guard/state").get_json()
    assert state["halted"] is True and state["strikes"] == 3
    assert client.post("/guard/check", json={"tool": "search_docs", "input": {}}).get_json()["action"] == "halt"

    client.post("/audit/clear")
    assert client.get("/guard/state").get_json()["halted"] is False


def test_a_new_goal_resets_the_guard_and_reaches_the_preflight(server):
    _, client, _ = server
    client.post("/guard/check", json={"tool": "made_up", "input": {}})
    client.post("/session/goal", json={"goal": "Follow the refund policy"})
    state = client.get("/guard/state").get_json()
    assert state["strikes"] == 0 and state["goal"] == "Follow the refund policy"


def test_events_queued_before_a_clear_are_dropped_not_judged(server):
    """A finished run's backlog must not land in the next run (or cost tokens)."""
    app, client, judge = server
    work = app.config["WORK_QUEUE"]
    # Simulate a backlog: an event stamped with the old run, still queued.
    work.put({"id": "old", "tool": "search_docs", "step_type": "tool_call", "input": {},
              "error": None, "duration_ms": 1, "_epoch": app.config["RUN_EPOCH"] - 1})
    work.join()
    assert judge.calls == 0
    assert client.get("/audit").get_json()["entries"] == []

    client.post("/trace", json={"id": "new", "tool": "search_docs", "step_type": "tool_call",
                                "input": {}, "error": None, "duration_ms": 1})
    work.join()
    assert [e["event"]["id"] for e in client.get("/audit").get_json()["entries"]] == ["new"]
