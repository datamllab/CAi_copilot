"""MemoryEntry — immutable dataclass describing a single memory fact."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


def _parse_dt(value, default=None) -> datetime | None:
    """Parse a datetime value that may be a string, datetime, or None."""
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return default


@dataclass(frozen=True)
class MemoryEntry:
    """One piece of cross-session memory.

    Categories:
        - preference: user preferences, habits, workflow choices
        - project_context: current goals, molecule targets, constraints
        - domain_fact: tool results, screening conclusions, parameters
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    category: str = "domain_fact"
    content: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "auto"
    importance: int = 5
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    last_accessed: datetime | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "id": self.id,
            "category": self.category,
            "content": self.content,
            "tags": list(self.tags),
            "source": self.source,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MemoryEntry:
        """Deserialize from a dict (inverse of to_dict)."""
        return cls(
            id=d.get("id", uuid.uuid4().hex[:12]),
            category=d.get("category", "domain_fact"),
            content=d.get("content", ""),
            tags=d.get("tags", []),
            source=d.get("source", "auto"),
            importance=d.get("importance", 5),
            created_at=_parse_dt(d.get("created_at"), datetime.now()),
            updated_at=_parse_dt(d.get("updated_at"), datetime.now()),
            access_count=d.get("access_count", 0),
            last_accessed=_parse_dt(d.get("last_accessed")),
        )

    def replace(self, **kwargs) -> MemoryEntry:
        """Return a new MemoryEntry with the given fields replaced."""
        d = self.to_dict()
        d.update(kwargs)
        return MemoryEntry.from_dict(d)
