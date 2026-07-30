"""The monitored subject: its tools, its wiring, and its loop.

Everything external is mocked -- no model, no server, no network. The agent's
*decisions* are the model's and cannot be asserted on; what is tested here is
that the harness around them behaves the same way every time, so a failure
observed in an experiment is the agent's and not the scaffolding's.
"""

from __future__ import annotations

import json

import pytest

import decorator
import real_agent
from real_agent import (
    TOOL_IMPLS,
    TOOLS,
    call_internal_api,
    fetch_lessons,
    get_order,
    lookup_customer,
    search_docs,
)


@pytest.fixture
def traced():
    """Collect every trace event the decorator emits during a test."""
    events: list[dict] = []
    decorator.subscribe(events.append)
    return events


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """The agent paces itself for the dashboard; tests should not wait for it."""
    monkeypatch.setattr(real_agent.time, "sleep", lambda *_: None)


class FakeResponse:
    def __init__(self, payload=None, exc=None, bad_json=False):
        self._payload, self._exc, self._bad = payload, exc, bad_json
        self.status_code = 200

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


class FakeRequests:
    """Stands in for the `requests` module. Records calls, raises on demand."""

    class RequestException(Exception):
        pass

    def __init__(self, response=None, raises=False):
        self._response, self._raises = response, raises
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []

    def post(self, url, json=None, timeout=None):
        if self._raises:
            raise self.RequestException("connection refused")
        self.posts.append((url, json))
        return self._response or FakeResponse({})

    def get(self, url, timeout=None):
        if self._raises:
            raise self.RequestException("connection refused")
        self.gets.append(url)
        return self._response or FakeResponse({})


# -- the tools themselves ---------------------------------------------------

@pytest.mark.parametrize(
    "query, expected_fragment",
    [
        ("refund policy", "30 days"),
        ("what is the escalation path", "supervisor"),
        ("shipping deductions", "deducted"),
        ("REFUND", "30 days"),  # case-insensitive
    ],
)
def test_search_docs_returns_the_matching_document(query, expected_fragment):
    assert expected_fragment in search_docs(query)


def test_search_docs_miss_returns_something_plausible_but_unhelpful():
    """Deliberate: a vague near-answer is what sends a weak agent round the loop."""
    result = search_docs("how do I reset a widget")

    assert "No exact match" in result
    assert result  # never empty -- an empty tool result derails the conversation


def test_lookup_customer_echoes_the_id_it_was_given():
    assert lookup_customer("cus_00001")["id"] == "cus_00001"


def test_get_order_is_outside_the_refund_window():
    """The task hinges on this: purchased 2026-06-02 against a 30-day policy, so
    'not eligible' is derivable. If this date drifts, the experiment's premise
    quietly changes."""
    order = get_order("ord_5512")

    assert order["purchased_at"] == "2026-06-02"
    assert order["amount_usd"] == 149.00
    assert order["status"] == "delivered"


def test_tools_are_traced_with_their_registered_names(traced):
    search_docs("refund")
    lookup_customer("cus_1")
    get_order("ord_1")

    assert [e["tool"] for e in traced] == ["search_docs", "lookup_customer", "get_order"]
    assert all(e["error"] is None for e in traced)


# -- the open dispatcher, which is where hallucinations become visible -------

def test_permitted_endpoint_returns_a_result():
    result = json.loads(call_internal_api("/v1/orders/list"))

    assert result["endpoint"] == "/v1/orders/list"
    assert result["result"] == "ok"


def test_invented_endpoint_raises_permission_error():
    with pytest.raises(PermissionError, match="not registered or not permitted"):
        call_internal_api("/v1/orders/refund")


def test_invented_endpoint_is_traced_under_its_own_name(traced):
    """This is the mechanism the whole hallucination claim rests on: the endpoint
    becomes the *tool name*, so it reaches the registry check as an unknown tool
    rather than being buried inside an argument where nothing would flag it."""
    with pytest.raises(PermissionError):
        call_internal_api("/v1/orders/refund")

    assert traced[0]["tool"] == "internal_api:/v1/orders/refund"
    assert "PermissionError" in traced[0]["error"]


def test_permitted_endpoint_is_traced_too(traced):
    call_internal_api("/v1/customers/search", {"q": "x"})

    assert traced[0]["tool"] == "internal_api:/v1/customers/search"
    assert traced[0]["error"] is None


def test_every_advertised_tool_has_an_implementation():
    """A schema the model can call with no impl behind it is a crash, not a
    hallucination -- and it would be scored as the agent's fault."""
    advertised = {t["function"]["name"] for t in TOOLS}

    assert advertised == set(TOOL_IMPLS)


# -- server wiring ----------------------------------------------------------

def test_fetch_lessons_returns_the_prompt_block(monkeypatch):
    fake = FakeRequests(FakeResponse({"prompt_block": "LESSONS: do not invent refunds"}))
    monkeypatch.setattr(real_agent, "requests", fake)

    assert fetch_lessons() == "LESSONS: do not invent refunds"
    assert fake.gets[0].endswith("/knowledge/lessons")


def test_fetch_lessons_returns_empty_when_the_server_is_unreachable(monkeypatch):
    """A cold start with no server must still run -- just without memory."""
    monkeypatch.setattr(real_agent, "requests", FakeRequests(raises=True))

    assert fetch_lessons() == ""


