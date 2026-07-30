"""Persist experiment results so a number never has to be re-earned.

Both harnesses printed to the terminal and nothing else. That is fine until you
want to plot a trend, put a figure in a deck, or answer "was it better last
week" -- at which point the only option is to run it again. On a provider with a
daily token cap, re-running is not always possible, and a result you cannot
reproduce today is a result you no longer have.

So every run writes two files, timestamped, never overwritten:

    evals/results/learning_2026-07-30_14-42-18.json   full structure
    evals/results/learning_2026-07-30_14-42-18.csv    flat rows for plotting

The JSON carries everything needed to redraw any chart without the server, the
API, or a key. The CSV is the same per-row data flattened, so it opens directly
in Excel or ``pandas.read_csv`` without a parsing step.

**Failed runs are written too.** An experiment that came back INVALID is
evidence -- it records that the provider was rate-limited at a particular time,
which is exactly the context you need when comparing it to a later run.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _stamp() -> str:
    """Filename-safe UTC timestamp. Sorts chronologically as plain text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def write_result(
    experiment: str,
    payload: dict,
    rows: list[dict] | None = None,
    results_dir: Path | None = None,
) -> dict:
    """Write one experiment's results. Returns the paths written.

    Args:
        experiment: Short name, used as the filename prefix (``learning``,
            ``meta_agent_eval``).
        payload: The full result structure. ``experiment``, ``timestamp``, and
            ``timestamp_unix`` are added here so every artifact carries them
            and no caller has to remember.
        rows: Flat per-unit records for the CSV -- one per run, per case, per
            whatever the experiment's unit is. Omit for no CSV.
        results_dir: Override the output directory. Tests pass a tmp_path;
            nothing else should need it.

    Never raises on a write failure. Losing an artifact is bad; losing the
    printed result that is already on screen because the write failed is worse.
    """
    directory = results_dir or RESULTS_DIR
    stamp = _stamp()
    now = datetime.now(timezone.utc)

    document = {
        "experiment": experiment,
        "timestamp": now.isoformat(),
        # Unix seconds alongside ISO: matplotlib and Excel both plot a number
        # far more readily than they parse a string.
        "timestamp_unix": int(now.timestamp()),
        **payload,
    }

    written: dict = {"json": None, "csv": None}
    try:
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{experiment}_{stamp}.json"
        json_path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
        written["json"] = json_path

        if rows:
            csv_path = directory / f"{experiment}_{stamp}.csv"
            # union of keys, first-seen order, so a row missing an optional
            # field doesn't truncate the header for every other row
            fields: list[str] = []
            for row in rows:
                for key in row:
                    if key not in fields:
                        fields.append(key)
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: _flatten(row.get(k)) for k in fields})
            written["csv"] = csv_path
    except OSError as exc:
        print(f"  ! could not write results artifact: {exc}")

    return written


def _flatten(value):
    """CSV cells hold scalars. Lists become semicolon-joined; dicts become JSON."""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return value
