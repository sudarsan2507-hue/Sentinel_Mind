"""The scripted demo pipeline -- the code that runs on stage.

It had no coverage at all, which is a strange place to have none: an
unnoticed break here does not fail a test suite, it fails in front of judges.
The offline path especially, because it exists precisely for the moment when
nothing else is working and there is no time to debug.

Everything external is mocked. No server, no network.
"""

from __future__ import annotations

import json

import pytest

import demo_agent
from demo_agent import _load_recording, offline, replay, save_recording


class FakeResponse:
    def __init__(self, payload=None, bad_json=False, status=200):
        self._payload, self._bad = payload, bad_json
        self.status_code = status

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeRequests.RequestException(f"HTTP {self.status_code}")


class FakeRequests:
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


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    """The pipeline paces itself for the dashboard. Tests should not wait."""
    monkeypatch.setattr(demo_agent.time, "sleep", lambda *_: None)


@pytest.fixture
def fake_requests(monkeypatch):
    fake = FakeRequests()
    monkeypatch.setattr(demo_agent, "requests", fake)
    return fake


def _entry(tool="search_docs", status="OK"):
    return {
        "event": {"id": f"evt_{tool}", "tool": tool, "input": {"args": [], "kwargs": {}},
                  "output": "x", "error": None, "duration_ms": 60.0},
        "verdict": {"status": status, "explanation": "because", "confidence": 0.9,
                    "latency_ms": 500.0},
    }


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# -- loading recordings -----------------------------------------------------

def test_loads_the_current_event_and_verdict_shape(tmp_path):
    path = _write(tmp_path / "run.json", [_entry(), _entry("get_order", "ANOMALY")])

    entries = _load_recording(path)

    assert len(entries) == 2
    assert entries[1]["verdict"]["status"] == "ANOMALY"


def test_legacy_event_only_recordings_still_load(tmp_path):
    """Older files were a bare list of events. They must still drive --replay."""
    path = _write(tmp_path / "run.json", [{"id": "evt_1", "tool": "search_docs"}])

    entries = _load_recording(path)

    assert entries[0]["event"]["tool"] == "search_docs"
    assert entries[0]["verdict"] is None


def test_a_missing_recording_exits_with_the_command_that_creates_one(tmp_path):
    with pytest.raises(SystemExit) as exc:
        _load_recording(tmp_path / "absent.json")

    assert "--record" in str(exc.value)


def test_a_recording_of_the_wrong_shape_is_rejected(tmp_path):
    path = _write(tmp_path / "run.json", {"not": "a list"})

    with pytest.raises(SystemExit, match="not a recording"):
        _load_recording(path)


# -- offline mode, the fallback that has to work when nothing else does ------

def test_offline_posts_pre_judged_entries_and_never_touches_trace(tmp_path, fake_requests):
    """The whole contract: /replay only. A single /trace call here would mean
    the server judges the event, which needs the API, which is the thing that
    is broken when you reach for this mode."""
    path = _write(tmp_path / "run.json", [_entry(), _entry("get_order", "ANOMALY")])

    offline(path, pace=0)

    urls = [url for url, _ in fake_requests.posts]
    assert sum(1 for u in urls if u.endswith("/replay")) == 2
    assert not any(u.endswith("/trace") for u in urls)


def test_offline_sends_the_recorded_verdict_alongside_the_event(tmp_path, fake_requests):
    path = _write(tmp_path / "run.json", [_entry("flaky_api", "ANOMALY")])

    offline(path, pace=0)

    _url, body = [p for p in fake_requests.posts if p[0].endswith("/replay")][0]
    assert body["verdict"]["status"] == "ANOMALY"
    assert body["event"]["tool"] == "flaky_api"


def test_offline_refuses_a_recording_with_no_verdicts(tmp_path, fake_requests):
    """Better to refuse than to replay half a run and look like it worked."""
    path = _write(tmp_path / "run.json", [{"id": "evt_1", "tool": "search_docs"}])

    with pytest.raises(SystemExit) as exc:
        offline(path, pace=0)

    assert "--record" in str(exc.value)


def test_offline_refuses_when_only_some_verdicts_are_missing(tmp_path, fake_requests):
    path = _write(tmp_path / "run.json", [_entry(), {"id": "evt_2", "tool": "x"}])

    with pytest.raises(SystemExit, match="1 event"):
        offline(path, pace=0)


def test_offline_survives_an_unreachable_server(tmp_path, monkeypatch):
    """It must not crash mid-demo if the server is not up yet."""
    monkeypatch.setattr(demo_agent, "requests", FakeRequests(raises=True))
    path = _write(tmp_path / "run.json", [_entry()])

    offline(path, pace=0)  # must not raise


# -- replay mode ------------------------------------------------------------

def test_replay_posts_events_to_trace_for_rejudging(tmp_path, fake_requests):
    path = _write(tmp_path / "run.json", [_entry(), _entry("get_order")])

    replay(path, pace=0)

    urls = [url for url, _ in fake_requests.posts]
    assert sum(1 for u in urls if u.endswith("/trace")) == 2
    assert not any(u.endswith("/replay") for u in urls)


