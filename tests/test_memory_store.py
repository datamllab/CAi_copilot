"""Tests for MemoryStore — CRUD, search, observer, dedup, eviction."""

from pathlib import Path

import pytest

from CAi.CAi_agent.memory._store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """Fresh MemoryStore in a temp directory."""
    return MemoryStore(tmp_path / "_memory", max_memories=10)


class TestMemoryStorePersistence:
    def test_save_and_reload(self, tmp_path):
        d = tmp_path / "_memory"
        s1 = MemoryStore(d, max_memories=10)
        s1.save("User prefers dark mode", category="preference", tags=["ui"])
        s1.save("Target: EGFR kinase", category="project_context", tags=["egfr"])
        assert len(s1) == 2

        # Reload from disk
        s2 = MemoryStore(d, max_memories=10)
        assert len(s2) == 2
        entries = s2.list_all()
        contents = {e.content for e in entries}
        assert "User prefers dark mode" in contents
        assert "Target: EGFR kinase" in contents

    def test_delete_persists(self, store):
        entry = store.save("To be deleted", tags=["temp"])
        assert entry is not None
        assert store.delete(entry.id) is True
        assert len(store) == 0

        # Reload
        s2 = MemoryStore(store._dir, max_memories=10)
        assert len(s2) == 0


class TestMemoryStoreCRUD:
    def test_save_returns_entry(self, store):
        entry = store.save("Test fact", category="domain_fact", tags=["test"], importance=7)
        assert entry is not None
        assert entry.content == "Test fact"
        assert entry.importance == 7
        assert entry.source == "auto"

    def test_get(self, store):
        entry = store.save("Findable fact")
        found = store.get(entry.id)
        assert found is not None
        assert found.content == "Findable fact"
        assert store.get("nonexistent") is None

    def test_update(self, store):
        entry = store.save("Original content")
        updated = store.update(entry.id, content="Updated content", importance=9)
        assert updated is not None
        assert updated.content == "Updated content"
        assert updated.importance == 9
        assert store.update("nonexistent", content="x") is None

    def test_delete_returns_bool(self, store):
        entry = store.save("Deletable")
        assert store.delete(entry.id) is True
        assert store.delete(entry.id) is False  # already deleted
        assert store.delete("nonexistent") is False

    def test_list_all_with_category_filter(self, store):
        store.save("Pref 1", category="preference")
        store.save("Pref 2", category="preference")
        store.save("Fact 1", category="domain_fact")
        assert len(store.list_all()) == 3
        assert len(store.list_all(category="preference")) == 2
        assert len(store.list_all(category="domain_fact")) == 1
        assert len(store.list_all(category="project_context")) == 0


class TestMemoryStoreDedup:
    def test_duplicate_merges(self, store):
        e1 = store.save("User prefers Chinese language responses", category="preference", tags=["lang"])
        # Very similar content (Jaccard > 0.8) → should merge
        e2 = store.save("User prefers Chinese language responses always", category="preference", tags=["response"])
        assert e2 is None  # merged, not new
        assert len(store) == 1
        # Tags should be merged
        entry = list(store.entries.values())[0]
        assert "lang" in entry.tags
        assert "response" in entry.tags

    def test_different_category_no_merge(self, store):
        store.save("EGFR target", category="project_context")
        store.save("EGFR target", category="domain_fact")
        assert len(store) == 2  # different categories → both kept


class TestMemoryStoreSearch:
    def test_keyword_search(self, store):
        store.save("EGFR kinase inhibitor screening", tags=["egfr", "screening"])
        store.save("User prefers tabular output", category="preference", tags=["output"])
        store.save("Best docking score: -9.2 kcal/mol", tags=["docking", "score"])

        results = store.search("EGFR inhibitor")
        assert len(results) >= 1
        assert results[0].content == "EGFR kinase inhibitor screening"

    def test_tag_filter(self, store):
        store.save("Docking result A", tags=["docking"])
        store.save("Toxicity result B", tags=["toxicity"])

        results = store.search(tags=["docking"])
        assert all("docking" in [t.lower() for t in e.tags] for e in results)

    def test_category_filter(self, store):
        store.save("Pref 1", category="preference")
        store.save("Fact 1", category="domain_fact")

        results = store.search(category="preference")
        assert all(e.category == "preference" for e in results)

    def test_empty_query_returns_top_by_importance(self, store):
        store.save("Low importance", importance=2)
        store.save("High importance", importance=9)

        results = store.search(limit=10)
        assert len(results) == 2
        assert results[0].importance >= results[1].importance

    def test_search_updates_access_count(self, store):
        entry = store.save("Searchable fact", tags=["search"])
        initial_count = entry.access_count
        store.search("searchable")
        updated = store.get(entry.id)
        assert updated.access_count > initial_count


class TestMemoryStoreEviction:
    def test_evicts_when_full(self, tmp_path):
        store = MemoryStore(tmp_path / "_memory", max_memories=3)
        store.save("Fact 1", importance=3)
        store.save("Fact 2", importance=5)
        store.save("Fact 3", importance=7)
        assert len(store) == 3

        # Adding a 4th should evict the lowest importance
        store.save("Fact 4", importance=9)
        assert len(store) == 3
        contents = {e.content for e in store.list_all()}
        assert "Fact 4" in contents
        assert "Fact 1" not in contents  # evicted (lowest importance)


class TestMemoryStoreObserver:
    def test_on_change_fires(self, store):
        calls = []
        store.on_change(lambda: calls.append(1))
        store.save("Trigger change")
        assert len(calls) >= 1

    def test_on_change_delete(self, store):
        calls = []
        entry = store.save("Will delete")
        store.on_change(lambda: calls.append(1))
        store.delete(entry.id)
        assert len(calls) == 1

    def test_unsubscribe(self, store):
        calls = []
        unsub = store.on_change(lambda: calls.append(1))
        store.save("First")
        assert len(calls) == 1
        unsub()
        store.save("Second")
        assert len(calls) == 1  # no more notifications

    def test_listener_exception_isolated(self, store):
        calls = []
        store.on_change(lambda: (_ for _ in ()).throw(ValueError("boom")))
        store.on_change(lambda: calls.append(1))
        store.save("Test")
        assert len(calls) == 1  # second listener still ran


class TestMemoryStoreProperties:
    def test_len(self, store):
        assert len(store) == 0
        store.save("A")
        assert len(store) == 1

    def test_bool(self, store):
        assert not store
        store.save("A")
        assert store

    def test_entries_returns_copy(self, store):
        store.save("A")
        entries = store.entries
        entries.clear()
        assert len(store) == 1  # original not affected
