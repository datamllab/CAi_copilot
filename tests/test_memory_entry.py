"""Tests for MemoryEntry dataclass."""

from datetime import datetime

from CAi.CAi_agent.memory._entry import MemoryEntry


class TestMemoryEntrySerialization:
    def test_roundtrip(self):
        entry = MemoryEntry(
            id="abc123",
            category="preference",
            content="User prefers Chinese responses",
            tags=["language", "chinese"],
            source="user",
            importance=8,
            created_at=datetime(2026, 1, 1, 12, 0, 0),
            updated_at=datetime(2026, 1, 2, 12, 0, 0),
            access_count=3,
            last_accessed=datetime(2026, 1, 3, 12, 0, 0),
        )
        d = entry.to_dict()
        restored = MemoryEntry.from_dict(d)
        assert restored.id == entry.id
        assert restored.category == entry.category
        assert restored.content == entry.content
        assert restored.tags == entry.tags
        assert restored.source == entry.source
        assert restored.importance == entry.importance
        assert restored.access_count == entry.access_count
        assert restored.last_accessed == entry.last_accessed

    def test_defaults(self):
        entry = MemoryEntry(content="test fact")
        assert entry.category == "domain_fact"
        assert entry.importance == 5
        assert entry.tags == []
        assert entry.access_count == 0
        assert entry.last_accessed is None
        assert len(entry.id) == 12

    def test_replace(self):
        entry = MemoryEntry(content="original", importance=5)
        updated = entry.replace(content="modified", importance=9)
        assert updated.content == "modified"
        assert updated.importance == 9
        # Original unchanged (frozen)
        assert entry.content == "original"
        assert entry.importance == 5

    def test_from_dict_missing_fields(self):
        d = {"content": "minimal"}
        entry = MemoryEntry.from_dict(d)
        assert entry.content == "minimal"
        assert entry.category == "domain_fact"
        assert entry.importance == 5
        assert entry.tags == []
