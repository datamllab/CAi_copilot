"""Terminal-based evaluation runner for quick manual testing.

No web UI needed — runs a single task in the terminal with formatted output.

Usage:
    # Run task T1 with utilities enabled
    python -m tests.eval.run_eval --task T1

    # Run task T2 without utilities (baseline)
    python -m tests.eval.run_eval --task T2 --no-utilities

    # Use a custom prompt instead of a predefined task
    python -m tests.eval.run_eval --prompt "Generate 5 molecules from scratch and calculate SCScore."

    # Show verbose step-by-step output
    python -m tests.eval.run_eval --task T1 -v
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path so CAi is importable
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))


# ---------------------------------------------------------------------------
# Predefined evaluation tasks (same as test_utility_effect.py)
# ---------------------------------------------------------------------------

TASKS = {
    "T1": (
        "Based on scaffold c1cc(CCO)cc(*)c1, generate 5 analogs and calculate SCScore. "
        "Report the top 3 by lowest SCScore.",
        {"scaffold", "scscore"},
    ),
    "T2": (
        "Generate 10 novel molecules from scratch (de novo). Calculate SCScore for each "
        "and report the 5 most synthetically accessible ones.",
        {"reinvent4", "scscore"},
    ),
    "T3": (
        "For molecule CC(=O)Oc1ccccc1C(=O)O (aspirin), predict toxicity and pMIC. "
        "Summarize the drug-likeness profile.",
        {"toxicity", "pmic"},
    ),
    "T4": (
        "Generate 20 novel molecules from scratch, then predict SCScore for all of them "
        "and filter to keep only those with SCScore < 3.0.",
        {"reinvent4", "scscore"},
    ),
    "T5": (
        "Generate analogs of CC(=O)Nc1ccc(O)cc1 using mol2mol (5 variants). "
        "For each analog, calculate SCScore and predict toxicity.",
        {"reinvent4", "scscore", "toxicity"},
    ),
    "T6": (
        "Using scaffold c1cc(*)ccc1, generate 5 analogs with LibINVENT and 5 with RNN scaffold. "
        "Compare the results and rank all molecules by SCScore.",
        {"scaffold", "libinvent", "scscore"},
    ),
}


# ---------------------------------------------------------------------------
# Terminal output helpers
# ---------------------------------------------------------------------------

SEPARATOR = "=" * 72


def print_header(text: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {text}")
    print(SEPARATOR)


def print_step(step: dict, verbose: bool = False) -> None:
    """Print a single execution step."""
    step_type = step.get("type", "unknown")
    content = step.get("content", "")

    if step_type == "message_end":
        # LLM response — print the text content
        if content.strip():
            # Truncate very long outputs unless verbose
            display = content if verbose or len(content) < 2000 else content[:2000] + "..."
            print(f"\n[LLM]\n{display}")

    elif step_type == "observation":
        # Code execution result
        if verbose and content.strip():
            display = content if len(content) < 1500 else content[:1500] + "..."
            print(f"\n  [EXEC] {display}")
        elif content.strip():
            # Short summary
            first_line = content.strip().split("\n")[0][:200]
            print(f"\n  [EXEC] {first_line}")

    elif step_type == "error":
        print(f"\n  [ERROR] {content[:500]}")


def print_summary(metrics: dict, prompt: str) -> None:
    print_header("Summary")
    print(f"  Prompt:       {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
    print(f"  Turns:        {metrics['turns']}")
    print(f"  Tool calls:   {metrics['tool_calls']}")
    print(f"  Unique tools: {metrics['unique_tools']}")
    if metrics.get("tool_names"):
        print(f"  Tools used:   {', '.join(metrics['tool_names'])}")
    print(f"  Has error:    {metrics['has_error']}")
    if metrics.get("tool_call_sequence"):
        print(f"  Call order:   {' -> '.join(metrics['tool_call_sequence'])}")
    print()


def extract_metrics(steps: list[dict], call_log: list[dict]) -> dict:
    """Extract metrics from agent execution steps."""
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run a CAi agent evaluation task from the terminal.",
    )
    parser.add_argument(
        "--task",
        choices=sorted(TASKS.keys()),
        help="Predefined task ID to run (T1-T6).",
    )
    parser.add_argument(
        "--prompt",
        help="Custom prompt to run instead of a predefined task.",
    )
    parser.add_argument(
        "--no-utilities",
        action="store_true",
        help="Disable utilities (baseline mode).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show full step-by-step output without truncation.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Agent timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--save-metrics",
        action="store_true",
        help="Save metrics to agent_workspace/eval_metrics.jsonl.",
    )

    args = parser.parse_args()

    if not args.task and not args.prompt:
        parser.error("Provide either --task <ID> or --prompt '...'")

    # Resolve prompt and expected tools
    if args.prompt:
        prompt = args.prompt
        expected_tools: set[str] = set()
        task_id = "custom"
    else:
        task_id = args.task
        prompt, expected_tools = TASKS[task_id]

    # Import here so imports don't slow down --help
    from CAi.CAi_agent.base import A1pro

    print_header(f"Task: {task_id}")
    print(f"  Utilities: {'disabled' if args.no_utilities else 'enabled'}")
    print(f"  Timeout:   {args.timeout}s")
    print(f"\n  Prompt:\n  {prompt}")

    # Create agent
    agent = A1pro(
        auto_load_tools=True,
        auto_load_skills=True,
        auto_load_utilities=not args.no_utilities,
        timeout_seconds=args.timeout,
    )

    # Create call log collector
    call_log: list[dict] = []
    original_run_tool = None

    # Patch run_tool to capture calls
    try:
        import CAi.toolkit.functions.generation as gen
        import CAi.toolkit.functions.evaluation as evl
        original_gen_run_tool = gen.run_tool
        original_evl_run_tool = evl.run_tool

        def logging_run_tool(tool, payload, **kwargs):
            call_log.append({"tool": tool, "payload": dict(payload)})
            return original_gen_run_tool(tool, payload, **kwargs)

        gen.run_tool = logging_run_tool
        evl.run_tool = logging_run_tool
    except Exception:
        pass  # best-effort

    # Run agent
    print_header("Execution")
    t0 = time.time()
    steps = []

    try:
        for step in agent.run_with_history(prompt, history=[]):
            steps.append(step)
            print_step(step, verbose=args.verbose)
    except KeyboardInterrupt:
        print("\n\n  Interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n  [FATAL] {e}")
        sys.exit(1)

    elapsed = time.time() - t0

    # Restore
    try:
        gen.run_tool = original_gen_run_tool
        evl.run_tool = original_evl_run_tool
    except Exception:
        pass

    # Final output
    print_header("Final Response")
    all_content = "\n".join(s.get("content", "") for s in steps if s.get("type") == "message_end")
    # Show the last LLM response as the final answer
    last_llm_content = ""
    for s in reversed(steps):
        if s.get("type") == "message_end" and s.get("content", "").strip():
            last_llm_content = s["content"]
            break
    if last_llm_content:
        display = last_llm_content if args.verbose else last_llm_content[:3000]
        print(display)

    # Check completion
    completed = "<done/>" in all_content

    # Metrics
    metrics = extract_metrics(steps, call_log)
    metrics["elapsed_seconds"] = round(elapsed, 1)
    metrics["completed"] = completed

    print_summary(metrics, prompt)

    if not completed:
        print("  WARNING: Agent did not complete the task (no <done/> signal).")

    if expected_tools:
        called = set(c["tool"] for c in call_log)
        missing = expected_tools - called
        if missing:
            print(f"  NOTE: Expected tools not called: {missing}")

    # Save metrics if requested
    if args.save_metrics:
        report_path = Path("agent_workspace/eval_metrics.jsonl")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        variant = "without_utilities" if args.no_utilities else "with_utilities"
        record = {"task_id": task_id, "variant": variant, **metrics}
        with open(report_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  Metrics saved to {report_path}")


if __name__ == "__main__":
    main()
