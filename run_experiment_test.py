#!/usr/bin/env python3
"""Experiment launcher — run experiments with organized output.

Each run creates a timestamped directory under ``experiments/``:

    experiments/
    └── 20250528_143022_smoke_test/
        ├── config.json          # All parameters used
        ├── checkpoint.jsonl     # Crash-safe incremental results (one JSON line per item)
        ├── results.json         # Full JSON report
        ├── results.csv          # Flat CSV table
        └── summary.txt          # Human-readable summary

Usage:
    # Run with defaults (uses experiment_test_tasks.json)
    python run_experiment_test.py

    # Custom dataset and name
    python run_experiment_test.py --dataset my_bench.json --name bench_v1

    # Parallel with 4 workers
    python run_experiment_test.py --workers 4

    # Resume from an interrupted run
    python run_experiment_test.py --dataset my_bench.json --resume

    # Resume from a specific run directory
    python run_experiment_test.py --dataset my_bench.json --resume experiments/20250528_143022_smoke_test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from CAi.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_SOURCE
from CAi.experiment import (
    DatasetItem,
    ExperimentReport,
    ExperimentResult,
    completed_item_ids,
    load_checkpoint,
    load_dataset,
    merge_results,
    run_experiment,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run CAi experiment")

    # Dataset & naming
    p.add_argument("--dataset", default="experiment_test_tasks.json",
                   help="Path to dataset file (JSON/JSONL/CSV)")
    p.add_argument("--name", default="",
                   help="Experiment name (appended to timestamp dir). Default: dataset stem")
    p.add_argument("--output-dir", default="experiments",
                   help="Root directory for experiment results (default: experiments/)")

    # Agent config
    p.add_argument("--model", default=LLM_MODEL, help="LLM model")
    p.add_argument("--source", default=LLM_SOURCE, help="LLM source")
    p.add_argument("--base-url", default=LLM_BASE_URL, help="LLM base URL")
    p.add_argument("--no-tools", action="store_true", help="Disable tool loading")
    p.add_argument("--no-skills", action="store_true", help="Disable skill loading")
    p.add_argument("--utilities", action="store_true", help="Enable utility loading (default: off)")

    # Execution
    p.add_argument("--workers", type=int, default=1,
                   help="Number of parallel workers (1=sequential, >1=multiprocessing)")
    p.add_argument("--timeout", type=int, default=300,
                   help="Per-item timeout in seconds")

    # Dataset field mapping
    p.add_argument("--prompt-field", default="prompt", help="Field name for prompt text")
    p.add_argument("--id-field", default="id", help="Field name for item ID")

    # Resume
    p.add_argument("--resume", nargs="?", const=True, default=None,
                   metavar="RUN_DIR",
                   help="Resume from checkpoint. If a path is given, resume from that "
                        "run directory. If given without a path (just --resume), auto-detect "
                        "the most recent run directory under output-dir.")

    return p.parse_args()


def create_run_dir(base_dir: str | Path, name: str) -> Path:
    """Create a timestamped run directory: base_dir/YYYYMMDD_HHMMSS_name/"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{name}" if name else ""
    run_dir = Path(base_dir) / f"{ts}{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def resolve_resume_dir(args: argparse.Namespace) -> Path:
    """Determine the run directory to resume from."""
    if isinstance(args.resume, str):
        run_dir = Path(args.resume)
        if not run_dir.exists():
            print(f"[ERROR] Resume directory not found: {run_dir}", file=sys.stderr)
            sys.exit(1)
        return run_dir

    # Auto-detect: find the most recent timestamped directory under output-dir
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"[ERROR] Output directory does not exist: {output_dir}", file=sys.stderr)
        sys.exit(1)

    subdirs = [d for d in output_dir.iterdir() if d.is_dir()
               and d.name[:8].isdigit()]  # starts with YYYYMMDD
    if not subdirs:
        print(f"[ERROR] No run directories found in {output_dir}", file=sys.stderr)
        sys.exit(1)

    return max(subdirs, key=lambda d: d.name)


