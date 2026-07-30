"""Does the accumulated failure memory actually reduce failures?

    python evals/run_learning_experiment.py --runs 3

Two phases against the same task and the same agent model:

  COLD  memory wiped, --learn off. The agent has no idea what it can't do.
        Every anomaly here feeds the knowledge graph.
  WARM  memory kept, --learn on. Lessons distilled from the cold phase are
        injected into the agent's system prompt before it acts.

Reports mean anomalies per run for each phase. That number is the whole claim --
if WARM is not lower than COLD, the loop does not work and the honest thing is
to say so.

Requires the server running (python backend/app.py) and GROQ_API_KEY set. The
agent runs at temperature 0.7, so use --runs 3 or more; a single run of each
phase tells you almost nothing.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
SERVER = "http://127.0.0.1:5000"

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def one_run(learn: bool, max_steps: int, settle: float) -> dict:
    """Run the agent once and return the verdict counts for that run."""
    requests.post(f"{SERVER}/audit/clear", timeout=10)

    cmd = [sys.executable, "real_agent.py", "--max-steps", str(max_steps)]
    if learn:
        cmd.append("--learn")
    subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=300)

    # Verdicts are judged on a worker thread; give it time to drain the queue.
    time.sleep(settle)

    audit = requests.get(f"{SERVER}/audit", timeout=10).json()
    counts = audit["summary"]["counts"]
    anomalies = [
        e["event"]["tool"] for e in audit["entries"] if e["status"] == "ANOMALY"
    ]
    # A degraded verdict means the meta-agent never judged the step. Degraded
    # verdicts are always WARN and can never be ANOMALY, so a rate-limited run
    # scores zero anomalies and looks perfect. Count them so the caller can
    # refuse to draw a conclusion.
    degraded = [
        e["verdict"].get("explanation", "")
        for e in audit["entries"]
        if e["verdict"].get("degraded")
    ]
    return {
        "steps": audit["summary"]["total"],
        "ok": counts.get("OK", 0),
        "warn": counts.get("WARN", 0),
        "anomaly": counts.get("ANOMALY", 0),
        "anomaly_tools": anomalies,
        "degraded": len(degraded),
        "degraded_reason": degraded[0] if degraded else "",
    }


def phase(
    name: str, runs: int, learn: bool, max_steps: int, settle: float, pause: float
) -> list[dict]:
    print(f"\n{BOLD}{name}{RESET}  (--learn {'ON' if learn else 'off'})")
    print(f"{'run':<5} {'steps':<7} {'OK':<5} {'WARN':<6} {'ANOM':<6} {'degr':<6} anomalous tools")
    print("-" * 82)

    results = []
    for i in range(1, runs + 1):
        r = one_run(learn, max_steps, settle)
        results.append(r)
        tools = ", ".join(t.replace("internal_api:", "") for t in r["anomaly_tools"][:3])
        if len(r["anomaly_tools"]) > 3:
            tools += f" +{len(r['anomaly_tools']) - 3}"
        flag = f"{RED}{r['degraded']}{RESET}" if r["degraded"] else "0"
        print(
            f"{i:<5} {r['steps']:<7} {r['ok']:<5} {r['warn']:<6} {r['anomaly']:<6} "
            f"{flag:<6} {DIM}{tools}{RESET}"
        )
        if i < runs and pause:
            time.sleep(pause)  # stay under the provider's rate limit
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure whether the agent learns")
    parser.add_argument("--runs", type=int, default=3, help="runs per phase")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--settle", type=float, default=9.0, help="seconds to wait for verdicts")
    parser.add_argument(
        "--pause",
        type=float,
        default=20.0,
        help="seconds between runs, to stay under the provider rate limit",
    )
    args = parser.parse_args()

    try:
        requests.get(f"{SERVER}/health", timeout=5)
    except requests.RequestException:
        print(
            "Server is not reachable. Start it first:\n  cd backend && python app.py",
            file=sys.stderr,
        )
        return 2

    print(f"\n{BOLD}SentinelMind learning experiment{RESET}")
    print(f"{args.runs} run(s) per phase, same task, same agent model")

    # Wipe memory so the cold phase is genuinely cold.
    requests.post(f"{SERVER}/knowledge/clear", timeout=10)
    cold = phase(
        "COLD  — no memory", args.runs, False, args.max_steps, args.settle, args.pause
    )

    lessons = requests.get(f"{SERVER}/knowledge/lessons", timeout=10).json()["lessons"]
    print(f"\n{BOLD}Lessons learned from the cold phase{RESET}")
    if lessons:
        for i, line in enumerate(lessons, 1):
            print(f"  {i}. {line}")
    else:
        print(f"  {DIM}(none — the cold phase produced no recurring failures){RESET}")

    warm = phase(
        "WARM  — lessons injected", args.runs, True, args.max_steps, args.settle, args.pause
    )

    cold_mean = statistics.mean(r["anomaly"] for r in cold)
    warm_mean = statistics.mean(r["anomaly"] for r in warm)
    delta = cold_mean - warm_mean
    pct = (delta / cold_mean * 100) if cold_mean else 0.0

    print("\n" + "=" * 78)
    print(f"{'':<22}{'mean anomalies/run':<22}{'mean steps/run'}")
    print(f"{'COLD (no memory)':<22}{cold_mean:<22.2f}{statistics.mean(r['steps'] for r in cold):.2f}")
    print(f"{'WARM (with memory)':<22}{warm_mean:<22.2f}{statistics.mean(r['steps'] for r in warm):.2f}")

    if delta > 0:
        print(f"\n{GREEN}Anomalies fell by {delta:.2f} per run ({pct:.0f}%).{RESET}")
        print("The memory loop reduced repeat failures on this task.")
    elif delta == 0:
        print(f"\n{DIM}No change. The lessons did not alter behaviour on this task.{RESET}")
    else:
        print(f"\n{RED}Anomalies ROSE by {-delta:.2f} per run.{RESET}")
        print("The lessons made it worse. Report this, don't bury it.")

    print(
        f"\n{DIM}n={args.runs} per phase at temperature 0.7. This is a directional signal,\n"
        f"not a statistically significant result. Say 'across {args.runs} runs' when you quote it.{RESET}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
