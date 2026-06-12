"""
HTTP client for the local tool server.

Every wrapper function in this package calls `run_tool(tool, payload, ...)`,
which submits a job to the FastAPI server (see `CAi/toolkit/server/app.py`)
and polls for completion.

Design notes:
  - Proxy bypass: we explicitly pass `proxies={"http": None, "https": None}`
    so corporate / system proxies don't try to route LAN / VPN addresses
    through an external proxy (was a real bug in the old code).
  - Backoff: polling uses a small exponential backoff bounded by
    MAX_POLL_INTERVAL, instead of a flat 3s sleep.
  - Config: server host/port come from CAi.config (single source of truth).
    The old hardcoded default (a Tailscale IP) is gone.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from CAi.config import TOOL_SERVER_HOST, TOOL_SERVER_PORT

_BASE_URL = f"http://{TOOL_SERVER_HOST}:{TOOL_SERVER_PORT}"
_NO_PROXY = {"http": None, "https": None}

# Polling tuning
_INITIAL_POLL_INTERVAL = 0.5
_MAX_POLL_INTERVAL = 10.0
_POLL_BACKOFF = 1.5

# Submission tuning — conda env startup + model loading can be slow
_SUBMIT_TIMEOUT = 120  # seconds for the HTTP POST (not the overall job timeout)
_SUBMIT_MAX_RETRIES = 3
_SUBMIT_RETRY_BASE_DELAY = 2.0  # seconds, doubles each retry
_POLL_TIMEOUT = 10  # seconds per polling GET (just a status check)


class ToolServerError(RuntimeError):
    """Raised when the tool server is unreachable or returns an unexpected shape."""


def ping() -> dict[str, Any]:
    """Call /health on the tool server. Returns the server's response dict.

    Raises ToolServerError if the server is unreachable.
    """
    try:
        r = requests.get(f"{_BASE_URL}/health", timeout=5, proxies=_NO_PROXY)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise ToolServerError(
            f"Tool server unreachable at {_BASE_URL}: {e}"
        ) from e


def run_tool(
    tool: str,
    payload: dict[str, Any],
    *,
    action: str = "default",
    timeout_mins: int = 5,
) -> dict[str, Any]:
    """Submit a job and poll until it finishes, fails, or times out.

    Returns the raw result dict from the tool (or {"error": "..."} on
    failure). This is the low-level primitive; higher-level wrappers
    adapt the shape to what the agent expects.
    """
    submit_url = f"{_BASE_URL}/run/{tool}/{action}"
    job_url = f"{_BASE_URL}/job"

    # 1. Submit (with retries — conda startup + model loading can exceed short timeouts)
    last_err: Exception | None = None
    for attempt in range(_SUBMIT_MAX_RETRIES):
        try:
            r = requests.post(
                submit_url, json=payload, timeout=_SUBMIT_TIMEOUT, proxies=_NO_PROXY
            )
            r.raise_for_status()
            data = r.json()
            break
        except requests.exceptions.HTTPError as e:
            return {
                "error": f"HTTP {e.response.status_code} from tool server: {e.response.text}"
            }
        except requests.RequestException as e:
            last_err = e
            if attempt < _SUBMIT_MAX_RETRIES - 1:
                delay = _SUBMIT_RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
            return {"error": f"Cannot reach tool server at {_BASE_URL} after {_SUBMIT_MAX_RETRIES} attempts: {last_err}"}

    if "error" in data:
        return {"error": f"Task submission rejected: {data['error']}"}
    job_id = data.get("job_id")
    if not job_id:
        return {"error": f"Submission returned no job_id: {data}"}

    # 2. Poll with exponential backoff
    deadline = time.time() + timeout_mins * 60
    interval = _INITIAL_POLL_INTERVAL
    while True:
        if time.time() > deadline:
            return {"error": f"Timeout: task did not finish within {timeout_mins} minutes."}
        try:
            r = requests.get(f"{job_url}/{job_id}", timeout=_POLL_TIMEOUT, proxies=_NO_PROXY)
            status = r.json()
        except requests.RequestException as e:
            return {"error": f"Polling failed: {e}"}

        state = status.get("status")
        if state == "running":
            time.sleep(interval)
            interval = min(interval * _POLL_BACKOFF, _MAX_POLL_INTERVAL)
            continue
        if state == "failed":
            return {"error": f"Server execution crashed: {status.get('data')}"}
        if state == "finished":
            return _unwrap_result(status)
        return {"error": f"Unknown job state: {state}"}


def _unwrap_result(status: dict[str, Any]) -> dict[str, Any]:
    """Normalise the `finished` status envelope into the tool's result dict."""
    result = status.get("data") or status.get("stdout")

    # Legacy path: some older tools emitted a stringified JSON on stdout.
    if isinstance(result, str):
        try:
            # Single quotes → double quotes was the old quick-fix
            result = json.loads(result.replace("'", '"'))
        except json.JSONDecodeError:
            return {"error": "Failed to parse string output into JSON.", "raw": result}

    if not result:
        return {"error": "Task finished but returned no data."}

    # Pass through explicit failures
    if isinstance(result, dict) and result.get("success") is False:
        return {"error": f"Tool execution failed: {result.get('error', 'Unknown error')}"}

    return result
