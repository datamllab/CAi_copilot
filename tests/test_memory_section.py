"""Tests for MemorySection — PromptSection rendering."""

import pytest

from CAi.CAi_agent.memory._section import MemorySection
from CAi.CAi_agent.memory._store import MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "_memory", max_memories=10)


class TestMemorySectionRender:
    def test_empty_store_renders_empty(self, store):
        section = MemorySection(store)
        assert section.render() == ""

    def test_renders_memories(self, store):
        store.save("User prefers Chinese", category="preference", tags=["language"])
        store.save("Target: EGFR", category="project_context", tags=["egfr"])

        section = MemorySection(store)
        section.set_context("EGFR drug design")
        output = section.render()
        assert "MEMORY" in output
        assert "User Preferences" in output or "Project Context" in output

    def test_set_context_updates_query(self, store):
        store.save("Docking results", tags=["docking"])
        store.save("Toxicity data", tags=["toxicity"])

        section = MemorySection(store)

        section.set_context("docking score")
        output1 = section.render()

        section.set_context("toxicity prediction")
        output2 = section.render()

        # Both should render (no context filter on render, just ranking)
        assert "MEMORY" in output1
        assert "MEMORY" in output2

    def test_category_grouping(self, store):
        store.save("Pref 1", category="preference")
        store.save("Context 1", category="project_context")
        store.save("Fact 1", category="domain_fact")

        section = MemorySection(store)
        output = section.render()
        assert "[User Preferences]" in output
        assert "[Project Context]" in output
        assert "[Domain Facts]" in output

    def test_tags_shown_in_output(self, store):
        store.save("Important fact", tags=["smiles", "filtering"])

        section = MemorySection(store)
        output = section.render()
        assert "smiles" in output
        assert "filtering" in output
