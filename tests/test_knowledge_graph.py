"""The knowledge graph is what turns detection into memory.

Every lesson injected back into an agent's prompt is derived from this file, so
a wrong classification here does not surface as an error -- it surfaces as an
agent being confidently taught something false.
"""

from __future__ import annotations

import json

import pytest

from knowledge_graph import (
    EXCEPTION,
    GOAL_DRIFT,
    HALLUCINATED_TOOL,
    INEFFICIENT,
    INFINITE_LOOP,
    KnowledgeGraph,
    classify_capability,
    classify_failure,
)

KNOWN = ["search_docs", "lookup_customer", "get_order"]


@pytest.fixture
def graph(tmp_path):
    """A graph with a throwaway store. Never touches the real one."""
    return KnowledgeGraph(path=tmp_path / "graph.json")


def _event(tool="search_docs", error=None, **extra):
    return {"id": "evt_1", "tool": tool, "input": {"args": [], "kwargs": {}},
            "error": error, "duration_ms": 60.0, **extra}


def _verdict(status="ANOMALY", explanation="something went wrong", **extra):
    return {"status": status, "explanation": explanation, "confidence": 0.9,
            "degraded": False, **extra}


# -- classify_capability ----------------------------------------------------

@pytest.mark.parametrize(
    "tool, expected",
    [
        ("/v1/orders/refund", "issue_refunds"),
        ("/v1/refunds/create", "issue_refunds"),
        ("reimburse_customer", "issue_refunds"),
        ("money-back", "issue_refunds"),
        ("/v1/notifications/send", "notify_customers"),
        ("send_email", "notify_customers"),
        ("sms_gateway", "notify_customers"),
        ("/v1/support/escalate", "escalate_to_a_human"),
        ("contact_supervisor", "escalate_to_a_human"),
        ("create_ticket", "escalate_to_a_human"),
        ("/v1/orders/cancel", "cancel_orders"),
        ("delete_user_record", "delete_records"),
        ("purge_logs", "delete_records"),
        ("/v1/billing/charge", "process_payments"),
        ("create_invoice", "process_payments"),
        ("update_address", "write_data"),
        ("patch_order", "write_data"),
    ],
)
def test_classify_capability_maps_endpoints_to_capabilities(tool, expected):
    assert classify_capability(tool) == expected


def test_refund_status_lands_on_refund_not_something_else():
    """Ordering matters: 'refund-status' must not fall through to write_data.

    The whole point of capability abstraction is that the agent invents a
    different path every run. If near-miss variants classify differently, the
    counts scatter and no lesson ever reaches a useful weight.
    """
    assert classify_capability("/v1/orders/refund-status") == "issue_refunds"
    assert classify_capability("/v1/orders/refund/create") == "issue_refunds"


def test_classify_capability_is_case_insensitive():
    assert classify_capability("/V1/Orders/REFUND") == "issue_refunds"


@pytest.mark.parametrize("tool", ["", "search_docs", "frobnicate", "/v1/quux"])
def test_unrecognised_capability_is_named_not_guessed(tool):
    """No match returns an explicit placeholder rather than a wrong bucket."""
    assert classify_capability(tool) == "an_unrecognised_capability"


# -- classify_failure -------------------------------------------------------

def test_unregistered_tool_is_a_hallucination():
    assert classify_failure(_event(tool="invented_tool"), _verdict(), KNOWN) == HALLUCINATED_TOOL


def test_registered_tool_is_never_a_hallucination():
    assert classify_failure(_event(tool="search_docs"), _verdict(), KNOWN) != HALLUCINATED_TOOL


def test_empty_registry_cannot_prove_a_hallucination():
    """With no registry, every tool would look invented. Fall through instead."""
    assert classify_failure(_event(tool="anything"), _verdict(), []) == INEFFICIENT


def test_loop_is_read_from_the_verdict_language():
    for phrasing in ("indicating an infinite loop", "repeated identical call"):
        verdict = _verdict(explanation=phrasing)
        assert classify_failure(_event(), verdict, KNOWN) == INFINITE_LOOP


def test_exception_is_detected_from_the_event():
    event = _event(error="PermissionError: endpoint not permitted")
    assert classify_failure(event, _verdict(explanation="it raised"), KNOWN) == EXCEPTION


def test_goal_drift_is_read_from_the_verdict_language():
    verdict = _verdict(explanation="the agent has drifted from the stated goal")
    assert classify_failure(_event(), verdict, KNOWN) == GOAL_DRIFT


def test_unclassifiable_failure_falls_back_to_inefficient():
    assert classify_failure(_event(), _verdict(explanation="odd"), KNOWN) == INEFFICIENT


def test_hallucination_outranks_every_other_signal():
    """An invented tool that also raised and also looped is still a hallucination
    -- the deterministic fact wins over the model's wording."""
    event = _event(tool="invented", error="boom")
    verdict = _verdict(explanation="a repeated call, and it drifted from the goal")
    assert classify_failure(event, verdict, KNOWN) == HALLUCINATED_TOOL


