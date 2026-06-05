"""
Shared application state and FastAPI dependency providers.

All mutable singletons live here so routers can import them via Depends()
instead of referencing module-level globals scattered across app.py.

Multi-user support:
    Each conversation gets an independent Jupyter kernel (via ``KernelSession``)
    and its own ``asyncio.Lock``. The ``SessionManager`` lazily creates and
    caches these per-conversation sessions. Shared resources (LLM client,
    tool registry, prompt, utilities registry) are reused across sessions.
"""

from __future__ import annotations

import asyncio
import os

from CAi.config import WORKSPACE_DIR
from CAi.logger import get_logger

from .conversation_store import ConversationStore

logger = get_logger("CAi.web_ui.deps")

# ---------------------------------------------------------------------------
# Global (shared) resources
# ---------------------------------------------------------------------------

_agent = None  # The prototype A1pro agent — cloned per session.

_workspace_dir: str = str((WORKSPACE_DIR / "agent_workspace").resolve())
_conversations_dir: str = str(
    (WORKSPACE_DIR / "agent_workspace" / "_conversations").resolve()
)
os.makedirs(_workspace_dir, exist_ok=True)

_store = ConversationStore(_conversations_dir)

# Per-conversation cancellation signals (shared — cancel is always per-conv).
_cancel_events: dict[str, asyncio.Event] = {}

# ---------------------------------------------------------------------------
# SessionManager — per-conversation kernel + lock
# ---------------------------------------------------------------------------


class AgentSession:
    """Bundles everything one conversation needs for isolated execution."""

    __slots__ = ("conv_id", "agent", "lock", "last_session_log")

    def __init__(self, conv_id: str, agent) -> None:
        self.conv_id = conv_id
        self.agent = agent                  # cloned A1pro with its own kernel
        self.lock = asyncio.Lock()          # serialises chat for this conv only
        self.last_session_log: dict = {"log": [], "user_message": ""}


class SessionManager:
    """Lazily creates and caches ``AgentSession`` instances per conversation.

    Shared resources (LLM, tool registry, prompt, utilities) are reused.
    Each session gets its own Jupyter kernel subprocess and asyncio lock.
    """

    def __init__(self, prototype_agent, workspace_dir: str) -> None:
        self._prototype = prototype_agent
        self._workspace_dir = workspace_dir
        self._sessions: dict[str, AgentSession] = {}

    def get_session(self, conv_id: str) -> AgentSession:
        """Return (or create) the session for a conversation."""
        session = self._sessions.get(conv_id)
        if session is None:
            session = self._create_session(conv_id)
        return session

    def _create_session(self, conv_id: str) -> AgentSession:
        from CAi.CAi_agent.execution.repl import KernelSession

        kernel = KernelSession(workspace_dir=self._workspace_dir)
        cloned_agent = self._prototype.clone_for_session(kernel)
        session = AgentSession(conv_id, cloned_agent)
        self._sessions[conv_id] = session
        logger.debug("Created session for conv %s", conv_id)
        return session

    def evict(self, conv_id: str) -> None:
        """Shut down a session's kernel and remove it from the cache."""
        session = self._sessions.pop(conv_id, None)
        if session is not None:
            kernel = getattr(session.agent, "_kernel_session", None)
            if kernel is not None:
                kernel.shutdown()
            logger.debug("Evicted session for conv %s", conv_id)

    def shutdown_all(self) -> None:
        """Shut down all session kernels."""
        for conv_id in list(self._sessions):
            self.evict(conv_id)

    @property
    def active_count(self) -> int:
        return len(self._sessions)


# Single instance — created when set_agent() is called.
_session_manager: SessionManager | None = None


# ---------------------------------------------------------------------------
# Initialisation (called by launch.py via app.set_agent)
# ---------------------------------------------------------------------------


def set_agent(agent) -> None:
    """Register the prototype agent and initialise the session manager."""
    global _agent, _session_manager
    _agent = agent
    _session_manager = SessionManager(agent, _workspace_dir)

    # Also configure the prototype's default kernel workspace (for CLI compat).
    from CAi.CAi_agent.execution.repl import set_workspace_dir as _set_repl_workspace
    _set_repl_workspace(_workspace_dir)

    logger.debug("Agent registered; workspace=%s", _workspace_dir)


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_agent():
    """Return the prototype agent; raise 503 if not yet initialised."""
    from fastapi import HTTPException

    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return _agent


def get_agent_optional():
    """Return the agent or None — never raises (used by /health)."""
    return _agent


def get_store() -> ConversationStore:
    return _store


def get_workspace_dir() -> str:
    return _workspace_dir


def get_session_manager() -> SessionManager:
    if _session_manager is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return _session_manager


def get_cancel_events() -> dict[str, asyncio.Event]:
    return _cancel_events
