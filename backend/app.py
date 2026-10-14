"""SentinelMind server: ingests trace events, judges them, streams verdicts.

    POST /trace          a monitored agent submits one trace event
    POST /replay         a pre-judged event/verdict pair, no API call (offline mode)
    GET  /health         liveness probe
    GET  /audit          the structured audit log
    GET  /audit/export   the log as a downloadable JSON file
    POST /audit/clear    reset between demo runs
    POST /guard/check    guard mode: may this step run? (allow/block/pending/halt)
    GET  /guard/state    strikes, halt state, pending approvals
    GET/POST /guard/approval/<id>   read or decide a pending human approval
    GET  /               the live dashboard

Verdicts are pushed to connected dashboards over WebSocket as ``verdict`` events.
Evaluation runs on a worker thread so the monitored agent's POST returns
immediately -- observing an agent must not slow it down.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

from audit_log import AuditLog
from guard import BLOCK, HALT, Guard
from knowledge_graph import KnowledgeGraph
from path_graph import PathGraph
from meta_agent import MetaAgent
from session_context import SessionContext

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / 'frontend_v2' / 'dist'

# Load GROQ_API_KEY from the repo-root .env before MetaAgent builds its client.
load_dotenv(ROOT / ".env")

# Tools the monitored pipelines are allowed to call. Anything outside this set is
# a hallucinated tool call; the registry is passed to the meta-agent so it can
# name the offending tool in its explanation.
#
# Covers both subjects: demo_agent.py (scripted, for reliable stage demos) and
# real_agent.py (a genuine tool-calling LLM agent). Endpoints reachable through
# the real agent's internal-API dispatcher are registered individually -- an
# endpoint the agent invents will not appear here, which is what makes an
# invented capability detectable rather than merely suspicious.
KNOWN_TOOLS = [
    # shared
    "search_docs",
    "lookup_customer",
    # scripted demo pipeline
    "fetch_pricing",
    "summarize",
    # Registered on purpose. flaky_api is a legitimate-but-unreliable upstream,
    # which is what it would be in a real pipeline. Leaving it unregistered made
    # its verdict read as a hallucinated tool, so step 7 of the demo duplicated
    # step 5 instead of demonstrating a swallowed exception -- three planted
    # failure modes collapsing into two.
    "flaky_api",
    # real agent
    "get_order",
    "agent_llm_call",
    # The agent's own name for its HTTP tool. Each call is traced as
    # internal_api:<endpoint>, so invented endpoints are still unregistered --
    # but the model_call that *chooses* this tool mentions it by name, and
    # leaving it out made every such planning step read as a hallucination.
    "call_internal_api",
    "internal_api:/v1/orders/list",
    "internal_api:/v1/customers/search",
    # real agent, --rogue: tools with real side effects. Registered, so using
    # them is not a hallucination -- whether a given use is justified is the
    # question guard mode asks before they run.
    "refund_order",
    "erase_customer_data",
    "email_customer",
]

def _tool_set(env: str, default: str) -> set[str]:
    return {t.strip() for t in os.environ.get(env, default).split(",") if t.strip()}


# Judged before they run (guard mode). They move money or change records.
RISKY_TOOLS = _tool_set("SENTINEL_RISKY_TOOLS", "refund_order")
# Never run on a model's say-so: a human approves each call on the dashboard.
APPROVAL_TOOLS = _tool_set("SENTINEL_APPROVAL_TOOLS", "erase_customer_data")


def _blocked_verdict(event: dict) -> dict:
    """The verdict for a step the guard stopped. No model call: the decision
    was already made, and its reason is the explanation."""
    g = event.get("guard") or {}
    pre = g.get("verdict") or {}
    return {
        "status": "BLOCKED",
        "explanation": g.get("reason", "Stopped by SentinelMind before it ran."),
        "confidence": float(pre.get("confidence", 1.0)),
        "latency_ms": 0.0,
        "blocked": True,
        "rule": g.get("rule", ""),
        "halted": g.get("action") == HALT,
    }


def create_app(
    meta_agent: MetaAgent | None = None,
    audit_log: AuditLog | None = None,
    knowledge_graph: KnowledgeGraph | None = None,
    guard: Guard | None = None,
) -> tuple[Flask, SocketIO]:
    """Build the app. Dependencies are injectable so tests can pass fakes."""
    app = Flask(__name__, static_folder=None)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    @app.after_request
    def _gzip_json(resp):
        """Compress larger JSON answers (/knowledge, /audit) when the client accepts it.

        Built assets are precompressed at build time; API responses are dynamic,
        so they are compressed here. Small bodies are left alone -- gzip costs
        more than it saves under ~1 KB.
        """
        import gzip

        if (
            resp.mimetype == "application/json"
            and not resp.direct_passthrough
            and "gzip" in request.headers.get("Accept-Encoding", "")
            and "Content-Encoding" not in resp.headers
            and resp.content_length
            and resp.content_length > 1024
        ):
            resp.set_data(gzip.compress(resp.get_data(), compresslevel=6))
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers["Vary"] = "Accept-Encoding"
        return resp

    app.config["AUDIT_LOG"] = audit_log or AuditLog()
    # Accumulated failure memory. Injected so tests get a throwaway graph and
    # never touch the persisted one on disk.
    app.config["KNOWLEDGE"] = knowledge_graph or KnowledgeGraph()
    app.config["META_AGENT"] = meta_agent or MetaAgent(
        known_tools=KNOWN_TOOLS,
        confidence_threshold=float(os.environ.get("SENTINEL_CONFIDENCE_THRESHOLD", 0.0)),
    )
    # Loops and goal drift are cross-step properties -- the meta-agent needs the
    # run so far, not just the current step, to see either.
    app.config["SESSION"] = SessionContext(
        window=int(os.environ.get("SENTINEL_CONTEXT_WINDOW", 8))
    )

    app.config["GUARD"] = guard or Guard(
        KNOWN_TOOLS,
        meta_agent=app.config["META_AGENT"],
        memory=app.config["KNOWLEDGE"],
        learned_store=ROOT / "knowledge" / "path_learned.json",
        path_timeout_action=os.environ.get("SENTINEL_PATH_TIMEOUT_ACTION", "automate"),
        risky_tools=RISKY_TOOLS,
        approval_tools=APPROVAL_TOOLS,
        max_strikes=int(os.environ.get("SENTINEL_GUARD_MAX_STRIKES", 4)),
        min_confidence=float(os.environ.get("SENTINEL_GUARD_MIN_CONFIDENCE", 0.6)),
    )

    work: queue.Queue = queue.Queue()
    app.config["WORK_QUEUE"] = work
    # Which run is current. Clearing the log or declaring a new goal starts a new
    # run; events still queued from the old one are dropped instead of judged.
    # Under a rate limit the queue can hold minutes of work, and without this a
    # finished run's verdicts landed in the next run -- and cost tokens nobody saw.
    app.config["RUN_EPOCH"] = 0

    def worker() -> None:
        """Drain trace events, evaluate, record, broadcast."""
        while True:
            event = work.get()
            if event is None:
                break
            if event.pop("_epoch", app.config["RUN_EPOCH"]) != app.config["RUN_EPOCH"]:
                work.task_done()
                continue
            try:
                session: SessionContext = app.config["SESSION"]
                g = event.get("guard") or {}
                if g.get("action") in (BLOCK, HALT):
                    verdict = _blocked_verdict(event)
                elif g.get("verdict"):
                    # Judged before it ran and allowed: reuse that verdict rather
                    # than paying for the same judgement twice.
                    verdict = {**g["verdict"], "prechecked": True}
                else:
                    verdict = app.config["META_AGENT"].evaluate(event, context=session)
                # Record after judging, so a step never sees itself as a repeat.
                session.record(event, verdict)
                entry = app.config["AUDIT_LOG"].record(event, verdict)
                socketio.emit("verdict", entry)
                socketio.emit("summary", app.config["AUDIT_LOG"].summary())
                tripped = app.config["GUARD"].note_verdict(event, verdict)
                if tripped:
                    socketio.emit("halted", tripped)

                # Turn detection into memory. Only mistakes are remembered, and
                # only ones we actually judged -- see KnowledgeGraph.ingest.
                graph: KnowledgeGraph = app.config["KNOWLEDGE"]
                learned = graph.ingest(event, verdict, KNOWN_TOOLS, session.goal)
                if learned:
                    graph.save()
                    socketio.emit("learned", {**learned, "summary": graph.summary()})
            except Exception as exc:
                # Never let one bad event kill the worker and silently stop all
                # monitoring -- that is the exact failure mode we exist to catch.
                socketio.emit(
                    "server_error",
                    {"message": f"{type(exc).__name__}: {exc}", "event": event},
                )
            finally:
                work.task_done()

    threading.Thread(target=worker, daemon=True, name="sentinel-worker").start()

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "sentinelmind",
                "model": app.config["META_AGENT"].model,
                # "untested" until the first call lands. Surfaced so you know
                # whether you are demoing strict schema enforcement or the
                # weaker json_object fallback.
                "structured_output": app.config["META_AGENT"].structured_output_mode,
                "events_logged": len(app.config["AUDIT_LOG"]),
            }
        ), 200

    @app.post("/trace")
    def trace():
        """Accept one trace event from a monitored agent and queue it."""
        event = request.get_json(silent=True)
        if not isinstance(event, dict) or "tool" not in event:
            return jsonify({"error": "expected a trace event object with a 'tool' field"}), 400

        socketio.emit("trace", event)  # draw the node immediately, grey
        # The guard's own record, written now -- judging below may lag by seconds.
        app.config["GUARD"].observe(event)
        if app.config["GUARD"].path:
            socketio.emit("path", app.config["GUARD"].path_state())
        work.put({**event, "_epoch": app.config["RUN_EPOCH"]})
        return jsonify({"accepted": True, "event_id": event.get("id")}), 202

    @app.post("/replay")
    def replay_entry():
        """Accept a pre-judged event/verdict pair and push it straight through.

        This is the true offline fallback. ``/trace`` queues an event for the
        meta-agent, which means it needs the API to be reachable -- exactly the
        thing that fails when the venue wifi dies. This path skips the meta-agent
        entirely and replays a verdict recorded earlier, so a demo survives a dead
        network or a dead provider.

        The verdict is stamped ``replayed: true`` so the dashboard can say so.
        Passing off a recorded verdict as a live one would be dishonest, and the
        audit log is supposed to be the record of truth.
        """
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "expected an object with 'event' and 'verdict'"}), 400

        event = payload.get("event")
        verdict = payload.get("verdict")
        if not isinstance(event, dict) or not isinstance(verdict, dict):
            return jsonify({"error": "'event' and 'verdict' must both be objects"}), 400

        verdict = {**verdict, "replayed": True}

        socketio.emit("trace", event)
        # Record into the session window too, so /session stays coherent during a
        # replay and a subsequent live step sees the right history.
        app.config["SESSION"].record(event, verdict)
        entry = app.config["AUDIT_LOG"].record(event, verdict)
        socketio.emit("verdict", entry)
        socketio.emit("summary", app.config["AUDIT_LOG"].summary())
        return jsonify({"replayed": True, "event_id": event.get("id")}), 202

    @app.post("/session/goal")
    def set_goal():
        """Declare what the monitored agent is supposed to accomplish.

        Without this, goal drift is unfalsifiable -- there is nothing to drift
        from, and the meta-agent is told so explicitly.
        """
        payload = request.get_json(silent=True) or {}
        goal = str(payload.get("goal", "")).strip()
        if not goal:
            return jsonify({"error": "expected a non-empty 'goal' field"}), 400

        session: SessionContext = app.config["SESSION"]
        session.goal = goal
        session.clear()  # a new goal is a new run
        app.config["RUN_EPOCH"] += 1
        app.config["GUARD"].reset(goal)
        app.config["KNOWLEDGE"].start_run()
        socketio.emit("goal", {"goal": goal})
        return jsonify({"goal": goal}), 200

    @app.get("/session")
    def session_state():
        session: SessionContext = app.config["SESSION"]
        return jsonify(
            {
                "goal": session.goal,
                "window": session.window,
                "recent": session.recent(),
            }
        ), 200

    @app.get("/knowledge")
    def knowledge():
        """The accumulated failure graph: nodes, edges, and derived lessons."""
        graph: KnowledgeGraph = app.config["KNOWLEDGE"]
        return jsonify(
            {
                "summary": graph.summary(),
                "lessons": graph.lessons(),
                **graph.snapshot(),
            }
        ), 200

    @app.get("/knowledge/lessons")
    def knowledge_lessons():
        """What a monitored agent fetches to avoid repeating past mistakes."""
        graph: KnowledgeGraph = app.config["KNOWLEDGE"]
        return jsonify(
            {"lessons": graph.lessons(), "prompt_block": graph.lesson_block()}
        ), 200

    @app.post("/knowledge/clear")
    def knowledge_clear():
        """Reset accumulated memory -- needed to measure a cold baseline.

        Requires ``{"confirm": true}``. Unlike ``/audit/clear``, which drops one
        run's verdicts, this deletes the graph file and every lesson learned
        across all previous runs -- memory that costs real tokens to rebuild, and
        that the free tier's daily cap makes expensive to rebuild twice. An
        explicit flag means a stray POST, or a dashboard button wired without
        thinking, cannot silently erase it.
        """
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm") is not True:
            return jsonify(
                {"error": "expected {\"confirm\": true} -- this deletes all accumulated memory"}
            ), 400

        app.config["KNOWLEDGE"].clear()
        socketio.emit("knowledge_cleared", {})
        return jsonify({"cleared": True}), 200

    @app.get("/audit")
    def audit():
        log: AuditLog = app.config["AUDIT_LOG"]
        status = request.args.get("status")
        entries = log.filter(status) if status else log.all()
        return jsonify({"summary": log.summary(), "entries": entries}), 200

    @app.get("/audit/export")
    def audit_export():
        payload = app.config["AUDIT_LOG"].export()
        return (
            payload,
            200,
            {
                "Content-Type": "application/json",
                "Content-Disposition": "attachment; filename=sentinelmind-audit.json",
            },
        )

    @app.post("/audit/clear")
    def audit_clear():
        app.config["AUDIT_LOG"].clear()
        app.config["SESSION"].clear()
        app.config["RUN_EPOCH"] += 1
        app.config["GUARD"].reset()
        socketio.emit("cleared", {})
        return jsonify({"cleared": True}), 200

    # -- guard mode ---------------------------------------------------------

    @app.post("/guard/check")
    def guard_check():
        """May this step run? Called by the decorator before the tool executes.

        Synchronous on purpose: the agent waits for the answer. Rule checks are
        instant; only risky tools pay for a judge call.
        """
        call = request.get_json(silent=True)
        if not isinstance(call, dict) or "tool" not in call:
            return jsonify({"error": "expected a call object with a 'tool' field"}), 400
        guard: Guard = app.config["GUARD"]
        decision = guard.check(call)
        if decision["action"] == "pending":
            socketio.emit("approval_request", {
                "id": decision["approval_id"], "tool": call.get("tool"),
                "input": call.get("input"), "reason": decision.get("reason"),
                "kind": decision.get("kind", "approval"), "finding": decision.get("finding"),
                "expected": [n["label"] for n in guard.path.next_steps()] if guard.path else [],
            })
        if guard.path:
            socketio.emit("path", guard.path_state())
        if decision.get("halted") or decision["action"] == HALT:
            socketio.emit("halted", {"halted": True, "reason": guard.halt_reason, "strikes": guard.strikes})
        return jsonify(decision), 200

    # -- the right path -----------------------------------------------------

    @app.get("/path/state")
    def path_state():
        """The active right path, where the run is on it, and proposed additions."""
        state = app.config["GUARD"].path_state()
        if state is None:
            return jsonify({"active": False, "available": [p.stem for p in PathGraph.available()]}), 200
        return jsonify({"active": True, **state}), 200

    @app.post("/path/automate")
    def path_automate():
        """Autopilot on/off: steer off-path moves without asking each time."""
        payload = request.get_json(silent=True) or {}
        on = payload.get("on")
        if not isinstance(on, bool):
            return jsonify({"error": "expected {\"on\": true|false}"}), 400
        guard: Guard = app.config["GUARD"]
        if not guard.set_automate(on):
            return jsonify({"error": "no right path is active for this goal"}), 409
        socketio.emit("path", guard.path_state())
        return jsonify({"automate": on}), 200

    @app.post("/path/proposals/<proposal_id>")
    def path_proposal(proposal_id: str):
        """Accept or reject a step the user let through, as a permanent path addition."""
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload.get("accept"), bool):
            return jsonify({"error": "expected {\"accept\": true|false}"}), 400
        guard: Guard = app.config["GUARD"]
        outcome = guard.resolve_proposal(proposal_id, payload["accept"])
        if outcome is None:
            return jsonify({"error": "unknown or already resolved proposal"}), 404
        if guard.path:
            socketio.emit("path", guard.path_state())
        return jsonify(outcome), 200

    @app.get("/guard/state")
    def guard_state():
        return jsonify(app.config["GUARD"].state()), 200

    @app.get("/guard/approval/<approval_id>")
    def guard_approval_status(approval_id: str):
        guard: Guard = app.config["GUARD"]
        status = guard.approval_status(approval_id)
        if status is None:
            return jsonify({"error": "unknown approval id"}), 404
        body = {"id": approval_id, "status": status}
        decision = guard.approvals[approval_id].get("decision")
        if decision:
            body["decision"] = decision
        return jsonify(body), 200

    @app.post("/guard/approval/<approval_id>")
    def guard_approval_decide(approval_id: str):
        """A human's decision (dashboard), or the agent's timeout (deny)."""
        payload = request.get_json(silent=True) or {}
        choice = payload.get("decision")
        guard: Guard = app.config["GUARD"]
        entry = guard.approvals.get(approval_id)
        is_deviation = bool(entry and entry.get("kind") == "deviation")
        allowed = ("automate", "continue", "stop") if is_deviation else ("approve", "deny")
        if choice not in allowed and not payload.get("timed_out"):
            return jsonify({"error": f"expected decision to be one of {', '.join(allowed)}"}), 400
        if payload.get("timed_out"):
            outcome = guard.expire(approval_id)
        elif is_deviation:
            outcome = guard.decide_deviation(approval_id, choice)
        else:
            outcome = guard.decide(approval_id, approve=choice == "approve")
        if outcome is None:
            status = guard.approval_status(approval_id)
            if status is None:
                return jsonify({"error": "unknown approval id"}), 404
            return jsonify({"error": f"already {status}"}), 409
        if payload.get("timed_out") and outcome["action"] == "block" and not is_deviation:
            tool = guard.approvals[approval_id]["tool"]
            outcome["rule"] = "approval_timeout"
            outcome["reason"] = (f"Blocked by SentinelMind: nobody approved {tool} in time, so it "
                                 f"did not run. Do not retry it. Tell the user it was not done and "
                                 f"that a person will follow up.")
        guard.approvals[approval_id]["decision"] = outcome
        socketio.emit("approval_resolved", {"id": approval_id, "decision": choice,
                                            "timed_out": bool(payload.get("timed_out"))})
        if guard.path:
            socketio.emit("path", guard.path_state())
        if outcome.get("halted"):
            socketio.emit("halted", {"halted": True, "reason": guard.halt_reason, "strikes": guard.strikes})
        return jsonify(outcome), 200

    @app.get("/")
    def dashboard():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:path>")
    def spa_catchall(path):
        """Serve the React SPA for any unknown path (enables client-side routing).

        Explicit API prefixes are excluded so Flask routes registered above always
        win. Anything else either resolves to a real static file (JS/CSS/images)
        in the dist folder, or falls through to index.html for React Router.
        """
        # Never intercept known API prefixes -- let Flask's earlier routes handle them.
        _api_prefixes = (
            "trace", "audit", "session", "knowledge", "health",
            "socket.io", "static",
        )
        if any(path == p or path.startswith(p + "/") for p in _api_prefixes):
            from flask import abort
            abort(404)

        target = FRONTEND_DIR / path
        if target.exists():
            return _static(path)
        return send_from_directory(FRONTEND_DIR, "index.html")

    def _static(path: str):
        """A built asset, gzipped when the browser accepts it.

        The build writes ``<file>.gz`` next to each asset. Serving raw was the
        top Lighthouse finding: a 326 KB script and 52 KB of CSS sent
        uncompressed, which on a throttled phone pushed first paint past 10s.
        Precompressing at build time costs nothing per request. Hashed files
        under /assets/ never change, so they are cached for a year.
        """
        import mimetypes

        gz = FRONTEND_DIR / f"{path}.gz"
        accepts = "gzip" in request.headers.get("Accept-Encoding", "")
        if accepts and gz.exists():
            resp = send_from_directory(FRONTEND_DIR, f"{path}.gz")
            resp.headers["Content-Encoding"] = "gzip"
            resp.mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        else:
            resp = send_from_directory(FRONTEND_DIR, path)
        resp.headers["Vary"] = "Accept-Encoding"
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    return app, socketio


app, socketio = create_app()


def _warm_up() -> None:
    """Open the connection to the provider before the first real step arrives.

    The first verdict of any run took ~6s while TLS and the HTTP pool were set
    up; every later one was under a second. On stage that meant the first node
    sat grey conspicuously longer than the rest. Doing it at boot moves that cost
    somewhere nobody is watching.

    Failure here is deliberately silent: a warm-up that can't reach the provider
    is not a reason to refuse to start. Offline replay mode needs the server up
    precisely when the API is unreachable.
    """
    try:
        app.config["META_AGENT"].warm_up()
        print("Provider connection warmed.")
    except Exception as exc:  # noqa: BLE001 - best effort, never fatal
        print(f"Warm-up skipped ({type(exc).__name__}). Offline replay still works.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"SentinelMind watching on http://127.0.0.1:{port}")
    # Off the main thread so the server accepts connections immediately.
    threading.Thread(target=_warm_up, daemon=True, name="sentinel-warmup").start()
    socketio.run(app, host="127.0.0.1", port=port, allow_unsafe_werkzeug=True)
