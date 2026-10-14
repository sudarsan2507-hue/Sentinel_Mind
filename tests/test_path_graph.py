"""The right path: knowing which move is correct, steering toward it, and
growing the path from moves a human approved."""

from __future__ import annotations

import pytest

import decorator
import real_agent
from app import create_app
from guard import ALLOW, BLOCK, HALT, PENDING, Guard
from knowledge_graph import KnowledgeGraph
from path_graph import (
    DONE_ALREADY, FORBIDDEN, KNOWN_WRONG, OFF_PATH, ON_PATH, PREMATURE,
    PathGraph, PathTracker, choose_path,
)

GOAL = "Resolve the refund complaint for order ord_5512 according to policy"
KNOWN = ["search_docs", "get_order", "lookup_customer", "refund_order", "erase_customer_data",
         "email_customer", "call_internal_api", "agent_llm_call", "internal_api:/v1/orders/list"]


def _ran(tool, output=None, **kwargs):
    return {"tool": tool, "step_type": "tool_call", "input": {"args": [], "kwargs": kwargs},
            "output": output, "error": None}


def _tracker(days: int | None = None, policy: bool = False) -> PathTracker:
    tracker = PathTracker(choose_path(GOAL))
    if days is not None:
        tracker.observe(_ran("get_order", {"id": "ord_5512", "days_since_purchase": days}, order_id="ord_5512"))
    if policy:
        tracker.observe(_ran("search_docs", "Refunds within 30 days.", query="refund"))
    return tracker


# -- the path itself ---------------------------------------------------------

def test_the_refund_path_is_chosen_by_the_goal():
    assert choose_path(GOAL).id == "support_refund"
    assert choose_path("Summarise this week's tickets") is None


def test_a_refund_before_reading_the_order_and_policy_is_premature():
    finding = _tracker().classify("refund_order")
    assert finding["kind"] == PREMATURE
    assert "look up the order" in finding["why"] and "read the refund policy" in finding["why"]


def test_an_out_of_window_refund_is_forbidden_by_arithmetic_not_opinion():
    finding = _tracker(days=58, policy=True).classify("refund_order")
    assert finding["kind"] == FORBIDDEN
    assert "58 days old" in finding["why"]


def test_an_in_window_refund_is_on_the_path():
    assert _tracker(days=10, policy=True).classify("refund_order")["kind"] == ON_PATH


def test_reading_the_policy_a_third_time_is_circling():
    tracker = _tracker(policy=True)
    tracker.observe(_ran("search_docs", "same", query="refund exceptions"))
    finding = tracker.classify("search_docs")
    assert finding["kind"] == DONE_ALREADY
    assert "already read the policy" in finding["why"]


def test_reordering_harmless_steps_stays_on_the_path():
    tracker = _tracker(policy=True)  # policy first, order second
    assert tracker.classify("get_order")["kind"] == ON_PATH


def test_a_tool_the_path_does_not_mention_is_off_path_not_wrong():
    assert _tracker().classify("internal_api:/v1/orders/list")["kind"] == OFF_PATH


def test_next_steps_and_finish_follow_the_facts():
    tracker = _tracker()
    assert [n["id"] for n in tracker.next_steps()] == ["get_order", "check_policy"]

    tracker = _tracker(days=58, policy=True)
    assert [n["id"] for n in tracker.next_steps()] == ["tell_customer"]  # refund ruled out
    assert "email_customer" in tracker.allowed_tools()
    assert "refund_order" not in tracker.allowed_tools()

    tracker.observe(_ran("email_customer", "Email sent.", customer_id="c", message="m"))
    assert tracker.finished()
    assert tracker.allowed_tools() == []  # nothing left but to answer


def test_a_failed_step_does_not_count_as_done():
    tracker = PathTracker(choose_path(GOAL))
    tracker.observe({**_ran("get_order", None), "error": "TimeoutError"})
    assert tracker.visits["get_order"] == 0
    assert tracker.route[-1]["kind"] == "failed"


def test_the_instruction_names_what_is_wrong_and_what_to_do_next():
    tracker = _tracker(days=58, policy=True)
    text = tracker.instruction(tracker.classify("refund_order"))
    assert "58 days old" in text
    assert "tell the customer the outcome" in text


