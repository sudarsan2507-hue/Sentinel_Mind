"""Score the meta-agent against the labelled eval set.

    python evals/run_eval.py

Answers slide 4's "How you know it works: tests or evals". The tests prove the
plumbing works with a fake model; this proves the *judgement* works with a real
one, and gives two numbers worth quoting:

  - accuracy on 9 labelled cases, with a confusion matrix
  - p50 / p95 verdict latency, which is the "under 3 seconds" claim measured
    rather than asserted

Requires GROQ_API_KEY. Cases run in sequence against one shared SessionContext
because the loop cases only read as a loop in the presence of the calls before
them.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from cases import CASES, GOAL, KNOWN_TOOLS  # noqa: E402
from meta_agent import ANOMALY, OK, WARN, MetaAgent  # noqa: E402
from session_context import SessionContext  # noqa: E402

LABELS = [OK, WARN, ANOMALY]
GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value at or above rank ceil(q*n).

    The previous expression, ``values[int(n * 0.95) - 1]``, was off by one rank
    and always in the flattering direction. On our 9 cases it returned index 7 --
    the second-slowest verdict -- and reported it as p95. The real p95 of 9
    samples is the slowest one.

    That matters because the number goes on a slide. Understating our own tail
    latency is the kind of error a judge is entitled to check, and "we quoted the
    8th of 9" is not a defensible answer.

    With n=9 this necessarily equals max(); the caller says so rather than
    letting "p95" imply more samples than we have.
    """
    if not sorted_values:
        return 0.0
    rank = math.ceil(q * len(sorted_values))
    return sorted_values[min(len(sorted_values), max(1, rank)) - 1]


def main() -> int:
    if not os.environ.get("GROQ_API_KEY"):
        print(
            "GROQ_API_KEY is not set. The eval needs a real model -- that is the point.\n"
            "Copy .env.example to .env and add your key from console.groq.com.",
            file=sys.stderr,
        )
        return 2

    agent = MetaAgent(known_tools=KNOWN_TOOLS)
    session = SessionContext(goal=GOAL)

    print(f"\nSentinelMind meta-agent eval -- model: {agent.model}")
    print(f"{len(CASES)} labelled cases")

    # Pay the connection cold start before measuring, exactly as the server now
    # does at boot. Left in, it landed entirely on case 1 and inflated the tail
    # by ~6s -- a number that measured our TLS handshake, not our judgement.
    # Reported rather than hidden: it is a real cost, just not a per-verdict one.
    warm_started = time.perf_counter()
    try:
        agent.warm_up()
        warm_ms = (time.perf_counter() - warm_started) * 1000
        print(f"Cold start {warm_ms/1000:.2f}s (excluded below) -- format: "
              f"{agent.structured_output_mode}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"{YELLOW}Warm-up failed ({exc}).{RESET} Case 1 will carry the cold start.\n")

    print(f"{'case':<26} {'expected':<9} {'actual':<9} {'conf':<6} {'ms':<7} result")
    print("-" * 72)

    results = []
    for case in CASES:
        verdict = agent.evaluate(case["event"], context=session)
        session.record(case["event"], verdict)

        actual = verdict["status"]
        hit = actual == case["expected"]
        results.append(
            {
                "name": case["name"],
                "expected": case["expected"],
                "actual": actual,
                "hit": hit,
                "latency_ms": verdict["latency_ms"],
                "degraded": verdict["degraded"],
                "explanation": verdict["explanation"],
            }
        )

        mark = f"{GREEN}pass{RESET}" if hit else f"{RED}FAIL{RESET}"
        if verdict["degraded"]:
            mark = f"{YELLOW}degraded{RESET}"
        print(
            f"{case['name']:<26} {case['expected']:<9} {actual:<9} "
            f"{verdict['confidence']:<6.2f} {verdict['latency_ms']:<7.0f} {mark}"
        )

    degraded = [r for r in results if r["degraded"]]
    if degraded:
        print(
            f"\n{YELLOW}{len(degraded)} case(s) never reached the model.{RESET} "
            "Accuracy below is meaningless until that is fixed:"
        )
        print(f"  {degraded[0]['explanation']}")
        return 1

    hits = sum(r["hit"] for r in results)
    accuracy = hits / len(results)
    latencies = sorted(r["latency_ms"] for r in results)
    p50 = statistics.median(latencies)
    p95 = _percentile(latencies, 0.95)

    print("\n" + "=" * 72)
    print(f"Accuracy      {hits}/{len(results)} on this labelled set  ({accuracy:.0%})")
    print(f"Latency       p50 {p50/1000:.2f}s   p95 {p95/1000:.2f}s   max {max(latencies)/1000:.2f}s")
    if len(latencies) < 20:
        print(
            f"{DIM}              n={len(latencies)}, so p95 is the slowest sample. "
            f"Quote it as such, not as a distribution.{RESET}"
        )
    claim = "MET" if p95 < 3000 else "MISSED"
    colour = GREEN if p95 < 3000 else RED
    print(f"Sub-3s claim  {colour}{claim}{RESET} (p95 {p95/1000:.2f}s vs 3.00s target)")

    print("\nConfusion matrix (rows = expected, cols = actual)")
    print(f"{'':<10}" + "".join(f"{c:<10}" for c in LABELS))
    for expected in LABELS:
        row = [
            sum(1 for r in results if r["expected"] == expected and r["actual"] == a)
            for a in LABELS
        ]
        print(f"{expected:<10}" + "".join(f"{n:<10}" for n in row))

    misses = [r for r in results if not r["hit"]]
    if misses:
        print(f"\n{len(misses)} miss(es):")
        for r in misses:
            print(f"  {RED}{r['name']}{RESET}: expected {r['expected']}, got {r['actual']}")
            print(f"    {DIM}{r['explanation']}{RESET}")
        print(
            "\nIf a miss looks like a bad label rather than a bad verdict, fix the label in "
            "evals/cases.py and say so in the rationale."
        )

    print()
    return 0 if accuracy == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
