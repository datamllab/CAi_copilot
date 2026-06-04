"""Chat streaming endpoint and cancel."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from CAi.logger import get_logger

from ..chat_service import async_iter_agent, build_prompt, clean_stored_answer
from ..conversation_store import ConversationStore
from ..deps import (
    AgentSession,
    SessionManager,
    get_agent,
    get_agent_optional,
    get_cancel_events,
    get_session_manager,
    get_store,
    get_workspace_dir,
)

logger = get_logger("CAi.web_ui.chat")

router = APIRouter(prefix="/api", tags=["chat"])


# ---------------------------------------------------------------------------
# Utility maintenance helper
# ---------------------------------------------------------------------------


async def _flush_usage_only(session: AgentSession) -> None:
    """Flush utility usage stats without triggering LLM maintenance.

    Runs as a fire-and-forget background task after the SSE stream completes.
    Each session has its own kernel with its own usage accumulator.
    """
    try:
        agent = session.agent
        registry = getattr(agent, "utility_registry", None)
        if registry is None:
            return

        kernel = getattr(agent, "_kernel_session", None)
        if kernel is None:
            return

        usage = kernel.flush_utility_usage()
        if usage:
            registry.apply_usage(usage)
    except Exception as e:
        logger.warning("Utility usage flush failed: %s", e)


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    file_refs: list[str] = []
    conversation_id: str | None = None


@router.get("/health")
async def health(agent=Depends(get_agent_optional)):
    return {"status": "ok", "agent_loaded": agent is not None}


@router.post("/chat")
async def chat(
    request: ChatRequest,
    store: ConversationStore = Depends(get_store),
    workspace_dir: str = Depends(get_workspace_dir),
    cancel_events: dict = Depends(get_cancel_events),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """SSE stream of agent events.

    Each conversation uses an independent kernel and lock, so multiple
    users can chat concurrently without sharing REPL state.

    Event types sent to the frontend:
        conversation_id  — conversation UUID (first event)
        token            — one LLM token/chunk as it arrives
        message_end      — full message complete (may contain <execute>)
        observation      — code execution output
        solution         — final cleaned answer (persisted to history)
        done             — stream complete
        error            — exception message
    """
    conv_id = request.conversation_id
    if not conv_id:
        meta = store.create_conversation()
        conv_id = meta["id"]

    # Get the per-session agent + lock.
    session = session_mgr.get_session(conv_id)
    session_agent = session.agent

    async def event_stream():
        async with session.lock:
            raw_session_log: list[dict] = []

            try:
                yield f"data: {json.dumps({'type': 'conversation_id', 'content': conv_id})}\n\n"

                conv = store.get_conversation(conv_id)
                history = []
                if conv and conv.get("messages"):
                    for m in conv["messages"]:
                        if m.get("role") in ("user", "assistant"):
                            history.append({"role": m["role"], "content": m["content"]})

                agent_prompt = build_prompt(request.message, request.file_refs, workspace_dir)
                last_full_message = ""

                cancel_ev = asyncio.Event()
                cancel_events[conv_id] = cancel_ev

                full_trace_parts: list[str] = []

                try:
                    async for step in async_iter_agent(session_agent, agent_prompt, history, cancel_ev):
                        ev_type = step.get("type")
                        ev_content = step.get("content", "")

                        if ev_type == "token":
                            yield f"data: {json.dumps({'type': 'token', 'content': ev_content}, ensure_ascii=False)}\n\n"
                        elif ev_type == "message_end":
                            last_full_message = ev_content
                            full_trace_parts.append(ev_content)
                            raw_session_log.append({"type": "message_end", "content": ev_content})
                            yield f"data: {json.dumps({'type': 'message_end', 'content': ev_content}, ensure_ascii=False)}\n\n"
                        elif ev_type == "observation":
                            full_trace_parts.append(ev_content)
                            raw_session_log.append({"type": "observation", "content": ev_content})
                            yield f"data: {json.dumps({'type': 'observation', 'content': ev_content}, ensure_ascii=False)}\n\n"
                finally:
                    cancel_events.pop(conv_id, None)

                full_trace = "\n".join(full_trace_parts).strip() or last_full_message
                stored_answer = full_trace
                solution_for_ui = clean_stored_answer(last_full_message) or last_full_message
                yield f"data: {json.dumps({'type': 'solution', 'content': solution_for_ui}, ensure_ascii=False)}\n\n"

                display_message = request.message
                if request.file_refs:
                    display_message += f"\n\n📎 引用: {', '.join(request.file_refs)}"

                stored_messages = conv.get("messages", []) if conv else []
                stored_messages.append(
                    {
                        "role": "user",
                        "content": display_message,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                stored_messages.append(
                    {
                        "role": "assistant",
                        "content": stored_answer,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                store.save_messages(conv_id, stored_messages)

                has_executions = any(s.get("type") == "observation" for s in raw_session_log)
                if has_executions:
                    yield f"data: {json.dumps({'type': 'maintenance_pending'})}\n\n"
                    # Cache session log on the session for utilities router.
                    session.last_session_log = {
                        "log": raw_session_log,
                        "user_message": request.message,
                    }

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

                # Fire-and-forget: flush utility usage from this session's kernel.
                asyncio.ensure_future(_flush_usage_only(session))

            except Exception as e:
                logger.exception("Chat stream error")
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/cancel")
async def cancel_chat(
    conversation_id: str | None = None,
    cancel_events: dict = Depends(get_cancel_events),
):
    """Signal a running chat stream to stop."""
    if not conversation_id:
        return {"status": "no_conversation_id"}
    ev = cancel_events.get(conversation_id)
    if ev:
        ev.set()
        return {"status": "cancelled", "conversation_id": conversation_id}
    return {"status": "no_active_stream", "conversation_id": conversation_id}