def test_loop_outranks_a_raised_exception():
    """Pins current precedence: loop language is checked before event error."""
    event = _event(error="TimeoutError: slow")
    assert classify_failure(event, _verdict(explanation="a loop"), KNOWN) == INFINITE_LOOP


def test_classify_failure_survives_missing_fields():
    assert classify_failure({}, {}, KNOWN) == INEFFICIENT
    assert classify_failure({}, {"explanation": None}, KNOWN) == INEFFICIENT


# -- ingest -----------------------------------------------------------------

def test_healthy_verdicts_are_not_remembered(graph):
    assert graph.ingest(_event(), _verdict(status="OK"), KNOWN) is None
    assert graph.summary()["nodes"] == 0


def test_degraded_verdicts_are_not_remembered(graph):
    """A degraded verdict means we could not look. Remembering it would teach a
    lesson about our own outage rather than the agent's behaviour."""
    verdict = _verdict(status="WARN", explanation="Meta-agent unavailable", degraded=True)

    assert graph.ingest(_event(), verdict, KNOWN) is None
    assert graph.summary()["nodes"] == 0


def test_ingest_returns_the_derived_facts(graph):
    learned = graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)

    assert learned == {
        "tool": "/v1/orders/refund",
        "failure_mode": HALLUCINATED_TOOL,
        "capability": "issue_refunds",
    }


def test_ingest_builds_the_full_edge_set_for_a_hallucination(graph):
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN, goal="issue a refund")

    snap = graph.snapshot()
    relations = {(e["src_id"], e["relation"], e["dst_id"]) for e in snap["edges"]}
    assert ("/v1/orders/refund", "exhibits", HALLUCINATED_TOOL) in relations
    assert ("/v1/orders/refund", "requires", "issue_refunds") in relations
    assert ("issue_refunds", "missing_in", "issue a refund") in relations


def test_non_hallucinations_do_not_imply_a_missing_capability(graph):
    """A loop on a legitimate tool is not a capability gap."""
    graph.ingest(_event(tool="search_docs"), _verdict(explanation="a loop"), KNOWN, goal="g")

    types = graph.summary()["by_type"]
    assert "capability" not in types
    assert "goal" not in types


def test_goal_edge_is_omitted_when_no_goal_was_declared(graph):
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN, goal="")

    assert "goal" not in graph.summary()["by_type"]


def test_long_goals_are_truncated_for_the_node_id(graph):
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN, goal="g" * 500)

    goal_nodes = [n for n in graph.snapshot()["nodes"] if n["type"] == "goal"]
    assert len(goal_nodes[0]["id"]) == 160


def test_missing_tool_name_becomes_a_placeholder(graph):
    learned = graph.ingest({}, _verdict(), KNOWN)

    assert learned["tool"] == "unknown_tool"


def test_repeat_ingestion_increments_counts_rather_than_duplicating(graph):
    for _ in range(3):
        graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)

    snap = graph.snapshot()
    tool_nodes = [n for n in snap["nodes"] if n["type"] == "tool"]
    assert len(tool_nodes) == 1
    assert tool_nodes[0]["count"] == 3
    exhibits = [e for e in snap["edges"] if e["relation"] == "exhibits"]
    assert exhibits[0]["count"] == 3


# -- lessons ----------------------------------------------------------------

def test_lessons_rank_by_how_often_a_capability_was_reached_for(graph):
    for _ in range(3):
        graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)
    graph.ingest(_event(tool="/v1/support/escalate"), _verdict(), KNOWN)

    lessons = graph.lessons()

    assert "issue refunds" in lessons[0]
    assert "escalate to a human" in lessons[1]


def test_lesson_names_the_count_and_the_invented_endpoints(graph):
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)
    graph.ingest(_event(tool="/v1/refunds/create"), _verdict(), KNOWN)

    lesson = graph.lessons()[0]

    assert "2 previous attempt" in lesson
    assert "/v1/orders/refund" in lesson and "/v1/refunds/create" in lesson
    # A prohibition with no alternative just stalls the run.
    assert "requires a human" in lesson


def test_loop_lessons_are_produced_for_repeatedly_looping_tools(graph):
    for _ in range(2):
        graph.ingest(_event(tool="get_order"), _verdict(explanation="a loop"), KNOWN)

    lesson = graph.lessons()[0]

    assert "get_order" in lesson and "2 time(s)" in lesson


def test_unrecognised_capability_lesson_names_tools_not_a_fake_capability(graph):
    """The template for a recognised capability produced "You have NO tool that
    can an unrecognised capability" when nothing matched -- ungrammatical, and it
    asserted a missing capability that was never identified. Name what we know."""
    for _ in range(2):
        graph.ingest(_event(tool="flaky_api", error="ConnectionError: 503"), _verdict(), KNOWN)

    lesson = next(l for l in graph.lessons() if "flaky_api" in l)

    assert "NO tool that can an" not in lesson
    assert "unrecognised capability" not in lesson
    assert "'flaky_api'" in lesson
    assert "NOT in your tool registry" in lesson


