"""The meta-agent must always produce a usable verdict."""

from __future__ import annotations

from conftest import FakeGroq

from meta_agent import ANOMALY, OK, WARN, MetaAgent


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

    Also pins the strict-schema downgrade: the first call uses json_schema, and
    on rejection the agent retries once with json_object before giving up.
    """
    client = FakeGroq(error=RuntimeError("connection reset"))
    agent = MetaAgent(client=client)

    verdict = agent.evaluate(sample_event)

    assert verdict["status"] == WARN
    assert verdict["degraded"] is True
    assert "connection reset" in verdict["explanation"]
    assert verdict["confidence"] == 0.0

    formats = [c["response_format"]["type"] for c in client.completions.calls]
    assert formats == ["json_schema", "json_object"]


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
