"""The built frontend is served compressed and cached -- the top Lighthouse finding."""

from __future__ import annotations

import gzip

import pytest

import app as app_module
from app import create_app
from knowledge_graph import KnowledgeGraph
from meta_agent import MetaAgent


@pytest.fixture
def client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    js = b"console.log('hello');" * 50
    (dist / "assets" / "app-abc.js").write_bytes(js)
    (dist / "assets" / "app-abc.js.gz").write_bytes(gzip.compress(js))
    (dist / "robots.txt").write_text("User-agent: *")
    monkeypatch.setattr(app_module, "FRONTEND_DIR", dist)
    app, _ = create_app(
        meta_agent=MetaAgent(client=object()),
        knowledge_graph=KnowledgeGraph(path=tmp_path / "graph.json"),
    )
    return app.test_client()


def test_assets_are_served_gzipped_when_accepted(client):
    resp = client.get("/assets/app-abc.js", headers={"Accept-Encoding": "gzip, br"})
    assert resp.headers["Content-Encoding"] == "gzip"
    assert resp.mimetype in ("text/javascript", "application/javascript")
    assert gzip.decompress(resp.data).startswith(b"console.log")
    assert "immutable" in resp.headers["Cache-Control"]
    assert resp.headers["Vary"] == "Accept-Encoding"


def test_assets_fall_back_to_plain_without_gzip(client):
    resp = client.get("/assets/app-abc.js", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in resp.headers
    assert resp.data.startswith(b"console.log")


def test_unhashed_files_are_not_cached_forever(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "immutable" not in resp.headers.get("Cache-Control", "")


def test_client_routes_fall_through_to_the_spa(client):
    assert client.get("/graph").data == b"<html>spa</html>"



def test_large_json_is_gzipped_only_when_accepted(tmp_path):
    """/knowledge was the one uncompressed response Lighthouse still flagged."""
    import json

    kg = KnowledgeGraph(path=tmp_path / "graph.json")
    for i in range(30):
        kg.ingest(
            {"tool": f"internal_api:/v1/invented/{i}", "error": "PermissionError"},
            {"status": "ANOMALY", "explanation": "not in the registry " * 5},
            ["search_docs"],
        )
    app, _ = create_app(meta_agent=MetaAgent(client=object()), knowledge_graph=kg)
    c = app.test_client()

    zipped = c.get("/knowledge", headers={"Accept-Encoding": "gzip"})
    assert zipped.headers["Content-Encoding"] == "gzip"
    assert len(json.loads(gzip.decompress(zipped.data))["nodes"]) > 30

    plain = c.get("/knowledge")
    assert "Content-Encoding" not in plain.headers
    assert json.loads(plain.data)["nodes"]


def test_small_json_is_left_uncompressed(client):
    resp = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in resp.headers