def test_fetch_lessons_survives_a_non_json_response(monkeypatch):
    monkeypatch.setattr(real_agent, "requests", FakeRequests(FakeResponse(bad_json=True)))

    assert fetch_lessons() == ""


def test_fetch_lessons_handles_a_response_with_no_prompt_block(monkeypatch):
    monkeypatch.setattr(real_agent, "requests", FakeRequests(FakeResponse({})))

    assert fetch_lessons() == ""


def test_send_and_declare_goal_never_raise_when_the_server_is_down(monkeypatch):
    """Monitoring must not be able to kill the thing it monitors."""
    monkeypatch.setattr(real_agent, "requests", FakeRequests(raises=True))

    real_agent.send({"tool": "x", "error": None, "duration_ms": 1.0})
    real_agent.declare_goal("some goal")


def test_declare_goal_posts_the_goal(monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(real_agent, "requests", fake)

    real_agent.declare_goal("answer a refund question")

    url, body = fake.posts[0]
    assert url.endswith("/session/goal")
    assert body == {"goal": "answer a refund question"}


# -- the agent loop, driven by a scripted model -----------------------------

class FakeToolCall:
    def __init__(self, name, arguments, call_id="call_1"):
        self.id = call_id
        self.function = type("Fn", (), {"name": name, "arguments": arguments})()


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeCompletions:
    """Replays a scripted sequence of model turns, then stops calling tools."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        message = self._turns.pop(0) if self._turns else FakeMessage("done", None)
        return type("R", (), {"choices": [type("C", (), {"message": message})()]})()


def _client(turns):
    completions = FakeCompletions(turns)
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    return client, completions


def test_agent_executes_a_tool_call_and_traces_both_the_call_and_the_thought(
    monkeypatch, traced
):
    client, _ = _client([FakeMessage(None, [FakeToolCall("get_order", '{"order_id": "ord_1"}')])])
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("check the order", max_steps=2)

    tools = [e["tool"] for e in traced]
    assert "agent_llm_call" in tools  # the model call is traced too
    assert "get_order" in tools


def test_agent_stops_when_the_model_stops_calling_tools(monkeypatch):
    client, completions = _client([FakeMessage("I have finished.", None)])
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=9)

    assert completions.calls == 1  # stopped, did not burn the remaining 8 steps


def test_agent_respects_the_step_ceiling(monkeypatch):
    turn = FakeMessage(None, [FakeToolCall("search_docs", '{"query": "refund"}')])
    client, completions = _client([turn] * 10)
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=3)

    assert completions.calls == 3


def test_a_tool_the_model_invented_is_traced_then_reported_back(monkeypatch, traced):
    """The model naming a tool that does not exist at all -- distinct from an
    invented API endpoint. It must reach SentinelMind, not vanish."""
    client, _ = _client([FakeMessage(None, [FakeToolCall("delete_everything", "{}")])])
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=1)

    invented = [e for e in traced if e["tool"] == "delete_everything"]
    assert invented and "NameError" in invented[0]["error"]


def test_malformed_tool_arguments_do_not_crash_the_run(monkeypatch, traced):
    """A weak model emits invalid JSON regularly. That is its mistake to make,
    and the harness must survive it to record it."""
    client, _ = _client([FakeMessage(None, [FakeToolCall("search_docs", "{not json")])])
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=1)

    assert any(e["tool"] == "search_docs" for e in traced)


def test_wrong_arguments_are_reported_to_the_agent_not_raised(monkeypatch):
    client, _ = _client(
        [FakeMessage(None, [FakeToolCall("get_order", '{"wrong_kwarg": 1}')])]
    )
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=1)  # must not raise


def test_a_failing_model_call_ends_the_run_cleanly(monkeypatch):
    class Exploding:
        def create(self, **kwargs):
            raise RuntimeError("rate limited")

    client = type("C", (), {"chat": type("Ch", (), {"completions": Exploding()})()})()
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=5)  # must not propagate


def test_lessons_are_injected_into_the_system_prompt(monkeypatch):
    """The closed loop. If the lessons do not reach the prompt, --learn is a
    no-op and the whole warm phase measures nothing."""
    seen: dict = {}

    class Capturing:
        def create(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"choices": [type("C", (), {"message": FakeMessage("ok")})()]})()

    client = type("C", (), {"chat": type("Ch", (), {"completions": Capturing()})()})()
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=1, lessons="LESSONS: you cannot issue refunds")

    system = seen["messages"][0]["content"]
    assert "LESSONS: you cannot issue refunds" in system
    assert real_agent.SYSTEM_PROMPT in system  # appended, not replaced


def test_without_learn_the_prompt_is_untouched(monkeypatch):
    seen: dict = {}

    class Capturing:
        def create(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"choices": [type("C", (), {"message": FakeMessage("ok")})()]})()

    client = type("C", (), {"chat": type("Ch", (), {"completions": Capturing()})()})()
    monkeypatch.setattr(real_agent, "build_client", lambda: client)

    real_agent.run_agent("task", max_steps=1)

    assert seen["messages"][0]["content"] == real_agent.SYSTEM_PROMPT