# -- the guard, steering -------------------------------------------------------

def _guard(tmp_path, memory=None) -> Guard:
    g = Guard(KNOWN, meta_agent=None, risky_tools=set(), approval_tools=set(), memory=memory,
              learned_store=tmp_path / "learned.json")
    g.reset(GOAL)
    return g


def _call(tool, **kwargs):
    return {"tool": tool, "step_type": "tool_call", "input": {"args": [], "kwargs": kwargs}}


def test_off_path_moves_are_held_for_the_user_until_automate(tmp_path):
    g = _guard(tmp_path)
    held = g.check(_call("refund_order", order_id="ord_5512", amount_usd=149))
    assert held["action"] == PENDING and held["kind"] == "deviation"
    assert g.state()["pending_approvals"][0]["finding"]["kind"] == PREMATURE

    steer = g.decide_deviation(held["approval_id"], "automate")
    assert steer["action"] == BLOCK and steer["rule"] == "path"
    assert "SentinelMind kept you on the correct path" in steer["reason"]
    assert g.path.automate is True
    # From now on it steers without asking.
    assert g.check(_call("refund_order", order_id="ord_5512", amount_usd=150))["action"] == BLOCK
    assert g.strikes == 0  # steering a premature step is not a strike


def test_steering_a_forbidden_move_is_a_strike(tmp_path):
    g = _guard(tmp_path)
    g.set_automate(True)
    g.observe(_ran("get_order", {"days_since_purchase": 58}, order_id="ord_5512"))
    g.observe(_ran("search_docs", "policy", query="refund"))
    decision = g.check(_call("refund_order", order_id="ord_5512", amount_usd=149))
    assert decision["action"] == BLOCK and "58 days old" in decision["reason"]
    assert g.strikes == 1


def test_on_path_moves_pass_straight_through(tmp_path):
    g = _guard(tmp_path)
    assert g.check(_call("get_order", order_id="ord_5512"))["action"] == ALLOW


def test_let_it_continue_allows_the_move_and_proposes_it_as_a_path_step(tmp_path):
    g = _guard(tmp_path)
    g.observe(_ran("lookup_customer", {}, customer_id="c"))
    g.observe(_ran("lookup_customer", {}, customer_id="c"))  # max_visits 1: next one is circling
    held = g.check(_call("lookup_customer", customer_id="c2"))
    assert held["action"] == PENDING
    assert g.decide_deviation(held["approval_id"], "continue")["action"] == ALLOW
    proposals = g.list_proposals()
    assert proposals and proposals[0]["tool"] == "lookup_customer"


def test_an_accepted_proposal_becomes_part_of_the_path(tmp_path):
    g = _guard(tmp_path)
    g._propose(_call("internal_api:/v1/orders/list"))
    prop = g.list_proposals()[0]
    g.resolve_proposal(prop["id"], accept=True)
    assert g.path.classify("internal_api:/v1/orders/list")["kind"] == ON_PATH
    # Persisted: a fresh guard on the same store knows it too.
    again = Guard(KNOWN, learned_store=tmp_path / "learned.json")
    again.reset(GOAL)
    assert again.path.classify("internal_api:/v1/orders/list")["kind"] == ON_PATH
    assert g.resolve_proposal(prop["id"], accept=True) is None  # already resolved


def test_a_forbidden_move_is_never_proposed(tmp_path):
    g = _guard(tmp_path)
    g.observe(_ran("get_order", {"days_since_purchase": 58}, order_id="o"))
    g.observe(_ran("search_docs", "p", query="refund"))
    held = g.check(_call("refund_order", order_id="o", amount_usd=149))
    g.decide_deviation(held["approval_id"], "continue")
    assert g.list_proposals() == []


def test_stop_halts_the_run(tmp_path):
    g = _guard(tmp_path)
    held = g.check(_call("refund_order", order_id="o", amount_usd=1))
    assert g.decide_deviation(held["approval_id"], "stop")["action"] == HALT
    assert g.check(_call("get_order", order_id="o"))["action"] == HALT


def test_an_unanswered_path_question_steers_by_default(tmp_path):
    g = _guard(tmp_path)
    held = g.check(_call("refund_order", order_id="o", amount_usd=1))
    assert g.expire(held["approval_id"])["action"] == BLOCK
    assert g.path.automate is True


