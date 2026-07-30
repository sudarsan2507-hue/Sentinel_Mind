"""HTTP surface of the WebSocket server."""

from __future__ import annotations

import pytest

from app import create_app
from audit_log import AuditLog
from meta_agent import MetaAgent


@pytest.fixture
def client(sample_event):
    log = AuditLog()
    log.record(
        sample_event,
        {"status": "ANOMALY", "explanation": "hallucinated tool", "confidence": 0.97},
    )
    app, _socketio = create_app(meta_agent=MetaAgent(client=object()), audit_log=log)
    app.config["TESTING"] = True
    return app.test_client()


def test_health_endpoint_returns_200(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "sentinelmind"


def test_audit_endpoint_returns_correct_structure(client):
    response = client.get("/audit")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"summary", "entries"}
    assert body["summary"]["total"] == 1
    assert body["summary"]["counts"]["ANOMALY"] == 1

    entry = body["entries"][0]
    assert set(entry) >= {"sequence", "recorded_at", "event", "verdict", "status"}
    assert entry["verdict"]["explanation"] == "hallucinated tool"


def test_replay_records_a_prejudged_verdict_without_calling_the_meta_agent(client, sample_event):
    """The offline fallback's whole point: no provider call on this path.

    ``MetaAgent(client=object())`` would raise on any attempt to use it, so if
    this passes, nothing tried to judge the event.
    """
    response = client.post(
        "/replay",
        json={
            "event": sample_event,
            "verdict": {"status": "ANOMALY", "explanation": "recorded loop", "confidence": 0.94},
        },
    )

    assert response.status_code == 202
    entries = client.get("/audit").get_json()["entries"]
    assert len(entries) == 2  # the fixture's entry, plus this one
    replayed = entries[-1]
    assert replayed["status"] == "ANOMALY"
    # Stamped, so the dashboard never passes a recording off as a live verdict.
    assert replayed["verdict"]["replayed"] is True


def test_replay_rejects_a_payload_missing_its_verdict(client, sample_event):
    response = client.post("/replay", json={"event": sample_event})

    assert response.status_code == 400
