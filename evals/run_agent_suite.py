"""Run a set of agents against SentinelMind and keep every run.

    python evals/run_agent_suite.py                 # every agent once
    python evals/run_agent_suite.py --only rogue rogue-guard --repeat 2

Each run is saved to runs/<time>_<agent>.json: what the agent printed, every
step SentinelMind judged with its verdict, and a summary. runs/index.csv gets
one row per run, so runs from different days can be compared side by side.

Requires the server (python backend/app.py) and GROQ_API_KEY.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
RUNS = ROOT / "runs"

# name -> (script, extra args, what it shows)
AGENTS = {
    "demo": ("demo_agent.py", [], "scripted 7-step agent with planted mistakes"),
    "support": ("real_agent.py", [], "real tool-calling support agent, no help"),
    "support-learn": ("real_agent.py", ["--learn"], "same agent with lessons from past failures"),
    "rogue": ("real_agent.py", ["--rogue"], "agent pushed to break the refund policy, unprotected"),
    "rogue-guard": ("real_agent.py", ["--rogue", "--guard"], "rogue agent with guard mode"),
    "rogue-autopilot": ("real_agent.py", ["--rogue", "--autopilot"], "rogue agent kept on the right path"),
}

INDEX_FIELDS = ["file", "agent", "started", "seconds", "exit_code", "steps", "ok", "warn",
                "anomaly", "blocked", "refunded_usd", "erasures", "description"]


def settle(server: str, wait: float) -> dict:
    """Wait until the judge has caught up: some verdicts, and no new ones for 6s."""
    last, stable, audit = -1, 0, {}
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        audit = requests.get(f"{server}/audit", timeout=10).json()
        total = audit["summary"]["total"]
        stable = stable + 1 if total == last and total > 0 else 0
        if stable >= 2:
            break
        last = total
        time.sleep(3)
    return audit


def side_effects(stdout: str) -> tuple[float, int]:
    for line in stdout.splitlines():
        if line.startswith("Side effects:"):
            # "Side effects: 1 refund(s) totalling $149.00, 1 data erasure(s); ..."
            money = float(line.split("$")[1].split(",")[0]) if "$" in line else 0.0
            erasures = int(line.split(",")[1].split()[0]) if "," in line else 0
            return money, erasures
    return 0.0, 0


def run_one(name: str, server: str, approval_timeout: float, settle_s: float) -> dict:
    script, extra, description = AGENTS[name]
    requests.post(f"{server}/audit/clear", timeout=10)
    cmd = [sys.executable, script, "--server", server, *extra]
    if "--guard" in extra or "--autopilot" in extra:
        cmd += ["--approval-timeout", str(approval_timeout)]

    started = datetime.now()
    try:
        proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=420,
                              encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code = (exc.stdout or ""), "agent timed out after 420s", -1
        stdout = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else stdout
    seconds = round((datetime.now() - started).total_seconds(), 1)

    audit = settle(server, settle_s)
    counts = audit.get("summary", {}).get("counts", {})
    refunded, erasures = side_effects(stdout)
    record = {
        "agent": name,
        "description": description,
        "command": " ".join(cmd[1:]),
        "started": started.isoformat(timespec="seconds"),
        "seconds": seconds,
        "exit_code": code,
        "summary": {
            "steps": audit.get("summary", {}).get("total", 0),
            "ok": counts.get("OK", 0), "warn": counts.get("WARN", 0),
            "anomaly": counts.get("ANOMALY", 0), "blocked": counts.get("BLOCKED", 0),
            "refunded_usd": refunded, "erasures": erasures,
        },
        "path": requests.get(f"{server}/path/state", timeout=10).json(),
        "steps": audit.get("entries", []),
        "agent_output": stdout,
        "agent_errors": stderr[-2000:],
    }

    RUNS.mkdir(exist_ok=True)
    file = RUNS / f"{started:%Y-%m-%d_%H-%M-%S}_{name}.json"
    file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    index = RUNS / "index.csv"
    new = not index.exists()
    with index.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({"file": file.name, "agent": name, "started": record["started"],
                         "seconds": seconds, "exit_code": code, **record["summary"],
                         "description": description})
    return record | {"file": file.name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", nargs="+", choices=list(AGENTS), help="run just these agents")
    parser.add_argument("--repeat", type=int, default=1, help="runs per agent")
    parser.add_argument("--server", default="http://127.0.0.1:5000")
    parser.add_argument("--approval-timeout", type=float, default=15.0,
                        help="how long a guarded run waits for Approve/Deny before denying")
    parser.add_argument("--settle", type=float, default=90.0, help="max seconds to wait for verdicts")
    parser.add_argument("--pause", type=float, default=15.0, help="seconds between runs (rate limit)")
    args = parser.parse_args()

    try:
        requests.get(f"{args.server}/health", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        print(f"SentinelMind is not reachable at {args.server}: {exc}", file=sys.stderr)
        return 2

    names = [n for n in (args.only or AGENTS) for _ in range(args.repeat)]
    print(f"{'agent':<17}{'steps':>6}{'ok':>4}{'warn':>5}{'anom':>5}{'blkd':>5}{'refund':>8}{'erase':>6}  saved as")
    for i, name in enumerate(names):
        r = run_one(name, args.server, args.approval_timeout, args.settle)
        s = r["summary"]
        flag = "" if r["exit_code"] == 0 else f"  (agent exit {r['exit_code']})"
        print(f"{name:<17}{s['steps']:>6}{s['ok']:>4}{s['warn']:>5}{s['anomaly']:>5}{s['blocked']:>5}"
              f"{s['refunded_usd']:>8.0f}{s['erasures']:>6}  runs/{r['file']}{flag}", flush=True)
        if i < len(names) - 1:
            time.sleep(args.pause)
    print(f"\nAll runs: {RUNS / 'index.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
