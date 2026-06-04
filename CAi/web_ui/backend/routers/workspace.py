"""Workspace management endpoints."""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends

from ..deps import SessionManager, get_session_manager, get_workspace_dir

router = APIRouter(prefix="/api", tags=["workspace"])


@router.delete("/workspace")
async def clear_workspace(workspace_dir: str = Depends(get_workspace_dir)):
    """Delete all workspace files, preserving the _conversations directory."""
    if os.path.exists(workspace_dir):
        for item in os.listdir(workspace_dir):
            if item == "_conversations":
                continue
            p = os.path.join(workspace_dir, item)
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
    os.makedirs(workspace_dir, exist_ok=True)
    return {"status": "cleared"}


@router.post("/reset")
async def reset_all(session_mgr: SessionManager = Depends(get_session_manager)):
    """Shut down all session kernels and clear workspace."""
    session_mgr.shutdown_all()
    workspace_dir = get_workspace_dir()
    if os.path.exists(workspace_dir):
        for item in os.listdir(workspace_dir):
            if item == "_conversations":
                continue
            p = os.path.join(workspace_dir, item)
            if os.path.isfile(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
    os.makedirs(workspace_dir, exist_ok=True)
    return {"status": "reset"}
