"""Utility library maintenance endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from CAi.logger import get_logger

from ..deps import SessionManager, get_agent, get_session_manager

logger = get_logger("CAi.web_ui.utilities")

router = APIRouter(prefix="/api/utilities", tags=["utilities"])


# ---------------------------------------------------------------------------
# Status computation — single source of truth for UI badges
# ---------------------------------------------------------------------------

# Thresholds expressed as constants so the UI never re-implements the rules.
_HEALTHY_MIN_CALLS = 5
_HEALTHY_MIN_RATE = 0.9
_UNSTABLE_MIN_CALLS = 3
_UNSTABLE_MAX_RATE = 0.5


def _compute_status(call_count: int, success_count: int) -> str:
    """Classify a utility into one of: new / trial / healthy / unstable.

    The frontend uses this string verbatim to pick colors and copy.
    Keep the categories stable; tune thresholds via the constants above.
    """
    if call_count == 0:
        return "new"
    rate = success_count / call_count if call_count else 0.0
    if call_count >= _HEALTHY_MIN_CALLS and rate >= _HEALTHY_MIN_RATE:
        return "healthy"
    if call_count >= _UNSTABLE_MIN_CALLS and rate < _UNSTABLE_MAX_RATE:
        return "unstable"
    return "trial"


def _enrich(meta: dict) -> dict:
    """Attach `success_rate` and `status` to a registry meta dict."""
    calls = meta.get("call_count", 0) or 0
    successes = meta.get("success_count", 0) or 0
    return {
        **meta,
        "success_rate": (successes / calls) if calls else None,
        "status": _compute_status(calls, successes),
    }


def _get_registry_or_404(agent):
    """Pull the agent's UtilityRegistry, or raise 404 if disabled."""
    registry = getattr(agent, "utility_registry", None)
    if registry is None:
        raise HTTPException(status_code=404, detail="Utility system not enabled")
    return registry


# ---------------------------------------------------------------------------
# Maintenance (existing)
# ---------------------------------------------------------------------------


class MaintainRequest(BaseModel):
    skip_cooldown: bool = False
    mode: str = "execute"  # "execute" or "preview"


@router.post("/maintain")
async def maintain(
    request: MaintainRequest,
    agent=Depends(get_agent),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """Trigger utility library maintenance.

    Modes:
        - "preview": analyze session log and return proposed actions without applying
        - "execute": analyze and apply actions to the utility library

    If ``conversation_id`` is set, that conversation's session log is used.
    Otherwise the most recently active session is selected.
    """
    registry = getattr(agent, "utility_registry", None)
    if registry is None:
        return {"status": "disabled", "message": "Utility system not enabled"}

    # Get session log: try specific conversation, then fall back to most recent.
    session_log: list = []
    user_message = ""
    for s in session_mgr._sessions.values():
        log = s.last_session_log
        if log.get("log"):
            session_log = log["log"]
            user_message = log.get("user_message", "")

    if not session_log:
        return {"status": "no_data", "message": "No recent session data"}

    from CAi.CAi_agent.utilities import UtilityManager

    manager = UtilityManager(registry, llm=agent.curator_llm)
    loop = asyncio.get_event_loop()

    if request.mode == "preview":
        actions = await loop.run_in_executor(None, manager.preview, session_log, user_message)
        return {"status": "ok", "preview": actions}
    else:
        result = await loop.run_in_executor(None, manager.maintain, session_log, user_message)
        return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# Browsing — read-only display for the frontend panel
# ---------------------------------------------------------------------------


@router.get("/list")
async def list_utilities(agent=Depends(get_agent)):
    """List all utilities with computed display fields.

    Returns:
        {
            "utilities": [
                {name, description, call_count, success_count,
                 success_rate, status, last_used, ...},
                ...
            ],
            "total": int,
            "max": int,
        }
    """
    registry = getattr(agent, "utility_registry", None)
    if registry is None:
        return {"utilities": [], "total": 0, "max": 0}

    enriched = [_enrich(m) for m in registry.list_meta()]
    # Most useful first: by last_used desc, then call_count desc.
    enriched.sort(
        key=lambda u: (u.get("last_used") or "", u.get("call_count", 0)),
        reverse=True,
    )
    return {
        "utilities": enriched,
        "total": len(enriched),
        "max": getattr(registry, "_max", 20),
    }


@router.get("/detail/{name}")
async def get_utility(name: str, agent=Depends(get_agent)):
    """Full data for one utility, including source code."""
    registry = _get_registry_or_404(agent)
    spec = registry.specs.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Utility '{name}' not found")

    meta = {
        "name": spec.name,
        "description": spec.description,
        "call_count": spec.call_count,
        "success_count": spec.success_count,
        "created_at": spec.created_at.isoformat() if spec.created_at else None,
        "last_used": spec.last_used.isoformat() if spec.last_used else None,
    }
    return {
        **_enrich(meta),
        "code": spec.code,
    }


@router.delete("/detail/{name}")
async def delete_utility(name: str, agent=Depends(get_agent)):
    """Remove a utility from the registry (and its .py file)."""
    registry = _get_registry_or_404(agent)
    if name not in registry.specs:
        raise HTTPException(status_code=404, detail=f"Utility '{name}' not found")
    registry.delete(name)
    logger.info("Utility deleted via API: %s", name)
    return {"status": "ok", "deleted": name}


# ---------------------------------------------------------------------------
# Traces (existing — UtilityManager LLM call history)
# ---------------------------------------------------------------------------


@router.get("/traces")
async def list_traces(limit: int = 20, agent=Depends(get_agent)):
    """List recent UtilityManager traces (LLM call history).

    Read-only — no LLM call is made, so we don't need a configured curator
    LLM here. Pass ``llm=None`` to skip lazy curator construction when
    only traces are being browsed.
    """
    registry = getattr(agent, "utility_registry", None)
    if registry is None:
        return {"traces": []}

    from CAi.CAi_agent.utilities import UtilityManager

    manager = UtilityManager(registry, llm=None)
    return {"traces": manager.list_traces(limit=limit)}


@router.get("/traces/{filename}")
async def get_trace(filename: str, agent=Depends(get_agent)):
    """Fetch one trace by filename (full prompt + response + actions).

    Read-only — see :func:`list_traces` for why ``llm=None`` is fine here.
    """
    registry = getattr(agent, "utility_registry", None)
    if registry is None:
        return {"error": "utilities disabled"}

    from CAi.CAi_agent.utilities import UtilityManager

    manager = UtilityManager(registry, llm=None)
    trace = manager.get_trace(filename)
    if trace is None:
        return {"error": "trace not found"}
    return trace
