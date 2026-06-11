"""Memory management endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from CAi.logger import get_logger

from ..deps import SessionManager, get_agent, get_session_manager

logger = get_logger("CAi.web_ui.memory")

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store_or_404(agent):
    """Pull the agent's MemoryStore, or raise 404 if disabled."""
    store = getattr(agent, "memory_store", None)
    if store is None:
        raise HTTPException(status_code=404, detail="Memory system not enabled")
    return store


# ---------------------------------------------------------------------------
# Extraction (manual trigger)
# ---------------------------------------------------------------------------


class ExtractRequest(BaseModel):
    conversation_id: str | None = None


@router.post("/extract")
async def extract_memories(
    request: ExtractRequest,
    agent=Depends(get_agent),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """Trigger memory extraction from the most recent session log.

    Runs the MemoryManager curator LLM to analyze the conversation
    and save relevant facts for future sessions.
    """
    store = getattr(agent, "memory_store", None)
    if store is None:
        return {"status": "disabled", "message": "Memory system not enabled"}

    # Find session log
    session_log: list = []
    user_message = ""
    if request.conversation_id:
        session = session_mgr._sessions.get(request.conversation_id)
        if session:
            log = session.last_session_log
            session_log = log.get("log", [])
            user_message = log.get("user_message", "")
    else:
        for s in session_mgr._sessions.values():
            log = s.last_session_log
            if log.get("log"):
                session_log = log["log"]
                user_message = log.get("user_message", "")

    if not session_log:
        return {"status": "no_data", "message": "No recent session data"}

    from CAi.CAi_agent.memory import MemoryManager

    manager = MemoryManager(store, llm=agent.curator_llm)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, manager.extract, session_log, user_message)
    return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# CRUD — list / get / create / update / delete
# ---------------------------------------------------------------------------


@router.get("/")
async def list_memories(category: str | None = None, agent=Depends(get_agent)):
    """List all memories, optionally filtered by category."""
    store = _get_store_or_404(agent)
    entries = store.list_all(category=category)
    return {
        "memories": [e.to_dict() for e in entries],
        "total": len(entries),
        "max": store._max,
    }


@router.get("/search")
async def search_memories(
    q: str = "",
    category: str | None = None,
    limit: int = 15,
    agent=Depends(get_agent),
):
    """Search memories by keyword query."""
    store = _get_store_or_404(agent)
    results = store.search(q, category=category, limit=limit)
    return {
        "memories": [e.to_dict() for e in results],
        "total": len(results),
    }


@router.get("/{entry_id}")
async def get_memory(entry_id: str, agent=Depends(get_agent)):
    """Get a single memory by ID."""
    store = _get_store_or_404(agent)
    entry = store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Memory '{entry_id}' not found")
    return entry.to_dict()


class CreateMemoryRequest(BaseModel):
    content: str
    category: str = "domain_fact"
    tags: list[str] = []
    importance: int = 5


@router.post("/")
async def create_memory(request: CreateMemoryRequest, agent=Depends(get_agent)):
    """Manually add a memory."""
    store = _get_store_or_404(agent)
    entry = store.save(
        request.content,
        category=request.category,
        tags=request.tags,
        source="user",
        importance=request.importance,
    )
    if entry is None:
        return {"status": "merged", "message": "Similar memory already exists (merged)"}
    logger.info("Memory created via API: %s", entry.id)
    return {"status": "ok", "memory": entry.to_dict()}


class UpdateMemoryRequest(BaseModel):
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    importance: int | None = None


@router.patch("/{entry_id}")
async def update_memory(entry_id: str, request: UpdateMemoryRequest, agent=Depends(get_agent)):
    """Edit a memory's fields."""
    store = _get_store_or_404(agent)
    kwargs = {}
    if request.content is not None:
        kwargs["content"] = request.content
    if request.category is not None:
        kwargs["category"] = request.category
    if request.tags is not None:
        kwargs["tags"] = request.tags
    if request.importance is not None:
        kwargs["importance"] = request.importance
    if not kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    entry = store.update(entry_id, **kwargs)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Memory '{entry_id}' not found")
    logger.info("Memory updated via API: %s", entry_id)
    return {"status": "ok", "memory": entry.to_dict()}


@router.delete("/{entry_id}")
async def delete_memory(entry_id: str, agent=Depends(get_agent)):
    """Delete a memory."""
    store = _get_store_or_404(agent)
    if not store.delete(entry_id):
        raise HTTPException(status_code=404, detail=f"Memory '{entry_id}' not found")
    logger.info("Memory deleted via API: %s", entry_id)
    return {"status": "ok", "deleted": entry_id}


# ---------------------------------------------------------------------------
# Traces (MemoryManager LLM call history)
# ---------------------------------------------------------------------------


@router.get("/traces")
async def list_traces(limit: int = 20, agent=Depends(get_agent)):
    """List recent MemoryManager traces."""
    store = getattr(agent, "memory_store", None)
    if store is None:
        return {"traces": []}

    from CAi.CAi_agent.memory import MemoryManager

    manager = MemoryManager(store, llm=None)
    return {"traces": manager.list_traces(limit=limit)}


@router.get("/traces/{filename}")
async def get_trace(filename: str, agent=Depends(get_agent)):
    """Fetch one trace by filename."""
    store = getattr(agent, "memory_store", None)
    if store is None:
        return {"error": "memory disabled"}

    from CAi.CAi_agent.memory import MemoryManager

    manager = MemoryManager(store, llm=None)
    trace = manager.get_trace(filename)
    if trace is None:
        return {"error": "trace not found"}
    return trace
