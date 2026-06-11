"""MemoryStore — disk ↔ memory bridge for cross-session memories.

Thread-safe (RLock), observable (on_change callbacks), with keyword-based
search and automatic capacity management.

Storage layout:
    agent_workspace/_memory/
    ├── memories.json     # all entries as a JSON array
    └── _traces/          # MemoryManager LLM call traces
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from threading import RLock

from ._entry import MemoryEntry

logger = logging.getLogger("CAi.memory.store")

# ---------------------------------------------------------------------------
# Stopwords for keyword tokenization
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "nor", "not", "so", "yet", "both", "either", "neither", "each",
    "every", "all", "any", "few", "more", "most", "other", "some",
    "such", "no", "only", "own", "same", "than", "too", "very",
    "just", "because", "if", "when", "where", "how", "what", "which",
    "who", "whom", "this", "that", "these", "those", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her", "it",
    "its", "they", "them", "their", "about", "up", "out",
})


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase word tokens, filtering stopwords."""
    words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


class MemoryStore:
    """Manages memories on disk and in memory.

    Thread-safe via RLock. Enforces a configurable maximum entry count
    by evicting the lowest-importance, least-recently-accessed entries
    when the limit is reached.
    """

    def __init__(self, memory_dir: Path, max_memories: int = 100):
        self._dir = Path(memory_dir)
        self._max = max_memories
        self._entries: dict[str, MemoryEntry] = {}
        self._listeners: list[Callable[[], None]] = []
        self._lock = RLock()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------
    # Internal loading / persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load all memories from memories.json."""
        path = self._dir / "memories.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for d in data:
                entry = MemoryEntry.from_dict(d)
                self._entries[entry.id] = entry
            # Enforce max on load: evict lowest-importance entries
            if len(self._entries) > self._max:
                self._evict_excess()
        except Exception as e:
            logger.warning("Failed to load memories: %s", e)

    def _persist(self) -> None:
        """Write all entries to memories.json. Caller must hold _lock."""
        path = self._dir / "memories.json"
        data = [e.to_dict() for e in self._entries.values()]
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to persist memories: %s", e)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def save(
        self,
        content: str,
        *,
        category: str = "domain_fact",
        tags: list[str] | None = None,
        source: str = "auto",
        importance: int = 5,
    ) -> MemoryEntry | None:
        """Add a new memory. Returns the entry, or None if it was a duplicate.

        Duplicate detection: if a same-category memory has Jaccard
        similarity > 0.8 on content tokens, the new memory is merged
        into the existing one (tags union, importance max) instead.
        """
        content_tokens = _tokenize(content)

        with self._lock:
            # Dedup check
            for entry in self._entries.values():
                if entry.category != category:
                    continue
                entry_tokens = _tokenize(entry.content)
                if _jaccard_similarity(content_tokens, entry_tokens) > 0.8:
                    # Merge: union tags, max importance, append if meaningfully different
                    merged_tags = list(set(entry.tags) | set(tags or []))
                    merged_importance = max(entry.importance, importance)
                    updated = entry.replace(
                        tags=merged_tags,
                        importance=merged_importance,
                        updated_at=datetime.now(),
                    )
                    self._entries[entry.id] = updated
                    self._persist()
                    logger.debug("Merged duplicate memory: %s", entry.id)
                    self._notify()
                    return None

            # Capacity check
            if len(self._entries) >= self._max:
                self._evict_one()

            entry = MemoryEntry(
                category=category,
                content=content,
                tags=list(tags or []),
                source=source,
                importance=importance,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            self._entries[entry.id] = entry
            self._persist()

        self._notify()
        logger.debug("Saved memory: %s (%s)", entry.id, category)
        return entry

    def update(self, entry_id: str, **kwargs) -> MemoryEntry | None:
        """Update fields of an existing memory. Returns updated entry or None."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            kwargs["updated_at"] = datetime.now()
            updated = entry.replace(**kwargs)
            self._entries[entry_id] = updated
            self._persist()

        self._notify()
        return updated

    def delete(self, entry_id: str) -> bool:
        """Delete a memory. Returns True if it existed."""
        with self._lock:
            entry = self._entries.pop(entry_id, None)
            if entry is None:
                return False
            self._persist()

        self._notify()
        logger.debug("Deleted memory: %s", entry_id)
        return True

    def get(self, entry_id: str) -> MemoryEntry | None:
        """Get a single memory by ID."""
        with self._lock:
            return self._entries.get(entry_id)

    def list_all(self, *, category: str | None = None) -> list[MemoryEntry]:
        """Return all memories, optionally filtered by category."""
        with self._lock:
            entries = list(self._entries.values())
        if category:
            entries = [e for e in entries if e.category == category]
        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        *,
        tags: list[str] | None = None,
        category: str | None = None,
        limit: int = 15,
    ) -> list[MemoryEntry]:
        """Keyword-based search with importance × recency ranking.

        Scoring:
            tag_match * 3 + content_keyword_match + importance * 0.1

        Accessed memories get their access_count and last_accessed updated.
        """
        if not query and not tags and not category:
            # No filter: return top-N by importance
            return self.list_all()[:limit]

        query_tokens = _tokenize(query) if query else set()
        tag_set = {t.lower() for t in (tags or [])}
        now = datetime.now()

        scored: list[tuple[float, MemoryEntry]] = []
        with self._lock:
            for entry in self._entries.values():
                if category and entry.category != category:
                    continue

                score = 0.0
                has_match = False

                # Tag matching (weighted heavily)
                if tag_set:
                    entry_tags = {t.lower() for t in entry.tags}
                    tag_overlap = len(tag_set & entry_tags)
                    if tag_overlap:
                        score += tag_overlap * 3.0
                        has_match = True

                # Content keyword matching
                if query_tokens:
                    content_tokens = _tokenize(entry.content)
                    keyword_overlap = len(query_tokens & content_tokens)
                    if keyword_overlap:
                        score += keyword_overlap * 1.0
                        has_match = True
                    # Also check tags in query
                    entry_tags_lower = {t.lower() for t in entry.tags}
                    tag_in_query = len(query_tokens & entry_tags_lower)
                    if tag_in_query:
                        score += tag_in_query * 2.0
                        has_match = True

                # Importance bonus (small, as tiebreaker)
                score += entry.importance * 0.1

                # Recency bonus
                if entry.last_accessed:
                    days_ago = (now - entry.last_accessed).total_seconds() / 86400
                    score += max(0, 1.0 - days_ago / 30)  # max 1.0 for today

                # Include if: has a real match, or no filter was applied
                if has_match or (not query_tokens and not tag_set):
                    scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [entry for _, entry in scored[:limit]]

        # Update access stats for returned results
        with self._lock:
            for entry in results:
                updated = entry.replace(
                    access_count=entry.access_count + 1,
                    last_accessed=datetime.now(),
                )
                self._entries[entry.id] = updated
            if results:
                self._persist()

        return results

    # ------------------------------------------------------------------
    # Eviction
    # ------------------------------------------------------------------

    def _evict_excess(self) -> None:
        """Evict entries until len <= max. Caller must hold _lock."""
        while len(self._entries) > self._max:
            self._evict_one_locked()

    def _evict_one(self) -> None:
        """Evict the lowest-priority entry. Caller must hold _lock."""
        self._evict_one_locked()

    def _evict_one_locked(self) -> None:
        """Pick the entry with lowest eviction score and remove it."""
        if not self._entries:
            return
        # Eviction score: importance (high = safe) + access_count + recency
        now = datetime.now()

        def _eviction_score(entry: MemoryEntry) -> float:
            score = entry.importance * 2.0
            score += min(entry.access_count, 10)  # cap access contribution
            if entry.last_accessed:
                days_ago = (now - entry.last_accessed).total_seconds() / 86400
                score += max(0, 5.0 - days_ago / 7)  # recently accessed = safer
            return score

        victim_id = min(self._entries, key=lambda eid: _eviction_score(self._entries[eid]))
        del self._entries[victim_id]
        logger.debug("Evicted memory: %s", victim_id)

    # ------------------------------------------------------------------
    # Observer protocol
    # ------------------------------------------------------------------

    def on_change(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe a callback invoked after any mutating operation.

        Returns an unsubscribe function. Listener exceptions are logged
        but do not prevent other listeners from running.
        """
        self._listeners.append(callback)

        def _unsubscribe() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                logger.exception("Memory store listener raised — continuing")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def entries(self) -> dict[str, MemoryEntry]:
        """Return a copy of the current entries dict."""
        with self._lock:
            return dict(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __bool__(self) -> bool:
        return len(self) > 0
