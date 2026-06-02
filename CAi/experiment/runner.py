"""Experiment runner — orchestrates batch agent evaluation.

Uses ``multiprocessing.Pool`` with the **spawn** context so each worker
gets a clean Python interpreter, independent REPL kernel, and independent
builtins / module-level globals.

Usage:
    from CAi.experiment import run_experiment, load_dataset

    dataset = load_dataset("benchmark.csv", prompt_field="question", id_field="id")
    report = run_experiment(dataset, max_workers=4, output_path="results/exp_001.json")
    print(f"{report.successes}/{report.total} success")
"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointWriter
from .models import DatasetItem, ExperimentReport, ExperimentResult
from .persistence import save_csv, save_json
from .worker import run_single_experiment

# Default agent constructor args when none are provided
_DEFAULT_AGENT_ARGS = {
    "auto_load_tools": True,
    "auto_load_skills": True,
    "auto_load_utilities": False,  # Utilities are per-session; disable for batch
}


def run_experiment(
    dataset: list[DatasetItem],
    *,
    agent_args: dict[str, Any] | None = None,
    max_workers: int = 1,
    per_item_timeout_seconds: int = 600,
    output_path: str | Path | None = None,
    output_format: str = "json",
    on_progress: Callable[[int, int, ExperimentResult], None] | None = None,
    scorer: Callable[[ExperimentResult], float | None] | None = None,
    checkpoint_path: str | Path | None = None,
    on_item_start: Callable[[int, int, DatasetItem], None] | None = None,
    on_step: Callable[[str, dict], None] | None = None,
) -> ExperimentReport:
    """Run an experiment over a dataset of prompts.

    Args:
        dataset: List of DatasetItem to evaluate.
        agent_args: Kwargs forwarded to ``A1pro()``.  Defaults to loading
                    tools + skills, no utilities.
        max_workers: 1 = sequential (in-process, for debugging).
                     >1 = ``multiprocessing.Pool`` with spawn context.
        per_item_timeout_seconds: Hard timeout per item (enforced via SIGALRM).
        output_path: Where to save results.  ``None`` = no file written.
        output_format: ``"json"`` or ``"csv"``.
        on_progress: Called as ``(completed, total, result)`` after each item.
        scorer: Optional function ``(result) -> float | None`` to compute a
                match score for each result.
        checkpoint_path: If provided, each completed result is appended to
                         this JSONL file immediately for crash-safe persistence.
        on_item_start: Called as ``(completed, total, item)`` before each item
                       begins execution.
        on_step: Called as ``(item_id, event)`` for each streaming event from
                 the agent. **Only available in sequential mode** (``max_workers=1``);
                 silently ignored in multiprocessing mode.

    Returns:
        ExperimentReport with summary statistics and per-item results.
    """
    if not dataset:
        raise ValueError("dataset is empty")

    agent_kwargs = {**_DEFAULT_AGENT_ARGS, **(agent_args or {})}
    total = len(dataset)
    results: list[ExperimentResult] = []
    completed = 0

    checkpoint_writer: CheckpointWriter | None = None
    if checkpoint_path:
        checkpoint_writer = CheckpointWriter(checkpoint_path)

    if max_workers <= 1:
        # Sequential mode — run in the current process
        for item in dataset:
            if on_item_start:
                on_item_start(completed, total, item)

            item_d = _item_to_dict(item)
            step_cb = (
                (lambda event, _id=item.id: on_step(_id, event))
                if on_step
                else None
            )
            raw = run_single_experiment(
                item_d, agent_kwargs, per_item_timeout_seconds, step_cb
            )
            result = _dict_to_result(raw)
            if scorer:
                result.match_score = scorer(result)
            results.append(result)

            if checkpoint_writer:
                checkpoint_writer.append(result)

            completed += 1
            if on_progress:
                on_progress(completed, total, result)
    else:
        # Multiprocessing mode — spawn context for clean isolation
        ctx = mp.get_context("spawn")
        pool = ctx.Pool(processes=max_workers)
        async_results: list[mp.pool.AsyncResult] = []

        for item in dataset:
            if on_item_start:
                on_item_start(completed, total, item)
            item_d = _item_to_dict(item)
            ar = pool.apply_async(
                run_single_experiment,
                args=(item_d, agent_kwargs, per_item_timeout_seconds),
            )
            async_results.append(ar)

        pool.close()

        for ar in async_results:
            try:
                raw = ar.get(timeout=per_item_timeout_seconds + 30)
            except Exception as e:
                # Pool-level error (e.g., worker crash) — surface as error result
                raw = {
                    "item_id": None,
                    "prompt": "",
                    "final_response": "",
                    "status": "error",
                    "error_message": f"Worker process error: {e}",
                    "wall_time_seconds": 0.0,
                    "steps": [],
                    "code_executions": 0,
                    "item_metadata": {},
                    "expected_output": None,
                    "match_score": None,
                }

            result = _dict_to_result(raw)
            if scorer:
                result.match_score = scorer(result)
            results.append(result)

            if checkpoint_writer:
                checkpoint_writer.append(result)

            completed += 1
            if on_progress:
                on_progress(completed, total, result)

        pool.join()

    # Sort results by item_id (None sorts last)
    results.sort(key=lambda r: r.item_id or "\xff\xff")

    successes = sum(1 for r in results if r.status == "success")
    errors = sum(1 for r in results if r.status == "error")
    timeouts = sum(1 for r in results if r.status == "timeout")
    total_item_wall = sum(r.wall_time_seconds for r in results)

    report = ExperimentReport(
        total=total,
        successes=successes,
        errors=errors,
        timeouts=timeouts,
        total_wall_time=total_item_wall,
        avg_wall_time=total_item_wall / total if total else 0.0,
        results=results,
        output_path=str(output_path) if output_path else None,
    )

    # Persist results
    if output_path:
        path = Path(output_path)
        if output_format == "csv":
            save_csv(report, path)
        else:
            save_json(report, path)

    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _item_to_dict(item: DatasetItem) -> dict:
    """Convert DatasetItem to plain dict for subprocess IPC."""
    return {
        "id": item.id,
        "prompt": item.prompt,
        "history": item.history,
        "metadata": item.metadata,
        "expected_output": item.expected_output,
    }


def _dict_to_result(d: dict) -> ExperimentResult:
    """Convert worker output dict to ExperimentResult."""
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
