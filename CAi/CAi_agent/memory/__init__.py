"""Memory subsystem — cross-session persistent memory for the agent.

Components:
    _entry    — MemoryEntry: immutable dataclass for one memory fact.
    _store    — MemoryStore: disk ↔ memory bridge with CRUD and search.
    _section  — MemorySection: PromptSection for agent prompt.
    _manager  — MemoryManager: independent curator for auto-extraction.
"""

from ._entry import MemoryEntry


def __getattr__(name: str):
    """Lazy imports for modules that may not exist yet during incremental development."""
    if name == "MemoryStore":
        from ._store import MemoryStore
        return MemoryStore
    if name == "MemorySection":
        from ._section import MemorySection
        return MemorySection
    if name == "MemoryManager":
        from ._manager import MemoryManager
        return MemoryManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MemoryEntry",
    "MemoryStore",
    "MemorySection",
    "MemoryManager",
]
