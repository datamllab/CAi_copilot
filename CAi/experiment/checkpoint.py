"""Checkpoint persistence for experiment runs.

Uses JSONL format so each result is a self-contained line that can be
appended atomically.  A crash mid-write corrupts at most the last line,
which ``load_checkpoint`` silently skips.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import ExperimentResult


class CheckpointWriter:
    """Append ``ExperimentResult`` objects to a JSONL checkpoint file.

    Each ``append`` call opens the file, writes one line, and closes it.
    A ``threading.Lock`` guards against concurrent writes in the parent
    process (multiprocessing workers never share the same writer).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, result: ExperimentResult) -> None:
        """Append one result to the checkpoint file."""
        line = json.dumps(result.to_dict(), ensure_ascii=False)
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def load_checkpoint(path: str | Path) -> list[ExperimentResult]:
    """Read all completed results from a checkpoint JSONL file.

    Skips malformed lines (tolerant of partial writes from crashes).
    Returns results in file order.
    """
    path = Path(path)
    if not path.exists():
        return []

    results: list[ExperimentResult] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip corrupted trailing line
            results.append(_dict_to_result(d))
    return results


def completed_item_ids(results: list[ExperimentResult]) -> set[str]:
    """Extract the set of non-None item_ids from checkpointed results."""
    return {r.item_id for r in results if r.item_id is not None}


def merge_results(
    old: list[ExperimentResult],
    new: list[ExperimentResult],
) -> list[ExperimentResult]:
    """Merge old (checkpointed) and new (fresh) results.

    Deduplicates by ``item_id`` — newer results take precedence.
    Items with ``None`` id from both lists are kept as-is.
    Returns a new list sorted by ``item_id`` (``None`` sorts last).
    """
    merged: dict[str, ExperimentResult] = {}
    none_id: list[ExperimentResult] = []

    for r in old:
        if r.item_id is not None:
            merged[r.item_id] = r
        else:
            none_id.append(r)

    for r in new:
        if r.item_id is not None:
            merged[r.item_id] = r
        else:
            none_id.append(r)

    all_results = list(merged.values()) + none_id
    all_results.sort(key=lambda r: r.item_id or "\xff\xff")
    return all_results


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _dict_to_result(d: dict) -> ExperimentResult:
    """Convert a plain dict (from JSONL) to ExperimentResult."""
    return ExperimentResult(
        item_id=d["item_id"],
        prompt=d["prompt"],
        final_response=d["final_response"],
        status=d["status"],
        error_message=d.get("error_message"),
        wall_time_seconds=d.get("wall_time_seconds", 0.0),
        steps=d.get("steps", []),
        code_executions=d.get("code_executions", 0),
        item_metadata=d.get("item_metadata", {}),
        expected_output=d.get("expected_output"),
        match_score=d.get("match_score"),
    )
