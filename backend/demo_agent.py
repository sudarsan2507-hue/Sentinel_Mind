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
    python demo_agent.py             # live: emit traces to the server
    python demo_agent.py --record    # live, and save the trace to traces/
    python demo_agent.py --replay    # offline: replay a saved trace, no API needed

``--replay`` is the demo fallback. If the venue wifi or the API is slow on the
day, this reproduces a full run from disk at the same pacing.
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


def replay(path: Path, pace: float = 0.7) -> None:
    """Replay a recorded trace against a live server. No LLM pipeline needed."""
    if not path.exists():
        sys.exit(
            f"No recorded trace at {path}.\n"
            "Run 'python demo_agent.py --record' once while online to create one."
        )

    events = json.loads(path.read_text(encoding="utf-8"))
    declare_goal()
    print(f"\nReplaying {len(events)} trace events from {path.name}")
    print("-" * 52)
    for event in events:
        announce(event)
        send(event)
        time.sleep(pace)
    print("-" * 52)
    print("Replay complete.\n")


def main() -> None:
    global SERVER

    parser = argparse.ArgumentParser(description="SentinelMind demo agent")
    parser.add_argument("--replay", action="store_true", help="replay a saved trace offline")
    parser.add_argument("--record", action="store_true", help="save this run's trace to traces/")
    parser.add_argument("--server", default=SERVER, help="SentinelMind server URL")
    args = parser.parse_args()

    SERVER = args.server

    if args.replay:
        replay(TRACE_FILE)
        return  # replay is terminal -- do not then run the live pipeline

    declare_goal()

    subscribe(send)
    subscribe(announce)
    if args.record:
        subscribe(_recorded.append)

    run_pipeline()

    if args.record:
        TRACE_DIR.mkdir(exist_ok=True)
        TRACE_FILE.write_text(json.dumps(_recorded, indent=2), encoding="utf-8")
        print(f"Trace saved to {TRACE_FILE} ({len(_recorded)} events)")
        print("Offline fallback: python demo_agent.py --replay\n")


if __name__ == "__main__":
    main()
