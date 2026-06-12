"""Plan block preservation for context compression.

Messages containing ``<execute lang="plan">`` are special-cased: the
**latest** plan message is always preserved through compression (prepended
to the result), while older plan messages participate in normal compression
and may be dropped. This ensures the agent never loses track of its
current task plan.
"""

from __future__ import annotations

import functools
import re

#: Detect <execute lang="plan"> blocks for plan preservation.
_PLAN_RE = re.compile(r'<execute\s+lang="plan"', re.IGNORECASE)


def _has_plan_block(content: str) -> bool:
    """Return True if the message content contains a plan execute block."""
    return bool(_PLAN_RE.search(content))


def _preserve_plan(compress_fn):
    """Decorator: extract the latest ``<execute lang="plan">`` message before
    compression, then prepend it to the compressed result.

    This guarantees the current task plan survives context compression
    regardless of how aggressively older messages are pruned.
    """
    @functools.wraps(compress_fn)
    def wrapper(history: list[dict], **kw) -> list[dict]:
        # Find all messages containing plan blocks.
        plan_indices = [
            i for i, m in enumerate(history)
            if _has_plan_block(m.get("content", ""))
        ]
        if not plan_indices:
            return compress_fn(history, **kw)

        # Keep only the latest plan message; older ones participate in compression.
        latest_idx = plan_indices[-1]
        latest_plan = history[latest_idx]

        # Remove ALL plan messages from the history fed to compression.
        filtered = [m for i, m in enumerate(history) if i not in plan_indices]
        compressed = compress_fn(filtered, **kw)

        # Prepend the latest plan so it's always the first message seen.
        return [latest_plan, *compressed]

    return wrapper
