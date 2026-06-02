"""CAi Experiment Runner — batch agent evaluation with multiprocessing.

Public API:
    from CAi.experiment import run_experiment, load_dataset, DatasetItem

    # From a file
    dataset = load_dataset("benchmark.csv", prompt_field="question", id_field="id")
    report = run_experiment(dataset, max_workers=4, output_path="results/exp.json")

    # Or inline
    dataset = [
        DatasetItem(id="q1", prompt="Calculate the molecular weight of aspirin"),
        DatasetItem(id="q2", prompt="Generate 5 drug-like molecules with DrugEx"),
    ]
    report = run_experiment(dataset, max_workers=1)
    print(f"{report.successes}/{report.total} success, avg {report.avg_wall_time:.1f}s")
"""

from .checkpoint import (
    CheckpointWriter,
    completed_item_ids,
    load_checkpoint,
    merge_results,
)
from .datasets import load_dataset
from .models import DatasetItem, ExperimentReport, ExperimentResult
from .runner import run_experiment

__all__ = [
    "CheckpointWriter",
    "DatasetItem",
    "ExperimentReport",
    "ExperimentResult",
    "completed_item_ids",
    "load_checkpoint",
    "load_dataset",
    "merge_results",
    "run_experiment",
]
