"""Tests for the Web UI backend — SSE parsing and chat lock existence."""

from __future__ import annotations

import builtins

import pytest


@pytest.fixture(autouse=True)
def _reset_custom_functions():
    yield
    if hasattr(builtins, "_base_CAi_custom_functions"):
        builtins._base_CAi_custom_functions.clear()


# ---------------------------------------------------------------------------
# _extract_parts — SSE payload builder
# ---------------------------------------------------------------------------


def test_extract_parts_plain_text():
    from CAi.web_ui.backend.chat_service import extract_parts

    parts = extract_parts("Hello world")
    assert parts == {"text": "Hello world"}


def test_extract_parts_with_thinking_and_code():
    from CAi.web_ui.backend.chat_service import extract_parts

    content = "Let me think about this.\n<execute>print(1)</execute>"
    parts = extract_parts(content)
    assert "thinking" in parts
    assert "Let me think about this" in parts["thinking"]
    assert parts["code"] == "print(1)"


def test_extract_parts_observation():
    from CAi.web_ui.backend.chat_service import extract_parts

    content = "<observation>\nresult = 42\n</observation>"
    parts = extract_parts(content)
    assert "observation" in parts
    assert "42" in parts["observation"]


def test_extract_parts_strips_done_tag_from_text():
    from CAi.web_ui.backend.chat_service import extract_parts

    parts = extract_parts("Final answer is X. <done/>")
    assert parts.get("text") == "Final answer is X."
    assert "<done/>" not in parts.get("text", "")


def test_extract_parts_multiple_execute_blocks():
    from CAi.web_ui.backend.chat_service import extract_parts

    content = "<execute>a=1</execute>\n<execute>b=2</execute>"
    parts = extract_parts(content)
    assert "a=1" in parts["code"]
    assert "b=2" in parts["code"]


# ---------------------------------------------------------------------------
# Chat lock exists and is an asyncio.Lock
# ---------------------------------------------------------------------------


def test_chat_lock_is_asyncio_lock():
    """Verify per-session chat locks are properly configured.

    Each ``AgentSession`` has its own ``asyncio.Lock`` so multiple
    conversations can stream independently. The real serialisation
    is validated by the fact that the agent's ``_exec_lock``
    (threading.Lock) prevents REPL interleaving, and the per-session
    ``asyncio.Lock`` prevents multiple SSE streams from overlapping.
    """
    import asyncio

    from CAi.web_ui.backend.deps import AgentSession

    # AgentSession creates its own lock.
    session = AgentSession(conv_id="test-conv", agent=None)
    assert isinstance(session.lock, asyncio.Lock)


def test_async_iter_agent_helper_exists():
    """Verify the async wrapper for the sync generator is importable."""
    from CAi.web_ui.backend.chat_service import async_iter_agent

    assert callable(async_iter_agent)
