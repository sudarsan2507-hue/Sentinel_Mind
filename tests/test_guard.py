"""Guard mode: a bad step is stopped before it runs, and the agent is told why."""

from __future__ import annotations

import pytest

import decorator
from guard import ALLOW, BLOCK, HALT, PENDING, Guard
from knowledge_graph import UNSAFE_ACTION, KnowledgeGraph, classify_failure

KNOWN = ["search_docs", "get_order", "refund_order", "erase_customer_data", "agent_llm_call"]


class FakeJudge:
    """Returns a canned verdict and remembers what it was shown."""

    def __init__(self, verdict: dict) -> None:
        self.verdict = verdict
        self.seen: list[tuple[dict, str]] = []

    def evaluate(self, event, context=None):
        self.seen.append((event, context.render(event) if context else ""))
        return dict(self.verdict)


def _call(tool: str, **kwargs) -> dict:
    return {"tool": tool, "step_type": "tool_call", "input": {"args": [], "kwargs": kwargs}}


def _guard(**kw) -> Guard:
    return Guard(KNOWN, meta_agent=kw.pop("judge", None), risky_tools={"refund_order"},
                 approval_tools={"erase_customer_data"}, **kw)


# -- rules: instant, no model call -------------------------------------------

def test_an_unregistered_tool_is_blocked_with_advice_naming_the_capability():
    decision = _guard().check(_call("internal_api:/v1/refunds/create", order_id="o1"))
    assert decision["action"] == BLOCK
    assert decision["rule"] == "unregistered"
    assert "issue refunds" in decision["reason"]
    assert "needs a human" in decision["reason"]


def test_the_third_identical_call_is_blocked_but_a_new_input_is_not():
    g = _guard()
    call = _call("search_docs", query="refund")
    assert g.check(call)["action"] == ALLOW
    assert g.check(call)["action"] == ALLOW
    third = g.check(call)
    assert third["action"] == BLOCK and third["rule"] == "repeat"
    assert g.check(_call("search_docs", query="escalation"))["action"] == ALLOW


def test_model_calls_are_never_pre_checked():
    g = _guard()
    assert g.check({"tool": "agent_llm_call", "step_type": "model_call", "input": {}})["action"] == ALLOW


# -- the judge, before the fact, for risky tools ------------------------------

def test_a_risky_call_the_judge_rejects_is_blocked_with_its_explanation():
    judge = FakeJudge({"status": "ANOMALY", "explanation": "Order is 58 days old; policy is 30.", "confidence": 0.9})
    g = _guard(judge=judge)
    g.reset("Resolve the complaint according to policy")
    g.observe({"tool": "get_order", "step_type": "tool_call", "input": {"kwargs": {"order_id": "ord_5512"}},
               "output": {"days_since_purchase": 58}, "error": None})

    decision = g.check(_call("refund_order", order_id="ord_5512", amount_usd=149))

    assert decision["action"] == BLOCK and decision["rule"] == "judge"
    assert "58 days old" in decision["reason"]
    # The judge was told this has not run yet, and shown what earlier tools returned.
    prompt = judge.seen[0][1]
    assert "has NOT run yet" in prompt
    assert "days_since_purchase" in prompt
    assert "Resolve the complaint according to policy" in prompt


def test_a_risky_call_the_judge_accepts_runs_and_carries_its_verdict():
    g = _guard(judge=FakeJudge({"status": "OK", "explanation": "Within window.", "confidence": 0.95}))
    decision = g.check(_call("refund_order", order_id="o1", amount_usd=10))
    assert decision["action"] == ALLOW
    assert decision["verdict"]["status"] == "OK"  # reused, so the step is not judged twice


def test_a_low_confidence_anomaly_does_not_block():
    g = _guard(judge=FakeJudge({"status": "ANOMALY", "explanation": "maybe", "confidence": 0.3}))
    assert g.check(_call("refund_order", order_id="o1", amount_usd=10))["action"] == ALLOW


@pytest.mark.parametrize("judge", [None, FakeJudge({"status": "WARN", "explanation": "x", "confidence": 0, "degraded": True})])
def test_a_risky_call_that_cannot_be_verified_is_blocked(judge):
    """Fail closed: an unverified irreversible action is what the guard is for."""
    decision = _guard(judge=judge).check(_call("refund_order", order_id="o1", amount_usd=10))
    assert decision["action"] == BLOCK and decision["rule"] == "unverified"


# -- circuit breaker ---------------------------------------------------------

def test_enough_strikes_halt_the_run():
    g = _guard(max_strikes=2)
    assert g.check(_call("made_up_tool"))["action"] == BLOCK
    second = g.check(_call("another_made_up_tool"))
    assert second["action"] == BLOCK and second.get("halted") is True
    after = g.check(_call("search_docs", query="anything"))
    assert after["action"] == HALT
    assert "a human will follow up" in after["reason"]


def test_post_hoc_tool_anomalies_count_as_strikes_but_model_calls_do_not():
    g = _guard(max_strikes=2)
    anomaly = {"status": "ANOMALY", "explanation": "bad"}
    assert g.note_verdict({"tool": "agent_llm_call", "step_type": "model_call"}, anomaly) is None
    assert g.note_verdict({"tool": "search_docs", "step_type": "tool_call"}, anomaly) is None
    assert g.note_verdict({"tool": "search_docs", "step_type": "tool_call"}, anomaly)["halted"] is True
    assert g.halted


def test_degraded_and_blocked_verdicts_are_not_strikes():
    g = _guard(max_strikes=1)
    assert g.note_verdict({"tool": "x", "step_type": "tool_call"}, {"status": "ANOMALY", "degraded": True}) is None
    assert g.note_verdict({"tool": "x", "step_type": "tool_call"}, {"status": "ANOMALY", "blocked": True}) is None
    assert not g.halted