def test_replay_works_from_a_legacy_event_only_recording(tmp_path, fake_requests):
    path = _write(tmp_path / "run.json", [{"id": "e", "tool": "search_docs",
                                           "error": None, "duration_ms": 1.0}])

    replay(path, pace=0)

    assert any(u.endswith("/trace") for u, _ in fake_requests.posts)


# -- recording --------------------------------------------------------------

def test_save_recording_pulls_verdicts_back_from_the_audit_log(tmp_path, monkeypatch):
    """Verdicts are produced server-side, so the agent has to ask for them."""
    fake = FakeRequests(FakeResponse({"entries": [_entry(), _entry("get_order", "WARN")]}))
    monkeypatch.setattr(demo_agent, "requests", fake)
    path = tmp_path / "out" / "run.json"

    save_recording(path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[1]["verdict"]["status"] == "WARN"
    assert fake.gets[0].endswith("/audit")


def test_save_recording_creates_its_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_agent, "requests", FakeRequests(FakeResponse({"entries": []})))
    path = tmp_path / "deep" / "nested" / "run.json"

    save_recording(path)

    assert path.exists()


def test_save_recording_falls_back_to_events_when_the_server_is_unreachable(
    tmp_path, monkeypatch
):
    """Degraded, and it says so -- the file will not drive --offline."""
    monkeypatch.setattr(demo_agent, "requests", FakeRequests(raises=True))
    monkeypatch.setattr(demo_agent, "_recorded", [{"id": "evt_1", "tool": "search_docs"}])
    path = tmp_path / "run.json"

    save_recording(path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[0]["verdict"] is None


def test_a_recording_saved_offline_cannot_then_drive_offline_mode(tmp_path, monkeypatch):
    """End to end on the failure case: a verdict-less recording is refused
    later rather than silently replaying a partial run."""
    monkeypatch.setattr(demo_agent, "requests", FakeRequests(raises=True))
    monkeypatch.setattr(demo_agent, "_recorded", [{"id": "evt_1", "tool": "search_docs"}])
    path = tmp_path / "run.json"
    save_recording(path)

    with pytest.raises(SystemExit):
        offline(path, pace=0)


# -- the pipeline itself ----------------------------------------------------

def test_the_scripted_pipeline_emits_every_verdict_class(monkeypatch):
    """The demo's premise: one run produces green, amber, and red.

    Pinned because the scenario is the story told on stage. If a step is
    removed or renamed, the narration stops matching the screen.
    """
    import decorator

    events: list[dict] = []
    decorator.subscribe(events.append)
    monkeypatch.setattr(demo_agent, "requests", FakeRequests())

    demo_agent.run_pipeline()

    tools = [e["tool"] for e in events]
    assert tools == [
        "search_docs",
        "lookup_customer",
        "fetch_pricing",            # slow -> WARN
        "summarize",                # off-goal -> WARN
        # Four hallucinations, four different capabilities. Same-capability
        # names would collapse to one graph node and one lesson.
        "delete_user_record",       # -> delete_records
        "issue_refund",             # -> issue_refunds
        "notify_customer",          # -> notify_customers
        "escalate_to_supervisor",   # -> escalate_to_a_human
        "fetch_pricing",            # the loop: three byte-identical calls
        "fetch_pricing",
        "fetch_pricing",
        "flaky_api",                # registered, but raises -> ANOMALY
    ]


def test_the_hallucinated_steps_span_four_distinct_capabilities():
    """The graph abstracts an invented tool to the capability behind it. If these
    four ever collapse onto one capability, the demo graph loses three nodes and
    three lessons and starts looking hardcoded."""
    from knowledge_graph import classify_capability

    caps = {
        classify_capability(t)
        for t in (
            "delete_user_record",
            "issue_refund",
            "notify_customer",
            "escalate_to_supervisor",
        )
    }

    assert caps == {
        "delete_records",
        "issue_refunds",
        "notify_customers",
        "escalate_to_a_human",
    }


def test_the_three_looping_calls_are_byte_identical(monkeypatch):
    """If they differ, the deterministic fingerprint will not match and the
    loop -- the clearest thing in the whole demo -- silently stops escalating."""
    import decorator
    from session_context import SessionContext

    events: list[dict] = []
    decorator.subscribe(events.append)
    monkeypatch.setattr(demo_agent, "requests", FakeRequests())

    demo_agent.run_pipeline()

    loop_calls = [e for e in events if e["tool"] == "fetch_pricing"][1:]
    fingerprints = {SessionContext.fingerprint(e) for e in loop_calls}
    assert len(loop_calls) == 3
    assert len(fingerprints) == 1


def test_the_pipeline_reraises_nothing_to_its_caller(monkeypatch):
    """flaky_api raises by design; the demo swallows it. If that leaked, the
    run would end early and the last node would never appear."""
    monkeypatch.setattr(demo_agent, "requests", FakeRequests())

    demo_agent.run_pipeline()  # must not raise


def test_declare_goal_and_send_never_raise_when_the_server_is_down(monkeypatch):
    monkeypatch.setattr(demo_agent, "requests", FakeRequests(raises=True))

    demo_agent.declare_goal()
    demo_agent.send({"tool": "x", "error": None, "duration_ms": 1.0})
