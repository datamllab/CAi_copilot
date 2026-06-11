"""MemorySection — PromptSection that renders relevant memories into the agent prompt."""

from __future__ import annotations

from ..prompt.section import PromptSection
from ._store import MemoryStore

_HEADER = """\
MEMORY — Relevant context from previous sessions
=================================================
The following facts were remembered from prior interactions. Use them as
context for the current task, but do NOT treat them as absolute truth —
the user's current request always takes precedence over stale memories.
"""

_CATEGORY_LABELS = {
    "preference": "User Preferences",
    "project_context": "Project Context",
    "domain_fact": "Domain Facts",
}


class MemorySection(PromptSection):
    """Render relevant memories into the agent system prompt.

    The section queries the MemoryStore using the current user message
    as context. If no memories match, the section renders as empty and
    is silently dropped by PromptBuilder.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._context_query: str = ""

    def set_context(self, query: str) -> None:
        """Update the search context (called once per user message)."""
        self._context_query = query

    def render(self) -> str:
        memories = self._store.search(self._context_query, limit=15)
        if not memories:
            return ""

        lines = [_HEADER]

        # Group by category for readability
        by_category: dict[str, list] = {}
        for m in memories:
            by_category.setdefault(m.category, []).append(m)

        for cat in ("preference", "project_context", "domain_fact"):
            entries = by_category.get(cat)
            if not entries:
                continue
            label = _CATEGORY_LABELS.get(cat, cat)
            lines.append(f"\n  [{label}]")
            for entry in entries:
                tags_str = ", ".join(entry.tags[:5]) if entry.tags else ""
                tag_hint = f"  [{tags_str}]" if tags_str else ""
                lines.append(f"  • {entry.content}{tag_hint}")

        return "\n".join(lines).rstrip()
