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


class RateLimited(Exception):
    status_code = 429


def test_a_short_rate_limit_is_waited_out(monkeypatch, sample_event):
    """A burst limit is worth sleeping through: degrading on the first 429 blinds
    the monitor for the rest of the burst, and a degraded verdict can never be
    ANOMALY, so a rate-limited run reads as healthy."""
    slept: list[float] = []
    monkeypatch.setattr("meta_agent.time.sleep", lambda s: slept.append(s))

    client = FakeGroq(error=RateLimited("Rate limit reached. Please try again in 1.5s"))
    agent = MetaAgent(client=client, rate_limit_retries=2, max_backoff=5.0)

    agent.evaluate(sample_event)

    assert slept == [1.5, 1.5]  # retried, honouring the server's own figure


def test_a_long_rate_limit_gives_up_immediately_instead_of_stalling(
    monkeypatch, sample_event
):
    """Judging is single-threaded, so a sleep stalls the whole queue. Retrying a
    wait we cannot outlast cost 90s per event and failed anyway -- observed as a
    13-step run frozen at one verdict."""
    slept: list[float] = []
    monkeypatch.setattr("meta_agent.time.sleep", lambda s: slept.append(s))

    client = FakeGroq(
        error=RateLimited("tokens per day (TPD) exceeded. Please try again in 9m37.152s")
    )
    agent = MetaAgent(client=client, rate_limit_retries=3, max_backoff=5.0)

    verdict = agent.evaluate(sample_event)

    assert slept == []  # never stalled the queue
    assert verdict["degraded"] is True
    assert verdict["status"] == WARN


def test_retry_after_is_parsed_from_the_message_when_there_is_no_header():
    """Groq reports the wait in the body on daily-cap errors, not the header."""
    from meta_agent import _retry_after

    assert _retry_after(RateLimited("try again in 9m37.152s"), default=1.0) == 577.152
    assert _retry_after(RateLimited("try again in 2.5s"), default=1.0) == 2.5
    assert _retry_after(RateLimited("no figure here"), default=7.0) == 7.0


def test_auth_failure_does_not_downgrade_the_format(sample_event):
    """A 401 is an account problem, not a capability signal."""

    class Unauthorized(Exception):
        status_code = 401

    client = FakeGroq(error=Unauthorized("invalid api key"))
    agent = MetaAgent(client=client)

    agent.evaluate(sample_event)

    assert [c["response_format"]["type"] for c in client.completions.calls] == ["json_schema"]
    assert agent.structured_output_mode == "untested"


def test_verdict_carries_token_usage_when_the_provider_reports_it(sample_event):
    """Per-verdict cost, so a run's spend is recoverable from the audit log."""
    client = FakeGroq({"status": "OK", "explanation": "ok", "confidence": 0.9})
    client.completions._response.usage = type(
        "Usage", (), {"prompt_tokens": 812, "completion_tokens": 44, "total_tokens": 856}
    )()

    verdict = MetaAgent(client=client).evaluate(sample_event)

    assert verdict["tokens"] == {"prompt": 812, "completion": 44, "total": 856}


def test_missing_usage_is_none_not_zero(sample_event):
    """None means "not reported"; 0 would claim a call cost nothing."""
    verdict = MetaAgent(
        client=FakeGroq({"status": "OK", "explanation": "ok", "confidence": 0.9})
    ).evaluate(sample_event)
    assert verdict["tokens"] is None

    degraded = MetaAgent(client=FakeGroq(error=RuntimeError("down"))).evaluate(sample_event)
    assert degraded["tokens"] is None


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
