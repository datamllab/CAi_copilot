"""Utility effect evaluation — compares agent behavior with vs without utilities.

These tests require real LLM API credentials. The toolkit tools are mocked
(no tool server needed) so only LLM API calls hit the network.

Usage:
    # Run all utility effect tests (requires LLM_API_KEY)
    pytest tests/eval/test_utility_effect.py -v -m slow

    # Run only a specific task
    pytest tests/eval/test_utility_effect.py -v -k "T1"
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Standard evaluation tasks
# ---------------------------------------------------------------------------
# Each task is a (prompt, expected_tools) pair.
# expected_tools: set of tool names that should appear in the call log.

TASKS = [
    (
        "T1",
        (
            "Based on scaffold c1cc(CCO)cc(*)c1, generate 5 analogs and calculate SCScore. "
            "Report the top 3 by lowest SCScore."
        ),
        {"scaffold", "scscore"},
    ),
    (
        "T2",
        (
            "Generate 10 novel molecules from scratch (de novo). Calculate SCScore for each "
            "and report the 5 most synthetically accessible ones."
        ),
        {"reinvent4", "scscore"},
    ),
    (
        "T3",
        (
            "For molecule CC(=O)Oc1ccccc1C(=O)O (aspirin), predict toxicity and pMIC. "
            "Summarize the drug-likeness profile."
        ),
        {"toxicity", "pmic"},
    ),
    (
        "T4",
        (
            "Generate 20 novel molecules from scratch, then predict SCScore for all of them "
            "and filter to keep only those with SCScore < 3.0."
        ),
        {"reinvent4", "scscore"},
    ),
    (
        "T5",
        (
            "Generate analogs of CC(=O)Nc1ccc(O)cc1 using mol2mol (5 variants). "
            "For each analog, calculate SCScore and predict toxicity."
        ),
        {"reinvent4", "scscore", "toxicity"},
    ),
    (
        "T6",
        (
            "Using scaffold c1cc(*)ccc1, generate 5 analogs with LibINVENT and 5 with RNN scaffold. "
            "Compare the results and rank all molecules by SCScore."
        ),
        {"scaffold", "libinvent", "scscore"},
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_metrics(steps: list[dict], call_log: list[dict]) -> dict:
    """Extract evaluation metrics from agent execution."""
    turns = sum(1 for s in steps if s.get("type") == "message_end")
    tool_names_used = [c["tool"] for c in call_log]
    unique_tools = set(tool_names_used)

    return {
        "turns": turns,
        "tool_calls": len(call_log),
        "unique_tools": len(unique_tools),
        "tool_names": sorted(unique_tools),
        "tool_call_sequence": tool_names_used,
        "has_error": any(
            "error" in s.get("content", "").lower()
            for s in steps
            if s.get("type") in ("message_end", "observation")
        ),
    }


def save_metrics(task_id: str, variant: str, metrics: dict) -> None:
    """Append metrics to a JSON file for post-analysis."""
    report_path = Path("agent_workspace/eval_metrics.jsonl")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"task_id": task_id, "variant": variant, **metrics}
    with open(report_path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def check_task_completion(steps: list[dict]) -> bool:
    """Check if the agent completed the task (output contains <done/>)."""
    all_content = "\n".join(
        s.get("content", "") for s in steps
    )
    return "<done/>" in all_content


# ---------------------------------------------------------------------------
# Tests — with utilities
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("task_id,task_prompt,expected_tools", TASKS)
def test_task_with_utilities(task_id, task_prompt, expected_tools, real_llm_agent):
    """Run a single task WITH utilities enabled. Record metrics and assert completion."""
    agent, call_log = real_llm_agent

    steps = list(agent.run_with_history(task_prompt, history=[]))

    metrics = extract_metrics(steps, call_log)
    save_metrics(task_id, "with_utilities", metrics)

    # Assert agent completed the task
    assert check_task_completion(steps), f"Task {task_id} did not complete. Steps: {steps[-1] if steps else 'no steps'}"

    # Assert at least one expected tool was called
    called_tools = {c["tool"] for c in call_log}
    overlap = called_tools & expected_tools
    assert overlap, (
        f"Task {task_id}: no expected tools called. "
        f"Expected any of {expected_tools}, got {called_tools}"
    )


# ---------------------------------------------------------------------------
# Tests — without utilities (baseline)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("task_id,task_prompt,expected_tools", TASKS)
def test_task_without_utilities(task_id, task_prompt, expected_tools, real_llm_agent_no_utilities):
    """Run a single task WITHOUT utilities. Record metrics as baseline."""
    agent, call_log = real_llm_agent_no_utilities

    steps = list(agent.run_with_history(task_prompt, history=[]))

    metrics = extract_metrics(steps, call_log)
    save_metrics(task_id, "without_utilities", metrics)

    assert check_task_completion(steps), f"Task {task_id} did not complete. Steps: {steps[-1] if steps else 'no steps'}"

    called_tools = {c["tool"] for c in call_log}
    overlap = called_tools & expected_tools
    assert overlap, (
        f"Task {task_id}: no expected tools called. "
        f"Expected any of {expected_tools}, got {called_tools}"
    )


# ---------------------------------------------------------------------------
# Comparison test — run all tasks and compare metrics
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_utility_effect_comparison(real_llm_agent, real_llm_agent_no_utilities):
    """Run all tasks with and without utilities, compare aggregate metrics.

    Expected outcome: tasks with utilities should have fewer turns and
    fewer redundant tool calls on average.
    """
    # Clear previous metrics
    report_path = Path("agent_workspace/eval_metrics.jsonl")
    if report_path.exists():
        report_path.unlink()

    results = {"with_utilities": [], "without_utilities": []}

    for _task_id, task_prompt, _expected_tools in TASKS:
        # With utilities
        agent_with, call_log_with = real_llm_agent
        steps_with = list(agent_with.run_with_history(task_prompt, history=[]))
        metrics_with = extract_metrics(steps_with, call_log_with)
        results["with_utilities"].append(metrics_with)

        # Without utilities
        agent_without, call_log_without = real_llm_agent_no_utilities
        steps_without = list(agent_without.run_with_history(task_prompt, history=[]))
        metrics_without = extract_metrics(steps_without, call_log_without)
        results["without_utilities"].append(metrics_without)

    # Compute averages
    def avg_turns(variant_metrics):
        return sum(m["turns"] for m in variant_metrics) / len(variant_metrics)

    def avg_tool_calls(variant_metrics):
        return sum(m["tool_calls"] for m in variant_metrics) / len(variant_metrics)

    with_turns = avg_turns(results["with_utilities"])
    without_turns = avg_turns(results["without_utilities"])
    with_tools = avg_tool_calls(results["with_utilities"])
    without_tools = avg_tool_calls(results["without_utilities"])

    # Print comparison summary
    print(f"\n{'='*60}")
    print("Utility Effect Comparison")
    print(f"{'='*60}")
    print(f"{'Metric':<25} {'With Util':>12} {'Without Util':>14} {'Delta':>10}")
    print(f"{'-'*60}")
    print(f"{'Avg turns':<25} {with_turns:>12.2f} {without_turns:>14.2f} {with_turns - without_turns:>10.2f}")
    print(f"{'Avg tool calls':<25} {with_tools:>12.2f} {without_tools:>14.2f} {with_tools - without_tools:>10.2f}")
    print(f"{'='*60}")

    # Save summary
    summary = {
        "task": "comparison_summary",
        "with_utilities": {"avg_turns": with_turns, "avg_tool_calls": with_tools},
        "without_utilities": {"avg_turns": without_turns, "avg_tool_calls": without_tools},
    }
    save_metrics("SUMMARY", "comparison", summary)

    # Assert: with utilities should be <= turns than without
    # (This is a soft assertion — in practice utilities should reduce turns)
    # We don't fail the test if it's not met, just log it.
    if with_turns > without_turns:
        print(f"WARNING: Utilities did not reduce turns. Delta: {with_turns - without_turns:.2f}")