def test_a_move_the_failure_memory_has_seen_fail_is_known_wrong(tmp_path):
    kg = KnowledgeGraph(path=tmp_path / "g.json")
    for _ in range(2):
        kg.ingest({"tool": "internal_api:/v1/orders/list", "step_type": "tool_call", "error": None},
                  {"status": "ANOMALY", "explanation": "repeat loop"}, KNOWN)
    assert kg.failures_for("internal_api:/v1/orders/list")["infinite_loop"] == 2
    g = _guard(tmp_path, memory=kg)
    held = g.check(_call("internal_api:/v1/orders/list"))
    assert held["action"] == PENDING and held["finding"]["kind"] == KNOWN_WRONG


def test_no_path_for_an_unknown_task_means_no_path_checks(tmp_path):
    g = Guard(KNOWN)
    g.reset("Summarise this week's tickets")
    assert g.path is None
    assert g.check(_call("refund_order", order_id="o", amount_usd=1))["action"] == ALLOW


# -- over HTTP ----------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    guard = Guard(KNOWN, learned_store=tmp_path / "learned.json")
    app, _ = create_app(meta_agent=type("J", (), {"model": "f", "structured_output_mode": "f",
                                                 "evaluate": lambda self, e, context=None: {"status": "OK"}})(),
                        knowledge_graph=KnowledgeGraph(path=tmp_path / "g.json"), guard=guard)
    app.config["TESTING"] = True
    return app.test_client()


def test_path_endpoints(client):
    assert client.get("/path/state").get_json()["active"] is False
    assert client.post("/path/automate", json={"on": True}).status_code == 409

    client.post("/session/goal", json={"goal": GOAL})
    state = client.get("/path/state").get_json()
    assert state["active"] and state["path"]["id"] == "support_refund"
    assert state["next"] == ["get_order", "check_policy"]

    assert client.post("/path/automate", json={"on": "yes"}).status_code == 400
    assert client.post("/path/automate", json={"on": True}).get_json()["automate"] is True
    assert client.post("/path/proposals/prop_missing", json={"accept": True}).status_code == 404


def test_deviation_decisions_over_http(client):
    client.post("/session/goal", json={"goal": GOAL})
    held = client.post("/guard/check", json={"tool": "refund_order", "input": {}}).get_json()
    aid = held["approval_id"]
    assert client.post(f"/guard/approval/{aid}", json={"decision": "approve"}).status_code == 400
    out = client.post(f"/guard/approval/{aid}", json={"decision": "automate"}).get_json()
    assert out["action"] == "block" and out["rule"] == "path"
    status = client.get(f"/guard/approval/{aid}").get_json()
    assert status["status"] == "automated" and status["decision"]["rule"] == "path"


# -- the agent side -------------------------------------------------------------

def test_decorator_runs_a_continued_move_and_blocks_an_automated_one(monkeypatch):
    decorator.enable_guard("http://g.test", approval_timeout=1, poll=0)
    try:
        answers = {"status": "continued"}
        monkeypatch.setattr(decorator, "_post", lambda *a, **k: {"action": PENDING, "approval_id": "dev_1"})
        monkeypatch.setattr(decorator, "_get", lambda *a, **k: {
            "status": answers["status"],
            "decision": {"action": "block", "rule": "path", "reason": "steer: tell the customer"}})

        @decorator.monitor(tool_name="refund_order")
        def refund():
            return "done"

        assert refund() == "done"
        answers["status"] = "automated"
        with pytest.raises(decorator.GuardBlocked, match="steer"):
            refund()
    finally:
        decorator.disable_guard()


def test_autopilot_offers_only_the_tools_on_the_path(monkeypatch):
    class Resp:
        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    tools = real_agent.TOOLS + real_agent.ROGUE_TOOLS
    monkeypatch.setattr(real_agent.requests, "get", lambda *a, **k: Resp(
        {"active": True, "automate": True, "allowed_tools": ["email_customer"]}))
    assert [t["function"]["name"] for t in real_agent.path_tools(tools)] == ["email_customer"]

    monkeypatch.setattr(real_agent.requests, "get", lambda *a, **k: Resp({"active": True, "automate": False}))
    assert len(real_agent.path_tools(tools)) == len(tools)
