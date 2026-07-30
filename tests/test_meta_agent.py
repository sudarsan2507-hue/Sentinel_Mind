"""The meta-agent must always produce a usable verdict."""

from __future__ import annotations

from conftest import FakeGroq

from meta_agent import ANOMALY, OK, SYSTEM_PROMPT, WARN, MetaAgent


def test_system_prompt_defines_each_verdict_the_right_way_round():
    """Guards the prompt against silent inversion.

    This is not a hypothetical. A round of file corruption flipped three
    sentences in this prompt -- "the step is valid" became "the step is not
    valid", and the ANOMALY definition was negated outright -- which told the
    model to invert every verdict it produced. Nothing failed: the tests passed,
    the server ran, and the dashboard filled with confident, backwards answers.

    A prompt is behaviour. It deserves an assertion like any other.
    """
    assert "OK: the step is valid." in SYSTEM_PROMPT
    assert "ANOMALY: the step is broken or dangerous." in SYSTEM_PROMPT
    assert "a thrown exception" in SYSTEM_PROMPT

    # The exact inversions that were introduced, pinned so they cannot come back.
    for inverted in (
        "the step is not valid",
        "not broken or not dangerous",
        "never a throw exception",
    ):
        assert inverted not in SYSTEM_PROMPT, f"prompt inverted: {inverted!r}"


def test_structured_output_mode_reports_which_path_was_taken(sample_event):
    """Which format we settled on is a claim we make to judges -- so read it."""
    agent = MetaAgent(client=FakeGroq({"status": "OK", "explanation": "ok", "confidence": 0.9}))
    assert agent.structured_output_mode == "untested"

    agent.evaluate(sample_event)
    assert agent.structured_output_mode == "json_schema"

    class BadRequest(Exception):
        status_code = 400

    downgraded = MetaAgent(client=FakeGroq(error=BadRequest("response_format unsupported")))
    downgraded.evaluate(sample_event)
    assert downgraded.structured_output_mode == "json_object"


def test_returns_ok_verdict(sample_event):
    client = FakeGroq(
        {"status": "OK", "explanation": "Valid tool call.", "confidence": 0.95}
    )
    agent = MetaAgent(client=client, known_tools=["search_docs"])

    verdict = agent.evaluate(sample_event)

    assert verdict["status"] == OK
    assert verdict["confidence"] == 0.95
    assert verdict["event_id"] == sample_event["id"]
    assert verdict["degraded"] is False


def test_returns_anomaly_verdict(sample_event):
    event = {**sample_event, "tool": "delete_production_db", "error": "ToolNotFound"}
    client = FakeGroq(
        {
            "status": "ANOMALY",
            "explanation": "Called 'delete_production_db', which is not a registered tool.",
            "confidence": 0.98,
        }
    )
    agent = MetaAgent(client=client, known_tools=["search_docs"])

    verdict = agent.evaluate(event)

    assert verdict["status"] == ANOMALY
    assert "not a registered tool" in verdict["explanation"]


def test_handles_api_failure_gracefully(sample_event):
    """An API outage degrades to WARN -- it never crashes and never claims OK.

    It also must NOT downgrade the response format. A connection reset says
    nothing about whether the model supports strict schema, and the downgrade is
    permanent for the process.
    """
    client = FakeGroq(error=RuntimeError("connection reset"))
    agent = MetaAgent(client=client)

    verdict = agent.evaluate(sample_event)

    assert verdict["status"] == WARN
    assert verdict["degraded"] is True
    assert "connection reset" in verdict["explanation"]
    assert verdict["confidence"] == 0.0

    formats = [c["response_format"]["type"] for c in client.completions.calls]
    assert formats == ["json_schema"], "an outage must not cost us strict schema"
    assert agent.structured_output_mode == "untested"


def test_downgrades_to_json_object_only_on_a_real_schema_rejection(sample_event):
    """The downgrade path itself: 400 naming the format, retried once, remembered."""

    class BadRequest(Exception):
        status_code = 400

    client = FakeGroq(error=BadRequest("response_format json_schema is not supported"))
    agent = MetaAgent(client=client)

    agent.evaluate(sample_event)

    formats = [c["response_format"]["type"] for c in client.completions.calls]
    assert formats == ["json_schema", "json_object"]
    assert agent.structured_output_mode == "json_object"

    # Remembered: the second evaluation never re-tries strict schema.
    agent.evaluate(sample_event)
    assert [c["response_format"]["type"] for c in client.completions.calls] == [
        "json_schema",
        "json_object",
        "json_object",
    ]


def test_auth_failure_does_not_downgrade_the_format(sample_event):
    """A 401 is an account problem, not a capability signal."""

    class Unauthorized(Exception):
        status_code = 401

    client = FakeGroq(error=Unauthorized("invalid api key"))
    agent = MetaAgent(client=client)

    agent.evaluate(sample_event)

    assert [c["response_format"]["type"] for c in client.completions.calls] == ["json_schema"]
    assert agent.structured_output_mode == "untested"


def test_verdict_has_all_required_fields(sample_event):
    client = FakeGroq(
        {"status": "WARN", "explanation": "Unusually slow.", "confidence": 0.6}
    )
    agent = MetaAgent(client=client)

    verdict = agent.evaluate(sample_event)

    for field in (
        "status",
        "explanation",
        "confidence",
        "event_id",
        "tool",
        "latency_ms",
        "degraded",
        "downgraded",
    ):
        assert field in verdict, f"verdict missing {field}"
    assert verdict["status"] in (OK, WARN, ANOMALY)
    assert 0.0 <= verdict["confidence"] <= 1.0