def test_reset_starts_a_clean_run():
    g = _guard(max_strikes=1)
    g.check(_call("made_up_tool"))
    assert g.halted
    g.reset("new goal")
    assert not g.halted and g.strikes == 0 and g.goal == "new goal"
    assert g.check(_call("search_docs", query="q"))["action"] == ALLOW


# -- human approval ----------------------------------------------------------

def test_an_approval_tool_waits_for_a_human_and_runs_if_approved():
    g = _guard()
    pending = g.check(_call("erase_customer_data", customer_id="c1"))
    assert pending["action"] == PENDING
    assert g.state()["pending_approvals"][0]["tool"] == "erase_customer_data"
    assert g.decide(pending["approval_id"], approve=True)["action"] == ALLOW
    assert g.approval_status(pending["approval_id"]) == "approved"
    assert g.decide(pending["approval_id"], approve=False) is None  # already decided


def test_a_denied_or_expired_approval_blocks_and_is_a_strike():
    g = _guard()
    pending = g.check(_call("erase_customer_data", customer_id="c1"))
    outcome = g.expire(pending["approval_id"])
    assert outcome["action"] == BLOCK and outcome["rule"] == "approval_denied"
    assert g.strikes == 1


# -- the decorator side ------------------------------------------------------

@pytest.fixture
def guarded(monkeypatch):
    """Guard mode on, with the server replaced by scripted answers."""
    answers: dict = {"check": {"action": ALLOW}, "status": []}
    events: list[dict] = []
    decorator.subscribe(events.append)
    decorator.enable_guard("http://guard.test", approval_timeout=0.05, poll=0.001)

    def fake_post(path, body, timeout=30.0):
        answers.setdefault("posts", []).append((path, body))
        if path == "/guard/check":
            return answers["check"]
        return answers.get("decide", {"action": BLOCK, "rule": "approval_timeout", "reason": "no approval"})

    def fake_get(path, timeout=10.0):
        return {"status": answers["status"].pop(0)} if answers["status"] else {"status": "pending"}

    monkeypatch.setattr(decorator, "_post", fake_post)
    monkeypatch.setattr(decorator, "_get", fake_get)
    yield answers, events
    decorator.disable_guard()


def test_a_blocked_call_never_runs_and_raises_the_instruction(guarded):
    answers, events = guarded
    answers["check"] = {"action": BLOCK, "rule": "judge", "reason": "Blocked: out of policy."}
    ran = []

    @decorator.monitor(tool_name="refund_order", risky=True)
    def refund(order_id):
        ran.append(order_id)

    with pytest.raises(decorator.GuardBlocked, match="out of policy") as exc:
        refund("ord_5512")
    assert ran == []
    assert exc.value.rule == "judge"
    assert events[-1]["guard"]["action"] == BLOCK
    assert events[-1]["error"].startswith("GuardBlocked")
    assert answers["posts"][0][1]["risky"] is True


def test_a_halt_raises_guard_halt(guarded):
    answers, _ = guarded
    answers["check"] = {"action": HALT, "rule": "circuit_breaker", "reason": "stop"}

    @decorator.monitor(tool_name="search_docs")
    def search(q):
        return q

    with pytest.raises(decorator.GuardHalt):
        search("x")


def test_an_approved_call_runs(guarded):
    answers, events = guarded
    answers["check"] = {"action": PENDING, "approval_id": "apr_1"}
    answers["status"] = ["pending", "approved"]

    @decorator.monitor(tool_name="erase_customer_data", approval=True)
    def erase(cid):
        return f"erased {cid}"

    assert erase("c1") == "erased c1"
    assert events[-1]["guard"]["rule"] == "approval"


def test_an_unanswered_approval_is_denied(guarded):
    answers, _ = guarded
    answers["check"] = {"action": PENDING, "approval_id": "apr_2"}

    @decorator.monitor(tool_name="erase_customer_data", approval=True)
    def erase(cid):
        return "erased"

    with pytest.raises(decorator.GuardBlocked):
        erase("c1")
    assert answers["posts"][-1][0] == "/guard/approval/apr_2"


def test_unreachable_guard_lets_ordinary_tools_run_but_not_risky_ones(guarded, monkeypatch):
    monkeypatch.setattr(decorator, "_post", lambda *a, **k: None)

    @decorator.monitor(tool_name="search_docs")
    def search(q):
        return "ok"

    @decorator.monitor(tool_name="refund_order", risky=True)
    def refund(order_id):
        return "refunded"

    assert search("q") == "ok"
    with pytest.raises(decorator.GuardBlocked):
        refund("o1")


def test_without_guard_mode_nothing_changes():
    decorator.disable_guard()

    @decorator.monitor(tool_name="refund_order", risky=True)
    def refund(order_id):
        return "refunded"

    assert refund("o1") == "refunded"


# -- failure memory ----------------------------------------------------------

def test_a_judge_block_is_remembered_as_an_unsafe_action_not_an_exception(tmp_path):
    event = {"tool": "refund_order", "error": "GuardBlocked: out of policy", "step_type": "tool_call"}
    verdict = {"status": "BLOCKED", "explanation": "out of policy", "blocked": True, "rule": "judge"}
    assert classify_failure(event, verdict, KNOWN) == UNSAFE_ACTION

    kg = KnowledgeGraph(path=tmp_path / "g.json")
    kg.ingest(event, verdict, KNOWN, goal="g")
    modes = {n["id"] for n in kg.snapshot()["nodes"] if n["type"] == "failure_mode"}
    assert modes == {UNSAFE_ACTION}  # no stray "exception" edge for a step that never ran
    assert any("'refund_order' was stopped 1 time(s)" in lesson for lesson in kg.lessons())
