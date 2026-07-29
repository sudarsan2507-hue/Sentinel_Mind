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
