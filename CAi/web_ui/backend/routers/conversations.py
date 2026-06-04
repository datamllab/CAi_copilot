"""Conversation CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..conversation_store import ConversationStore
from ..deps import SessionManager, get_session_manager, get_store

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str | None = None


class UpdateTitleRequest(BaseModel):
    title: str


@router.get("")
async def list_conversations(store: ConversationStore = Depends(get_store)):
    return {"conversations": store.list_conversations()}


@router.post("")
async def create_conversation(
    request: CreateConversationRequest,
    store: ConversationStore = Depends(get_store),
):
    return store.create_conversation(title=request.title)


@router.get("/{conv_id}")
async def get_conversation(
    conv_id: str,
    store: ConversationStore = Depends(get_store),
):
    conv = store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: str,
    store: ConversationStore = Depends(get_store),
    session_mgr: SessionManager = Depends(get_session_manager),
):
    if not store.delete_conversation(conv_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Shut down the session's kernel to free resources.
    session_mgr.evict(conv_id)
    return {"deleted": conv_id}


@router.patch("/{conv_id}/title")
async def update_title(
    conv_id: str,
    request: UpdateTitleRequest,
    store: ConversationStore = Depends(get_store),
):
    if not store.update_title(conv_id, request.title):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok"}
