"""
Chat business logic: prompt building, response cleaning, async agent iteration.

Kept separate from routing so the logic can be tested without FastAPI.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

from CAi.CAi_agent.agent_tags import (
    EXECUTE_RE,
    OBSERVATION_RE,
    iter_execute_blocks,
    strip_all_tags,
)


def build_prompt(text: str, ref_files: list[str], workspace_dir: str) -> str:
    """Construct the full prompt string sent to the agent."""
    prompt = text
    prompt += f"\n\n[工作目录]: {workspace_dir}"
    for f in ref_files:
        target = os.path.join(workspace_dir, os.path.basename(f))
        prompt += f"\n[引用文件]: {target}"
    return prompt


def clean_stored_answer(full_content: str) -> str:
    """Strip internal execution tags so stored conversation reads as plain text."""
    return strip_all_tags(full_content)


def extract_parts(content: str) -> dict:
    """Split a complete AI message into thinking / code / observation / text.

    Used when re-hydrating a conversation from storage and by pdf_export.
    """
    parts: dict = {}

    has_execute = bool(EXECUTE_RE.search(content))
    has_observation = bool(OBSERVATION_RE.search(content))

    if has_execute or has_observation:
        # Earliest tag start: the prose before it is the agent's "thinking".
        tag_positions = [
            m.start() for m in EXECUTE_RE.finditer(content)
        ] + [m.start() for m in OBSERVATION_RE.finditer(content)]
        if tag_positions:
            thinking = content[: min(tag_positions)].strip()
            if thinking:
                parts["thinking"] = thinking

    code_blocks = [b.code for b in iter_execute_blocks(content)]
    if code_blocks:
        parts["code"] = "\n\n".join(code_blocks)

    obs_blocks = [m.group("body").strip() for m in OBSERVATION_RE.finditer(content)]
    if obs_blocks:
        parts["observation"] = "\n\n".join(obs_blocks)

    if "code" not in parts and "observation" not in parts:
        cleaned = strip_all_tags(content)
        if cleaned:
            parts["text"] = cleaned

    return parts


async def async_iter_agent(
    agent,
    prompt: str,
    history: list[dict],
    cancel_event: asyncio.Event | None = None,
) -> AsyncGenerator:
    """Adapt the synchronous streaming generator into an async generator.

    Each call to next(gen) may block on LLM I/O or code execution; we run
    it in a thread pool so the event loop stays free to flush SSE frames.

    StopIteration cannot cross an asyncio Future boundary — if we let next()
    raise inside run_in_executor, asyncio raises a cryptic TypeError and the
    stream hangs.  We catch StopIteration on the worker side and return a
    sentinel value instead.

    If cancel_event is set between chunks the iteration stops; the current
    in-flight step finishes silently in the background (threads can't be
    forcibly killed, but the result is simply discarded).
    """
    _DONE = object()
    gen = agent.run_with_history_streaming(prompt, history)
    loop = asyncio.get_event_loop()

    def _next_or_sentinel():
        try:
            return next(gen)
        except StopIteration:
            return _DONE

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                break
            step = await loop.run_in_executor(None, _next_or_sentinel)
            if step is _DONE:
                break
            yield step
    finally:
        # gen may still be executing in the thread pool if we were cancelled.
        # Python raises ValueError if close() is called while next(gen) is
        # in-flight on another thread. We swallow it — the thread will finish
        # and the result is simply discarded.
        try:
            gen.close()
        except ValueError:
            pass
