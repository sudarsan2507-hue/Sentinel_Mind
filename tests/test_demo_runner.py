"""Starting the example agents from the connect guide."""

from __future__ import annotations

import pytest

import app as app_module
from app import create_app
from guard import Guard
from knowledge_graph import KnowledgeGraph


class Judge:
    model = "fake"
    structured_output_mode = "fake"
    known_tools: list = []

    def evaluate(self, event, context=None):
        return {"status": "OK", "explanation": "fine", "confidence": 0.9, "latency_ms": 1}


class FakeProcess:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.returncode = None

    def poll(self):
        return self.returncode


@pytest.fixture
def server(tmp_path, monkeypatch):
    started = []

    def popen(cmd, **kwargs):
        started.append(FakeProcess(cmd, **kwargs))
        return started[-1]

    monkeypatch.setattr(app_module.subprocess, "Popen", popen)
    app, _ = create_app(meta_agent=Judge(), knowledge_graph=KnowledgeGraph(path=tmp_path / "g.json"),
                        guard=Guard(["search_docs"]))
    app.config["TESTING"] = True
    return app.test_client(), started


def test_a_known_demo_starts_with_its_fixed_command(server):
    client, started = server
    resp = client.post("/demo/run", json={"demo": "travel"})
    assert resp.status_code == 202 and resp.get_json()["running"] is True
    assert started[0].cmd[-1] == "examples/connect_your_agent.py"


def test_an_unknown_demo_is_refused_and_nothing_starts(server):
    client, started = server
    assert client.post("/demo/run", json={"demo": "rm -rf /"}).status_code == 400
    assert started == []


def test_only_one_demo_runs_at_a_time(server):
    client, started = server
    client.post("/demo/run", json={"demo": "travel"})
    assert client.post("/demo/run", json={"demo": "refund"}).status_code == 409
    started[0].returncode = 0
    assert client.get("/demo/status").get_json() | {"demos": None} == {
        "running": False, "name": "travel", "exit_code": 0, "demos": None}
    assert client.post("/demo/run", json={"demo": "refund"}).status_code == 202


def test_demos_cannot_be_started_from_another_machine(server):
    client, started = server
    resp = client.post("/demo/run", json={"demo": "travel"}, environ_base={"REMOTE_ADDR": "10.0.0.7"})
    assert resp.status_code == 403 and started == []


def test_session_lists_the_tools_agents_registered(server):
    client, _ = server
    assert client.get("/session").get_json()["registered"] == []
    client.post("/session/tools", json={"tools": ["lookup_booking"], "risky": ["rebook"]})
    assert client.get("/session").get_json()["registered"] == ["lookup_booking", "rebook"]


def test_api_paths_are_not_swallowed_by_the_web_app(server):
    client, _ = server
    assert client.get("/path/nope").status_code == 404
    assert client.get("/guard/nope").status_code == 404
    assert client.get("/demo/nope").status_code == 404
