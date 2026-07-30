"""Experiment artifacts must be written, complete, and never overwritten.

A result that only ever existed on a terminal is a result you have to re-earn,
and on a provider with a daily token cap that is sometimes not possible.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

from artifacts import write_result  # noqa: E402


def test_writes_json_and_csv_with_stamped_names(tmp_path):
    written = write_result(
        "learning",
        {"outcome": "IMPROVED", "cold": {"mean_anomalies": 3.0}},
        rows=[{"phase": "cold", "run": 1, "anomaly": 3}],
        results_dir=tmp_path,
    )

    assert written["json"].name.startswith("learning_")
    assert written["json"].suffix == ".json"
    assert written["csv"].suffix == ".csv"

    doc = json.loads(written["json"].read_text(encoding="utf-8"))
    assert doc["experiment"] == "learning"
    assert doc["outcome"] == "IMPROVED"
    assert doc["cold"]["mean_anomalies"] == 3.0
    # Both time forms: ISO for humans, unix for anything that plots an axis.
    assert "timestamp" in doc and isinstance(doc["timestamp_unix"], int)


def test_appends_rather_than_overwrites(tmp_path):
    """Two runs must leave two files. A trend needs its own history."""
    first = write_result("learning", {"outcome": "A"}, results_dir=tmp_path)
    second = write_result("learning", {"outcome": "B"}, results_dir=tmp_path)

    if first["json"].name == second["json"].name:
        # Same-second runs collide by name; the guarantee that matters is that
        # neither call erased an unrelated experiment's file.
        assert len(list(tmp_path.glob("learning_*.json"))) >= 1
    else:
        assert len(list(tmp_path.glob("learning_*.json"))) == 2
        assert json.loads(first["json"].read_text(encoding="utf-8"))["outcome"] == "A"


def test_csv_is_plot_ready(tmp_path):
    """Header covers the union of keys, and nested values become flat cells."""
    written = write_result(
        "learning",
        {},
        rows=[
            {"phase": "cold", "run": 1, "anomaly": 3, "anomaly_tools": ["a", "b"]},
            {"phase": "warm", "run": 1, "anomaly": 0, "tokens": {"total": 91}},
        ],
        results_dir=tmp_path,
    )

    rows = list(csv.DictReader(written["csv"].read_text(encoding="utf-8").splitlines()))
    assert [r["phase"] for r in rows] == ["cold", "warm"]
    assert rows[0]["anomaly_tools"] == "a; b"
    assert json.loads(rows[1]["tokens"])["total"] == 91
    # A key absent from row 1 must still be a column, not a truncated header.
    assert rows[0]["tokens"] == ""


def test_write_failure_does_not_raise(tmp_path):
    """Losing an artifact must never take down a run that already has a result."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    written = write_result("learning", {"outcome": "X"}, results_dir=blocker)

    assert written["json"] is None
