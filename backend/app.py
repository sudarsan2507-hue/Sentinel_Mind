"""SentinelMind server: ingests trace events, judges them, streams verdicts.

    POST /trace          a monitored agent submits one trace event
    GET  /health         liveness probe
    GET  /audit          the structured audit log
    GET  /audit/export   the log as a downloadable JSON file
    POST /audit/clear    reset between demo runs
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
from meta_agent import MetaAgent
from session_context import SessionContext

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / 'frontend'

# Load GROQ_API_KEY from the repo-root .env before MetaAgent builds its client.
load_dotenv(ROOT / ".env")

# Tools the demo pipeline is allowed to call. Anything outside this set is a
# hallucinated tool call; the registry is passed to the meta-agent so it can say
# so by name.
KNOWN_TOOLS = [
    "search_docs",
    "fetch_pricing",
    "summarize",
    "lookup_customer",
]


def create_app(
    meta_agent: MetaAgent | None = None,
    audit_log: AuditLog | None = None,
) -> tuple[Flask, SocketIO]:
    """Build the app. Dependencies are injectable so tests can pass fakes."""
    app = Flask(__name__, static_folder=None)
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    app.config["AUDIT_LOG"] = audit_log or AuditLog()
    app.config["META_AGENT"] = meta_agent or MetaAgent(
        known_tools=KNOWN_TOOLS,
        confidence_threshold=float(os.environ.get("SENTINEL_CONFIDENCE_THRESHOLD", 0.0)),
    )
    # Loops and goal drift are cross-step properties -- the meta-agent needs the
    # run so far, not just the current step, to see either.
    app.config["SESSION"] = SessionContext(
        window=int(os.environ.get("SENTINEL_CONTEXT_WINDOW", 8))
    )

    work: queue.Queue = queue.Queue()
    app.config["WORK_QUEUE"] = work

    def worker() -> None:
        """Drain trace events, evaluate, record, broadcast."""
        while True:
            event = work.get()
            if event is None:
                break
            try:
                session: SessionContext = app.config["SESSION"]
                verdict = app.config["META_AGENT"].evaluate(event, context=session)
                # Record after judging, so a step never sees itself as a repeat.
                session.record(event, verdict)
                entry = app.config["AUDIT_LOG"].record(event, verdict)
                socketio.emit("verdict", entry)
                socketio.emit("summary", app.config["AUDIT_LOG"].summary())
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
        work.put(event)
        return jsonify({"accepted": True, "event_id": event.get("id")}), 202

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
        socketio.emit("cleared", {})
        return jsonify({"cleared": True}), 200

    @app.get("/")
    def dashboard():
        return send_from_directory(FRONTEND_DIR, "index.html")

    return app, socketio


app, socketio = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"SentinelMind watching on http://127.0.0.1:{port}")
    socketio.run(app, host="127.0.0.1", port=port, allow_unsafe_werkzeug=True)
