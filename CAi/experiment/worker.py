"""Subprocess worker for experiment runs.

Each worker runs in its own Python process (via multiprocessing spawn),
giving full isolation: independent REPL kernel, independent builtins,
independent module-level globals.

IPC uses plain dicts to avoid pickle issues with dataclasses.
"""

from __future__ import annotations

import signal
import time
import traceback
from collections.abc import Callable
from typing import Any


def run_single_experiment(
    item_dict: dict,
    agent_args: dict,
    timeout_seconds: int,
    step_callback: Callable[[dict], None] | None = None,
) -> dict:
    """Run one dataset item through an isolated A1pro agent.

    This function runs in a **child process** created by
    ``multiprocessing.get_context("spawn")``.  It creates a fresh A1pro
    (with its own REPL kernel, builtins, etc.), executes the prompt, and
    returns the result as a plain dict.

    Args:
        item_dict: Plain dict with keys: prompt, id, history, metadata,
                   expected_output — describing one dataset item.
        agent_args: Dict of kwargs forwarded to ``A1pro()`` constructor.
        timeout_seconds: Hard per-item timeout (SIGALRM).
        step_callback: Optional callback invoked for each streaming event
                       yielded by the agent. Only used in sequential mode;
                       pass ``None`` in multiprocessing mode.

    Returns:
        Plain dict matching ``ExperimentResult`` fields.
    """
    # Set a hard timeout via SIGALRM so runaway agent loops don't hang
    def _timeout_handler(signum, frame):
        raise TimeoutError(f"Item timed out after {timeout_seconds}s")

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_seconds)

    start = time.monotonic()
    result: dict[str, Any] = {
        "item_id": item_dict.get("id"),
        "prompt": item_dict["prompt"],
        "final_response": "",
        "status": "error",
        "error_message": None,
        "wall_time_seconds": 0.0,
        "steps": [],
        "code_executions": 0,
        "item_metadata": item_dict.get("metadata", {}),
        "expected_output": item_dict.get("expected_output"),
        "match_score": None,
    }

    try:
        from CAi.CAi_agent.agent import A1pro

        agent = A1pro(**agent_args)

        history = item_dict.get("history", [])
        prompt = item_dict["prompt"]

        # Consume the streaming generator and collect events
        steps = []
        code_execution_count = 0
        last_message = ""

        for event in agent.run_with_history_streaming(prompt, history):
            etype = event.get("type")
            content = event.get("content", "")

            if step_callback:
                step_callback(event)

            if etype == "message_end":
                last_message = content
                steps.append({"type": "message", "content": content})
            elif etype == "observation":
                code_execution_count += 1
                steps.append({"type": "observation", "content": content})

        # Strip <done/> tag from final response
        final_response = last_message
        if "<done/>" in final_response:
            final_response = final_response.replace("<done/>", "").strip()

        elapsed = time.monotonic() - start

        result["final_response"] = final_response
        result["status"] = "success"
        result["wall_time_seconds"] = round(elapsed, 2)
        result["steps"] = steps
        result["code_executions"] = code_execution_count

    except TimeoutError as e:
        elapsed = time.monotonic() - start
        result["status"] = "timeout"
        result["error_message"] = str(e)
        result["wall_time_seconds"] = round(elapsed, 2)

    except Exception as e:
        elapsed = time.monotonic() - start
        result["status"] = "error"
        result["error_message"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        result["wall_time_seconds"] = round(elapsed, 2)

    finally:
        signal.alarm(0)  # Cancel any pending alarm
        signal.signal(signal.SIGALRM, old_handler)

    return result
