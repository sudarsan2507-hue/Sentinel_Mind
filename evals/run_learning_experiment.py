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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifacts import write_result  # noqa: E402

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

    started = time.perf_counter()
    # The exit code was previously discarded. An agent that crashed on startup
    # produced zero steps and therefore zero anomalies -- indistinguishable, in
    # the mean, from an agent that behaved perfectly.
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=300)
    agent_seconds = round(time.perf_counter() - started, 2)

    # Verdicts are judged on a worker thread; give it time to drain the queue.
    time.sleep(settle)

    audit = requests.get(f"{SERVER}/audit", timeout=10).json()
    counts = audit["summary"]["counts"]
    anomalies = [
        e["event"]["tool"] for e in audit["entries"] if e["status"] == "ANOMALY"
    ]
    # Verdicts now carry token usage, so a run's meta-agent cost is recoverable
    # from the audit log. Missing on degraded verdicts, hence the `or {}`.
    tokens = sum((e["verdict"].get("tokens") or {}).get("total", 0) for e in audit["entries"])
    latencies = [
        e["verdict"]["latency_ms"]
        for e in audit["entries"]
        if isinstance(e["verdict"].get("latency_ms"), (int, float))
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
        "agent_seconds": agent_seconds,
        "agent_exit_code": proc.returncode,
        # Tail only: enough to identify a crash without burying the artifact in
        # a traceback nobody will read from a JSON file.
        "agent_stderr_tail": proc.stderr.strip()[-300:] if proc.returncode else "",
        "meta_agent_tokens": tokens,
        "verdict_latency_ms_mean": round(statistics.mean(latencies), 1) if latencies else 0.0,
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
        if r["agent_exit_code"]:
            # A crashed agent takes no steps and so scores no anomalies, which
            # reads as a flawless run unless it is said out loud.
            print(
                f"      {RED}agent exited {r['agent_exit_code']}{RESET} "
                f"{DIM}{r['agent_stderr_tail'][-120:]}{RESET}"
            )
        if i < runs and pause:
            time.sleep(pause)  # stay under the provider's rate limit
    return results


def _phase_metrics(runs: list[dict]) -> dict:
    """Aggregate one phase. Everything a chart might want, computed once."""
    if not runs:
        return {}
    anomalies = [r["anomaly"] for r in runs]
    return {
        "runs": len(runs),
        "mean_anomalies": round(statistics.mean(anomalies), 3),
        "median_anomalies": round(statistics.median(anomalies), 3),
        # Population stdev, and only when n > 1 -- statistics.stdev raises on a
        # single sample, and an experiment must not die while writing its report.
        "stdev_anomalies": round(statistics.pstdev(anomalies), 3) if len(runs) > 1 else 0.0,
        "total_anomalies": sum(anomalies),
        "mean_steps": round(statistics.mean(r["steps"] for r in runs), 3),
        "total_steps": sum(r["steps"] for r in runs),
        "total_ok": sum(r["ok"] for r in runs),
        "total_warn": sum(r["warn"] for r in runs),
        "total_degraded": sum(r["degraded"] for r in runs),
        # A run that produced steps and no anomalies is the outcome the loop is
        # trying to cause; a crashed run is not a success and is excluded.
        "clean_runs": sum(1 for r in runs if r["anomaly"] == 0 and r["agent_exit_code"] == 0),
        "success_rate": round(
            sum(1 for r in runs if r["anomaly"] == 0 and r["agent_exit_code"] == 0) / len(runs), 3
        ),
        "agent_failures": sum(1 for r in runs if r["agent_exit_code"] != 0),
        "total_agent_seconds": round(sum(r["agent_seconds"] for r in runs), 2),
        "total_meta_agent_tokens": sum(r["meta_agent_tokens"] for r in runs),
        "anomaly_tools": sorted({t for r in runs for t in r["anomaly_tools"]}),
    }


def _rows(phase_name: str, runs: list[dict]) -> list[dict]:
    """One flat CSV row per run -- the unit anyone would plot."""
    return [
        {
            "phase": phase_name,
            "run": i,
            "steps": r["steps"],
            "ok": r["ok"],
            "warn": r["warn"],
            "anomaly": r["anomaly"],
            "degraded": r["degraded"],
            "agent_seconds": r["agent_seconds"],
            "agent_exit_code": r["agent_exit_code"],
            "meta_agent_tokens": r["meta_agent_tokens"],
            "verdict_latency_ms_mean": r["verdict_latency_ms_mean"],
            "anomaly_tools": r["anomaly_tools"],
        }
        for i, r in enumerate(runs, 1)
    ]


def _persist(args, outcome: str, cold: list[dict], warm: list[dict],
             lessons: list[str], reason: str = "") -> None:
    """Write the JSON + CSV artifact for this experiment and say where it went."""
    cold_metrics = _phase_metrics(cold)
    warm_metrics = _phase_metrics(warm)

    delta = None
    if outcome != "INVALID" and cold_metrics and warm_metrics:
        raw = cold_metrics["mean_anomalies"] - warm_metrics["mean_anomalies"]
        delta = {
            "anomalies_per_run": round(raw, 3),
            "percent": round(raw / cold_metrics["mean_anomalies"] * 100, 1)
            if cold_metrics["mean_anomalies"]
            else 0.0,
        }

    written = write_result(
        "learning",
        {
            # outcome is a first-class field: an artifact whose numbers cannot
            # be trusted must say so in the file, not only on the terminal it
            # was printed to and then closed.
            "outcome": outcome,
            "invalid_reason": reason,
            "valid": outcome != "INVALID",
            "config": {
                "runs_per_phase": args.runs,
                "max_steps": args.max_steps,
                "settle_seconds": args.settle,
                "pause_seconds": args.pause,
                "server": SERVER,
            },
            "cold": {**cold_metrics, "runs_detail": cold},
            "warm": {**warm_metrics, "runs_detail": warm},
            "delta": delta,
            "lessons": lessons,
            "totals": {
                "meta_agent_tokens": cold_metrics.get("total_meta_agent_tokens", 0)
                + warm_metrics.get("total_meta_agent_tokens", 0),
                "agent_seconds": round(
                    cold_metrics.get("total_agent_seconds", 0)
                    + warm_metrics.get("total_agent_seconds", 0), 2
                ),
                "degraded_steps": cold_metrics.get("total_degraded", 0)
                + warm_metrics.get("total_degraded", 0),
                "agent_failures": cold_metrics.get("agent_failures", 0)
                + warm_metrics.get("agent_failures", 0),
            },
        },
        rows=_rows("cold", cold) + _rows("warm", warm),
    )

    if written["json"]:
        print(f"{DIM}Results written to {written['json'].relative_to(ROOT)}{RESET}")
    if written["csv"]:
        print(f"{DIM}                   {written['csv'].relative_to(ROOT)}{RESET}\n")


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

    # Wipe memory so the cold phase is genuinely cold. The endpoint requires an
    # explicit confirm; a silently-refused wipe would make the cold phase warm
    # and quietly invalidate the whole comparison.
    wiped = requests.post(f"{SERVER}/knowledge/clear", json={"confirm": True}, timeout=10)
    if wiped.status_code != 200:
        sys.exit(f"Could not clear knowledge before the cold phase: {wiped.text}")
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

    # Refuse to draw a conclusion from runs the meta-agent never judged. A
    # rate-limited phase degrades every verdict to WARN, scores zero anomalies,
    # and looks like a perfect result. That number would be a lie.
    degraded_total = sum(r["degraded"] for r in cold + warm)
    if degraded_total:
        print("\n" + "=" * 78)
        print(
            f"{RED}INVALID: {degraded_total} step(s) were never judged by the "
            f"meta-agent.{RESET}"
        )
        reason = next(
            (r["degraded_reason"] for r in cold + warm if r["degraded_reason"]), ""
        )
        print(f"  First reason: {reason[:160]}")
        print(
            "\nDegraded verdicts are always WARN and can never be ANOMALY, so a phase\n"
            "with degraded steps scores artificially few anomalies. No comparison is\n"
            "reported. Raise --pause, lower --runs, or wait for the rate limit to reset."
        )
        # Written anyway. An INVALID run records that the provider was rate
        # limited at a particular time with particular settings -- exactly the
        # context you want when comparing it against a later attempt.
        _persist(args, "INVALID", cold, warm, lessons, reason=reason)
        return 1

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

    verdict = "IMPROVED" if delta > 0 else ("UNCHANGED" if delta == 0 else "REGRESSED")
    _persist(args, verdict, cold, warm, lessons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
