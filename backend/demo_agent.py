"""The monitored agent -- a demo pipeline that SentinelMind watches.

Runs a support-assistant pipeline whose steps deliberately produce one of each
verdict, so the dashboard shows green, amber, and red in a single run:

    1. search_docs        -> OK        healthy tool call
    2. lookup_customer    -> OK        healthy tool call
    3. fetch_pricing      -> WARN      unusually slow
    4. summarize          -> WARN      output only loosely related to input
    5. delete_user_record -> ANOMALY   hallucinated tool, not in the registry
    6. fetch_pricing x3   -> ANOMALY   repeated identical call, an infinite loop
    7. flaky_api          -> ANOMALY   raises an exception

Usage:
    python demo_agent.py             # live: emit traces, server judges them
    python demo_agent.py --record    # live, and save events AND verdicts to traces/
    python demo_agent.py --replay    # re-send saved events; server re-judges (needs API)
    python demo_agent.py --offline   # replay saved VERDICTS; no API call at all

Two fallbacks, and the difference matters:

``--replay`` survives a broken monitored pipeline. It skips running the tools but
still posts events to ``/trace``, so the server calls the provider to judge each
one. It does **not** survive dead wifi.

``--offline`` survives dead wifi and a dead provider. It reads verdicts recorded
during an earlier live run and pushes them to ``/replay``, which writes straight
to the audit log and the socket. Nothing leaves the machine. Verdicts are marked
``replayed`` on the dashboard -- a recorded verdict shown as a live one would be
a lie, and the audit log is meant to be the record of truth.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

from decorator import monitor, subscribe

SERVER = "http://127.0.0.1:5000"
TRACE_DIR = Path(__file__).resolve().parent.parent / "traces"
TRACE_FILE = TRACE_DIR / "last_run.json"

# What this agent was asked to do. Declared to SentinelMind up front so goal
# drift is measurable against something -- steps 4 and 5 wander off this.
GOAL = (
    "Answer a customer's question about whether their refund window has expired, "
    "using the documentation and their account record."
)

_recorded: list[dict] = []


def send(event: dict) -> None:
    """Ship one trace event to the SentinelMind server."""
    try:
        requests.post(f"{SERVER}/trace", json=event, timeout=5)
    except requests.RequestException as exc:
        print(f"  ! could not reach SentinelMind at {SERVER}: {exc}", file=sys.stderr)


def declare_goal(goal: str = GOAL) -> None:
    """Tell SentinelMind the task, and reset the session window."""
    try:
        requests.post(f"{SERVER}/session/goal", json={"goal": goal}, timeout=5)
        print(f"\nGoal declared: {goal}")
    except requests.RequestException as exc:
        print(f"  ! could not declare goal: {exc}", file=sys.stderr)


def announce(event: dict) -> None:
    status = "ERROR" if event["error"] else "ok"
    print(f"  -> {event['tool']:<20} {event['duration_ms']:>7.1f}ms  {status}")


# --------------------------------------------------------------------------
# The monitored pipeline. Every tool is a plain callable wrapped in @monitor --
# that is the whole integration surface. A LangChain tool wraps the same way
# (decorate the underlying function), which is how this drops into a real
# pipeline unchanged.
# --------------------------------------------------------------------------


@monitor(tool_name="search_docs")
def search_docs(query: str) -> str:
    time.sleep(0.08)
    return "Refunds are accepted within 30 days of purchase, minus shipping."


@monitor(tool_name="lookup_customer")
def lookup_customer(customer_id: str) -> dict:
    time.sleep(0.05)
    return {"id": customer_id, "plan": "Enterprise", "since": "2024-03-11"}


@monitor(tool_name="fetch_pricing")
def fetch_pricing(sku: str, slow: bool = False) -> dict:
    # WARN: an unusually slow dependency. Nothing failed, but it is off-baseline.
    time.sleep(2.4 if slow else 0.06)
    return {"sku": sku, "price_usd": 149.00, "currency": "USD"}


@monitor(tool_name="summarize", step_type="model_call")
def summarize(text: str) -> str:
    time.sleep(0.12)
    # WARN: goal drift starting. The summary wandered off the source text.
    return "The customer seems interested in upgrading to a hardware bundle."


@monitor(tool_name="delete_user_record")
def delete_user_record(customer_id: str) -> str:
    # ANOMALY: this tool is not in the server's registry. A real agent reaching
    # for it means the model invented a capability it does not have.
    time.sleep(0.04)
    return f"deleted {customer_id}"


@monitor(tool_name="flaky_api")
def flaky_api(endpoint: str) -> str:
    # ANOMALY: raises. The decorator records the error and re-raises untouched.
    time.sleep(0.03)
    raise ConnectionError(f"upstream {endpoint} returned 503")


def run_pipeline() -> None:
    """Walk the scripted scenario, pausing so the dashboard animates."""
    print("\nMonitored agent: customer support assistant")
    print("-" * 52)

    print("\n[1] Answering a refund question")
    search_docs("refund policy")
    time.sleep(0.6)

    print("\n[2] Loading customer context")
    lookup_customer("cus_88213")
    time.sleep(0.6)

    print("\n[3] Pricing lookup (degraded upstream)")
    fetch_pricing("SKU-4471", slow=True)
    time.sleep(0.6)

    print("\n[4] Summarizing the thread")
    summarize("Customer asked whether their refund window had expired.")
    time.sleep(0.6)

    print("\n[5] Agent reaches for a tool it does not have")
    delete_user_record("cus_88213")
    time.sleep(0.6)

    print("\n[6] Agent loops on the same call")
    for _ in range(3):
        fetch_pricing("SKU-4471")
        time.sleep(0.35)
    time.sleep(0.3)

    print("\n[7] Upstream failure")
    try:
        flaky_api("/v1/entitlements")
    except ConnectionError:
        pass  # The agent swallows it -- SentinelMind still saw it.

    print("\n" + "-" * 52)
    print("Pipeline complete. Verdicts are on the dashboard.\n")


def _load_recording(path: Path) -> list[dict]:
    """Read a recording, accepting both the old and new file shapes.

    Older recordings were a bare list of events. Newer ones are a list of
    ``{"event": ..., "verdict": ...}`` entries, because verdicts are what offline
    mode actually needs. Normalizing here means an old file still drives
    ``--replay``; it just can't drive ``--offline``, and we say so plainly.
    """
    if not path.exists():
        sys.exit(
            f"No recorded trace at {path}.\n"
            "Run 'python demo_agent.py --record' once while online to create one."
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit(f"{path.name} is not a recording (expected a list).")

    entries = []
    for item in data:
        if isinstance(item, dict) and "event" in item:
            entries.append({"event": item["event"], "verdict": item.get("verdict")})
        else:
            entries.append({"event": item, "verdict": None})  # legacy shape
    return entries


def replay(path: Path, pace: float = 0.7) -> None:
    """Re-send recorded events. The server re-judges each one -- needs the API."""
    entries = _load_recording(path)
    declare_goal()
    print(f"\nReplaying {len(entries)} trace events from {path.name} (server re-judges)")
    print("-" * 52)
    for entry in entries:
        announce(entry["event"])
        send(entry["event"])
        time.sleep(pace)
    print("-" * 52)
    print("Replay complete.\n")


def offline(path: Path, pace: float = 0.7) -> None:
    """Replay recorded verdicts. No provider call anywhere in this path."""
    entries = _load_recording(path)
    missing = [e for e in entries if not e["verdict"]]
    if missing:
        sys.exit(
            f"{path.name} has {len(missing)} event(s) with no recorded verdict, so it "
            "cannot drive offline mode.\n"
            "Re-record it while online: python demo_agent.py --record"
        )

    declare_goal()
    print(f"\nOffline replay: {len(entries)} pre-judged entries from {path.name}")
    print("No API calls will be made.")
    print("-" * 52)
    for entry in entries:
        event, verdict = entry["event"], entry["verdict"]
        print(f"  -> {event['tool']:<20} {verdict.get('status', '?')}")
        try:
            requests.post(f"{SERVER}/replay", json=entry, timeout=5)
        except requests.RequestException as exc:
            print(f"  ! could not reach SentinelMind at {SERVER}: {exc}", file=sys.stderr)
        time.sleep(pace)
    print("-" * 52)
    print("Offline replay complete.\n")


def save_recording(path: Path) -> None:
    """Pull the judged entries back off the server and write them to disk.

    Verdicts are produced server-side, so the agent cannot record them from its
    own side of the wire -- it has to ask. Doing it after the run also means the
    file contains exactly what the audit log contains, which is the point: an
    offline replay should reproduce a real run, not an approximation of one.
    """
    try:
        response = requests.get(f"{SERVER}/audit", timeout=10)
        response.raise_for_status()
        entries = response.json().get("entries", [])
    except (requests.RequestException, ValueError) as exc:
        print(f"  ! could not fetch verdicts to record: {exc}", file=sys.stderr)
        print("  Falling back to events only -- this file will NOT drive --offline.")
        entries = [{"event": e, "verdict": None} for e in _recorded]

    payload = [{"event": e.get("event"), "verdict": e.get("verdict")} for e in entries]
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    judged = sum(1 for e in payload if e["verdict"])
    print(f"\nTrace saved to {path} ({len(payload)} entries, {judged} with verdicts)")
    if judged == len(payload) and payload:
        print("Offline fallback ready: python demo_agent.py --offline\n")


def main() -> None:
    global SERVER

    parser = argparse.ArgumentParser(description="SentinelMind demo agent")
    parser.add_argument(
        "--replay", action="store_true", help="re-send saved events; server re-judges (needs API)"
    )
    parser.add_argument(
        "--offline", action="store_true", help="replay saved verdicts; makes no API calls"
    )
    parser.add_argument(
        "--record", action="store_true", help="save this run's events and verdicts to traces/"
    )
    parser.add_argument("--server", default=SERVER, help="SentinelMind server URL")
    args = parser.parse_args()

    SERVER = args.server

    # Both are terminal -- never fall through into the live pipeline afterwards.
    if args.offline:
        offline(TRACE_FILE)
        return
    if args.replay:
        replay(TRACE_FILE)
        return

    declare_goal()

    subscribe(send)
    subscribe(announce)
    if args.record:
        subscribe(_recorded.append)

    run_pipeline()

    if args.record:
        # Verdicts arrive asynchronously on the server's worker thread; give the
        # last few time to land before asking for the log, or we record a run
        # that is missing its own tail.
        print("\nWaiting for the last verdicts to land...")
        time.sleep(3.0)
        save_recording(TRACE_FILE)


if __name__ == "__main__":
    main()
