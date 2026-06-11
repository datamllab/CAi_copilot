"""Tests for MemoryManager — curator LLM extraction."""

import json

import pytest

from CAi.CAi_agent.memory._manager import MemoryManager
from CAi.CAi_agent.memory._store import MemoryStore


class FakeCuratorLLM:
    """Minimal LLM stub for MemoryManager tests."""

    def __init__(self, response: str):
        self._response = response
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)

        class _Resp:
            content = self._response

        return _Resp()

    def bind(self, **kwargs):
        return self


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "_memory", max_memories=10)


@pytest.fixture
def session_log():
    return [
        {"type": "message_end", "content": "Let me analyze the EGFR docking results."},
        {"type": "observation", "content": "<observation>Best score: -9.2 kcal/mol for compound X</observation>"},
        {"type": "message_end", "content": "The best docking score is -9.2 kcal/mol. <done/>"},
    ]


class TestMemoryManagerExtract:
    def test_no_llm_returns_empty(self, store, session_log):
        manager = MemoryManager(store, llm=None)
        result = manager.extract(session_log)
        assert result == {"saved": [], "deleted": [], "rejected": []}

    def test_empty_session_returns_empty(self, store):
        manager = MemoryManager(store, llm=FakeCuratorLLM("[]"))
        result = manager.extract([])
        assert result == {"saved": [], "deleted": [], "rejected": []}

    def test_save_action(self, store, session_log):
        response = json.dumps([
            {
                "type": "save",
                "category": "domain_fact",
                "content": "Best EGFR docking score is -9.2 kcal/mol",
                "tags": ["egfr", "docking"],
                "importance": 8,
                "reasoning": "Key result for future reference",
            }
        ])
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        result = manager.extract(session_log, user_message="Dock EGFR compounds")
        assert len(result["saved"]) == 1
        assert len(store) == 1
        entry = store.list_all()[0]
        assert "EGFR" in entry.content
        assert entry.importance == 8

    def test_delete_action(self, store, session_log):
        # Pre-populate a memory
        entry = store.save("Old fact", tags=["old"])

        response = json.dumps([
            {
                "type": "delete",
                "id": entry.id,
                "reasoning": "No longer relevant",
            }
        ])
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        result = manager.extract(session_log)
        assert len(result["deleted"]) == 1
        assert len(store) == 0

    def test_invalid_json_returns_empty(self, store, session_log):
        manager = MemoryManager(store, llm=FakeCuratorLLM("not valid json at all"))
        result = manager.extract(session_log)
        assert result == {"saved": [], "deleted": [], "rejected": []}

    def test_fenced_json(self, store, session_log):
        response = '```json\n[{"type": "save", "category": "preference", "content": "Likes tables", "tags": ["format"], "importance": 6}]\n```'
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        result = manager.extract(session_log)
        assert len(result["saved"]) == 1

    def test_empty_content_rejected(self, store, session_log):
        response = json.dumps([
            {"type": "save", "category": "preference", "content": "", "tags": []}
        ])
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        result = manager.extract(session_log)
        assert len(result["rejected"]) == 1

    def test_importance_clamped(self, store, session_log):
        response = json.dumps([
            {"type": "save", "content": "Fact", "importance": 99, "tags": []}
        ])
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        manager.extract(session_log)
        entry = store.list_all()[0]
        assert entry.importance == 10  # clamped from 99

    def test_trace_saved(self, store, session_log):
        response = json.dumps([
            {"type": "save", "content": "Traced fact", "tags": [], "importance": 5}
        ])
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        manager.extract(session_log)
        traces = manager.list_traces()
        assert len(traces) == 1
        assert traces[0]["status"] == "ok"

    def test_trace_get(self, store, session_log):
        response = "[]"
        manager = MemoryManager(store, llm=FakeCuratorLLM(response))
        manager.extract(session_log)
        traces = manager.list_traces()
        assert len(traces) == 1
        full = manager.get_trace(traces[0]["file"])
        assert full is not None
        assert full["status"] == "ok"

    def test_exception_returns_empty(self, store, session_log):
        class BadLLM:
            def invoke(self, prompt):
                raise RuntimeError("LLM down")

            def bind(self, **kwargs):
                return self

        manager = MemoryManager(store, llm=BadLLM())
        result = manager.extract(session_log)
        assert result == {"saved": [], "deleted": [], "rejected": []}