def test_lesson_calls_a_bare_tool_a_tool_and_a_path_an_endpoint(graph):
    """Describing a bare function name as "an endpoint" is a small inaccuracy in
    text a model is asked to act on."""
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)
    graph.ingest(_event(tool="delete_user_record"), _verdict(), KNOWN)

    lessons = graph.lessons()
    refund = next(l for l in lessons if "issue refunds" in l)
    delete = next(l for l in lessons if "delete records" in l)

    assert "an endpoint for it was invented" in refund
    assert "a tool for it was invented" in delete


def test_a_tool_that_is_both_unregistered_and_raised_records_both(graph):
    """classify_failure returns one primary mode, but the graph should hold every
    fact about the step -- not just the winning one."""
    graph.ingest(_event(tool="flaky_api", error="ConnectionError: 503"), _verdict(), KNOWN)

    modes = {n["id"] for n in graph.snapshot()["nodes"] if n["type"] == "failure_mode"}

    assert HALLUCINATED_TOOL in modes
    assert EXCEPTION in modes


def test_a_clean_history_says_so_rather_than_returning_nothing(graph):
    graph.start_run()

    assert "No recurring failures" in graph.lessons()[0]


def test_no_runs_and_no_failures_produces_no_lessons(graph):
    assert graph.lessons() == []
    assert graph.lesson_block() == ""


def test_lessons_respect_the_limit(graph):
    for path in ("/refund", "/notify", "/escalate", "/cancel", "/delete", "/charge", "/update"):
        graph.ingest(_event(tool=path), _verdict(), KNOWN)

    assert len(graph.lessons(limit=3)) == 3


def test_lesson_block_is_labelled_as_observed_fact(graph):
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)

    block = graph.lesson_block()

    assert block.startswith("LESSONS FROM PREVIOUS RUNS")
    assert "not suggestions" in block
    assert "1. " in block


# -- persistence ------------------------------------------------------------

def test_save_and_reload_round_trips_the_graph(tmp_path):
    path = tmp_path / "nested" / "graph.json"
    original = KnowledgeGraph(path=path)
    original.start_run()
    original.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN, goal="refund it")
    original.save()

    reloaded = KnowledgeGraph(path=path)

    assert reloaded.summary() == original.summary()
    assert reloaded.lessons() == original.lessons()


def test_save_creates_the_directory_it_needs(tmp_path):
    path = tmp_path / "does" / "not" / "exist" / "graph.json"

    KnowledgeGraph(path=path).save()

    assert path.exists()


def test_a_missing_store_is_an_empty_graph_not_an_error(tmp_path):
    assert KnowledgeGraph(path=tmp_path / "absent.json").summary()["nodes"] == 0


@pytest.mark.parametrize(
    "content",
    [
        "{not json",                                    # unparseable
        "",                                             # empty file
        "[]",                                           # valid JSON, wrong type
        '"a string"',                                   # valid JSON, wrong type
        '{"nodes": []}',                                # valid but empty
        '{"nodes": [{"type": "tool"}]}',                # node missing "id"
        '{"nodes": "not a list"}',                      # wrong inner type
        '{"edges": [{"src_type": "tool"}]}',            # edge missing keys
        '{"runs": "seven"}',                            # wrong scalar type
    ],
)
def test_a_corrupt_store_starts_fresh_instead_of_refusing_to_boot(tmp_path, content):
    """Losing accumulated memory is recoverable. A server that won't start is not.

    KnowledgeGraph() is constructed at import and inside create_app, so anything
    that raises in _load takes the whole server down at boot.
    """
    path = tmp_path / "graph.json"
    path.write_text(content, encoding="utf-8")

    graph = KnowledgeGraph(path=path)

    assert graph.summary()["nodes"] == 0
    assert graph.summary()["runs"] == 0
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)  # still usable
    assert graph.summary()["nodes"] == 3


def test_clear_wipes_memory_and_deletes_the_store(tmp_path):
    path = tmp_path / "graph.json"
    graph = KnowledgeGraph(path=path)
    graph.start_run()
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN)
    graph.save()
    assert path.exists()

    graph.clear()

    assert not path.exists()
    assert graph.summary() == {"runs": 0, "nodes": 0, "edges": 0, "by_type": {}}


def test_clear_is_safe_when_nothing_was_ever_saved(tmp_path):
    KnowledgeGraph(path=tmp_path / "never.json").clear()  # must not raise


def test_snapshot_is_json_serialisable(graph):
    """The server returns this straight over HTTP."""
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN, goal="g")

    assert json.loads(json.dumps(graph.snapshot()))["runs"] == 0


def test_summary_counts_nodes_by_type(graph):
    graph.start_run()
    graph.ingest(_event(tool="/v1/orders/refund"), _verdict(), KNOWN, goal="refund it")

    summary = graph.summary()

    assert summary["runs"] == 1
    assert summary["by_type"] == {"tool": 1, "failure_mode": 1, "capability": 1, "goal": 1}
    assert summary["edges"] == 3
