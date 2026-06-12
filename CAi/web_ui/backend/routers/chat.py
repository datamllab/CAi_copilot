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
from CAi.config import AUTO_MAINTAIN

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


async def _extract_memories(session: AgentSession) -> None:
    """Run memory extraction as a fire-and-forget background task.

    Uses the MemoryManager curator to analyze the session log and
    save relevant facts for future sessions.
    """
    try:
        agent = session.agent
        store = getattr(agent, "memory_store", None)
        if store is None:
            return

        log = session.last_session_log
        session_log = log.get("log", [])
        user_message = log.get("user_message", "")
        if not session_log:
            return

        from CAi.CAi_agent.memory import MemoryManager

        llm = getattr(agent, "curator_llm", None)
        manager = MemoryManager(store, llm=llm)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, manager.extract, session_log, user_message)
    except Exception as e:
        logger.warning("Memory extraction failed: %s", e)


async def _auto_maintain(session: AgentSession) -> None:
    """Run utility maintenance automatically without UI prompt."""
    try:
        agent = session.agent
        registry = getattr(agent, "utility_registry", None)
        if registry is None:
            return

        log = session.last_session_log
        session_log = log.get("log", [])
        user_message = log.get("user_message", "")
        if not session_log:
            return

        from CAi.CAi_agent.utilities import UtilityManager

        manager = UtilityManager(registry, llm=agent.curator_llm)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, manager.maintain, session_log, user_message
        )
        if any(result.get(k) for k in ("saved", "updated", "deleted")):
            logger.info("Auto-maintain: %s", result)
    except Exception as e:
        logger.warning("Auto-maintain failed: %s", e)


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


async def _chat_event_stream(
    session,
    conv_id: str,
    prompt: str,
    file_refs: list[str],
    history: list[dict],
    workspace_dir: str,
    cancel_events: dict,
    store: ConversationStore,
):
    """Shared SSE stream logic used by both /chat and /chat/regenerate."""
    session_agent = session.agent
    raw_session_log: list[dict] = []

    try:
        yield f"data: {json.dumps({'type': 'conversation_id', 'content': conv_id})}\n\n"

        agent_prompt = build_prompt(prompt, file_refs, workspace_dir)

        if hasattr(session_agent, "update_memory_context"):
            session_agent.update_memory_context(prompt)

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

        display_message = prompt
        if file_refs:
            display_message += f"\n\n📎 引用: {', '.join(file_refs)}"

        stored_messages = store.get_conversation(conv_id).get("messages", [])
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
        session.last_session_log = {
            "log": raw_session_log,
            "user_message": prompt,
        }

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        asyncio.ensure_future(_flush_usage_only(session))
        if has_executions:
            asyncio.ensure_future(_extract_memories(session))
            if AUTO_MAINTAIN:
                asyncio.ensure_future(_auto_maintain(session))

    except Exception as e:
        logger.exception("Chat stream error")
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"


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
    """
    conv_id = request.conversation_id
    if not conv_id:
        meta = store.create_conversation()
        conv_id = meta["id"]

    session = session_mgr.get_session(conv_id)
    conv = store.get_conversation(conv_id)
    history = []
    if conv and conv.get("messages"):
        for m in conv["messages"]:
            if m.get("role") in ("user", "assistant"):
                history.append({"role": m["role"], "content": m["content"]})

    async def event_stream():
        async with session.lock:
            async for chunk in _chat_event_stream(
                session, conv_id, request.message, request.file_refs,
                history, workspace_dir, cancel_events, store,
            ):
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class RegenerateRequest(BaseModel):
    conversation_id: str


def _parse_user_message(content: str) -> tuple[str, list[str]]:
    """Restore raw prompt and file_refs from a stored user message.

    Stored format:  prompt + '\n\n📎 引用: file1, file2'
    """
    marker = "\n\n📎 引用: "
    idx = content.rfind(marker)
    if idx == -1:
        return content, []
    return content[:idx], content[idx + len(marker):].split(", ")


@router.post("/chat/regenerate")
async def regenerate(
    request: RegenerateRequest,
    store: ConversationStore = Depends(get_store),
    workspace_dir: str = Depends(get_workspace_dir),
    cancel_events: dict = Depends(get_cancel_events),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """Regenerate the last assistant message.

    Deletes the last assistant turn (and anything after it), then re-runs
    the agent with the same user prompt and truncated history.
    """
    conv_id = request.conversation_id
    conv = store.get_conversation(conv_id)
    if not conv:
        return StreamingResponse(
            _error_stream("Conversation not found"), media_type="text/event-stream"
        )

    messages = conv.get("messages", [])
    if not messages:
        return StreamingResponse(
            _error_stream("No messages in conversation"), media_type="text/event-stream"
        )

    # Find last assistant index
    last_assistant_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_assistant_idx = i
            break

    if last_assistant_idx is None:
        return StreamingResponse(
            _error_stream("No assistant message to regenerate"), media_type="text/event-stream"
        )

    # Truncate: keep only messages before the last assistant
    truncated = messages[:last_assistant_idx]
    store.save_messages(conv_id, truncated)

    # Find the user message that triggered the deleted assistant turn
    user_msg = None
    for i in range(len(truncated) - 1, -1, -1):
        if truncated[i].get("role") == "user":
            user_msg = truncated[i]
            break

    if user_msg is None:
        return StreamingResponse(
            _error_stream("No user message found before assistant"), media_type="text/event-stream"
        )

    prompt, file_refs = _parse_user_message(user_msg.get("content", ""))

    # Build history (excluding the last user message — it's the new prompt)
    history = []
    for m in truncated[:-1]:
        if m.get("role") in ("user", "assistant"):
            history.append({"role": m["role"], "content": m["content"]})

    session = session_mgr.get_session(conv_id)

    async def event_stream():
        async with session.lock:
            async for chunk in _chat_event_stream(
                session, conv_id, prompt, file_refs,
                history, workspace_dir, cancel_events, store,
            ):
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _error_stream(msg: str):
    yield f"data: {json.dumps({'type': 'error', 'content': msg})}\n\n"


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
