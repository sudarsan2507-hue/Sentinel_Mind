"""The eval harness produces the numbers we quote to judges.

Those numbers are a claim. A wrong percentile is not a cosmetic bug -- it is a
statement about our own tail latency that we cannot defend when checked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parent.parent / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

from run_eval import _percentile  # noqa: E402


def test_p95_of_nine_samples_is_the_slowest_one():
    """The bug this replaces returned index 7 of 9 and called it p95.

    Nearest rank for q=0.95, n=9 is ceil(8.55) = 9, i.e. the maximum. The old
    expression int(9 * 0.95) - 1 = 7 reported the second-slowest verdict, always
    understating the tail -- an error that flattered us.
    """
    latencies = [100, 200, 300, 400, 500, 600, 700, 800, 9000]

    assert _percentile(latencies, 0.95) == 9000
    assert _percentile(latencies, 0.95) != 800  # the old, flattering answer


def test_percentiles_on_a_known_distribution():
    values = list(range(1, 101))  # 1..100

    assert _percentile(values, 0.95) == 95
    assert _percentile(values, 0.50) == 50
    assert _percentile(values, 1.0) == 100


@pytest.mark.parametrize("values", [[], [42]])
def test_percentile_handles_degenerate_inputs(values):
    """An empty or single-sample run must not raise mid-eval."""
    assert _percentile(values, 0.95) == (0.0 if not values else 42)