def save_config(run_dir: Path, args: argparse.Namespace, dataset_size: int,
                total_wall: float) -> None:
    """Save experiment configuration as JSON."""
    config = {
        "experiment_name": args.name or Path(args.dataset).stem,
        "timestamp": datetime.now().isoformat(),
        "dataset": {
            "file": str(args.dataset),
            "size": dataset_size,
            "prompt_field": args.prompt_field,
            "id_field": args.id_field,
        },
        "agent": {
            "model": args.model,
            "source": args.source,
            "base_url": args.base_url,
            "auto_load_tools": not args.no_tools,
            "auto_load_skills": not args.no_skills,
            "auto_load_utilities": args.utilities,
        },
        "execution": {
            "workers": args.workers,
            "per_item_timeout_seconds": args.timeout,
        },
        "result": {
            "total": dataset_size,
            "total_wall_time_seconds": round(total_wall, 2),
        },
    }
    with open(run_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def save_summary(run_dir: Path, report: ExperimentReport,
                 total_wall: float, args: argparse.Namespace) -> None:
    """Save human-readable summary."""
    lines = [
        f"Experiment: {args.name or Path(args.dataset).stem}",
        f"Timestamp:  {datetime.now().isoformat()}",
        f"Dataset:    {args.dataset} ({report.total} items)",
        f"LLM:        {args.model} (source={args.source})",
        f"Workers:    {args.workers}, Timeout: {args.timeout}s/item",
        "",
        f"{'='*50}",
        f"Results: {report.successes}/{report.total} success",
        f"  Errors:   {report.errors}",
        f"  Timeouts: {report.timeouts}",
        f"  Avg time: {report.avg_wall_time:.1f}s/item",
        f"  Total:    {total_wall:.1f}s",
        "",
        "Per-item breakdown:",
    ]
    for r in report.results:
        cat = r.item_metadata.get("category", "?")
        status_icon = {"success": "✓", "error": "✗", "timeout": "⏱"}.get(r.status, "?")
        lines.append(
            f"  {status_icon} {r.item_id} ({cat}): {r.status} "
            f"in {r.wall_time_seconds:.1f}s, {r.code_executions} code runs"
        )
        if r.error_message:
            lines.append(f"    Error: {r.error_message[:150]}")

    with open(run_dir / "summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def rebuild_report(results: list[ExperimentResult], total: int) -> ExperimentReport:
    """Build an ExperimentReport from an arbitrary list of results."""
    successes = sum(1 for r in results if r.status == "success")
    errors = sum(1 for r in results if r.status == "error")
    timeouts = sum(1 for r in results if r.status == "timeout")
    total_item_wall = sum(r.wall_time_seconds for r in results)
    return ExperimentReport(
        total=total,
        successes=successes,
        errors=errors,
        timeouts=timeouts,
        total_wall_time=total_item_wall,
        avg_wall_time=total_item_wall / total if total else 0.0,
        results=results,
    )


def write_final_outputs(
    run_dir: Path,
    results: list[ExperimentResult],
    total: int,
    total_wall: float,
    args: argparse.Namespace,
) -> None:
    """Regenerate all output files from a list of results."""
    from CAi.experiment.persistence import save_csv, save_json

    report = rebuild_report(results, total)
    report.output_path = str(run_dir / "results.json")
    save_json(report, run_dir / "results.json")
    save_csv(report, run_dir / "results.csv")
    save_config(run_dir, args, total, total_wall)
    save_summary(run_dir, report, total_wall, args)


def main() -> None:
    args = parse_args()

    # Load dataset
    dataset = load_dataset(
        args.dataset,
        prompt_field=args.prompt_field,
        id_field=args.id_field,
    )
    if not dataset:
        print(f"[ERROR] Dataset is empty: {args.dataset}", file=sys.stderr)
        sys.exit(1)

    total_dataset_size = len(dataset)
    exp_name = args.name or Path(args.dataset).stem

    # Build agent args
    agent_args = {
        "llm": args.model,
        "source": args.source,
        "base_url": args.base_url,
        "api_key": LLM_API_KEY,
        "auto_load_tools": not args.no_tools,
        "auto_load_skills": not args.no_skills,
        "auto_load_utilities": args.utilities,
    }

    # ── Resume logic ──────────────────────────────────────────────
    old_results: list[ExperimentResult] = []
    run_dir: Path | None = None

    if args.resume is not None:
        run_dir = resolve_resume_dir(args)
        checkpoint_file = run_dir / "checkpoint.jsonl"
        if not checkpoint_file.exists():
            print(f"[ERROR] No checkpoint found at {checkpoint_file}", file=sys.stderr)
            sys.exit(1)

        old_results = load_checkpoint(checkpoint_file)
        completed_ids = completed_item_ids(old_results)
        remaining = [item for item in dataset
                      if item.id is None or item.id not in completed_ids]

        print(f"[RESUME] Loaded {len(old_results)} completed results from {checkpoint_file}")
        print(f"[RESUME] {len(remaining)}/{total_dataset_size} items remaining")

        if not remaining:
            print("[RESUME] All items already completed. Regenerating outputs.")
            write_final_outputs(run_dir, old_results, total_dataset_size, 0.0, args)
            print(f"\nSaved to: {run_dir}/")
            return

        dataset_to_run = remaining
    else:
        run_dir = create_run_dir(args.output_dir, exp_name)
        dataset_to_run = dataset

    print(f"[INFO] Run directory: {run_dir}")
    print(f"[INFO] Running {len(dataset_to_run)} tasks (total dataset: {total_dataset_size})")
    print(f"[INFO] LLM: model={args.model}, source={args.source}")
    print(f"[INFO] Workers: {args.workers}, Timeout: {args.timeout}s/item\n")

    # ── Callbacks ──────────────────────────────────────────────────
    checkpoint_file = run_dir / "checkpoint.jsonl"
    run_start = time.monotonic()

    def on_item_start(done: int, total: int, item: DatasetItem) -> None:
        elapsed = time.monotonic() - run_start
        cat = item.metadata.get("category", "?")
        print(f"  [▶] [{done+1}/{total}] {item.id} ({cat}) — starting  (elapsed {elapsed:.0f}s)")

    def on_progress(done: int, total: int, result: ExperimentResult) -> None:
        elapsed = time.monotonic() - run_start
        icon = {"success": "✓", "error": "✗", "timeout": "⏱"}.get(result.status, "?")
        cat = result.item_metadata.get("category", "?")
        print(
            f"  [{icon}] [{done}/{total}] {result.item_id} ({cat}): "
            f"{result.status} in {result.wall_time_seconds:.1f}s  (elapsed {elapsed:.0f}s)"
        )
        if result.error_message:
            print(f"       Error: {result.error_message[:200]}")

    def on_step(item_id: str, event: dict) -> None:
        etype = event.get("type", "")
        content = event.get("content", "")
        if etype == "observation":
            preview = content[:200].replace("\n", " ")
            print(f"    └─ code executed: {preview}")
        elif etype == "message_end":
            preview = content[:150].replace("\n", " ")
            print(f"    └─ response: {preview}")

    # ── Run experiment ─────────────────────────────────────────────
    report = run_experiment(
        dataset_to_run,
        agent_args=agent_args,
        max_workers=args.workers,
        per_item_timeout_seconds=args.timeout,
        on_progress=on_progress,
        on_item_start=on_item_start,
        on_step=on_step if args.workers <= 1 else None,
        checkpoint_path=checkpoint_file,
    )

    total_wall = time.monotonic() - run_start

    # ── Merge with old results if resuming ─────────────────────────
    if old_results:
        all_results = merge_results(old_results, report.results)
        report = rebuild_report(all_results, total_dataset_size)
        report.output_path = str(run_dir / "results.json")
        # Rewrite full checkpoint so it's consistent with merged results
        # Overwrite (not append) the checkpoint with merged results
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            import json as _json
            for r in all_results:
                f.write(_json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    else:
        report.output_path = str(run_dir / "results.json")

    # ── Write final outputs ────────────────────────────────────────
    from CAi.experiment.persistence import save_csv, save_json

    save_json(report, run_dir / "results.json")
    save_csv(report, run_dir / "results.csv")
    save_config(run_dir, args, total_dataset_size, total_wall)
    save_summary(run_dir, report, total_wall, args)

    # Print summary
    print(f"\n{'='*50}")
    print(f"Results: {report.successes}/{report.total} success")
    print(f"  Errors:   {report.errors}")
    print(f"  Timeouts: {report.timeouts}")
    print(f"  Avg time: {report.avg_wall_time:.1f}s/item")
    print(f"  Total:    {total_wall:.1f}s")
    print(f"\nSaved to: {run_dir}/")
    print("  ├── config.json")
    print("  ├── checkpoint.jsonl")
    print("  ├── results.json")
    print("  ├── results.csv")
    print("  └── summary.txt")


if __name__ == "__main__":
    main()
