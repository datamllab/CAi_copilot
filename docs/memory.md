# Memory Subsystem

`CAi/CAi_agent/memory/`

Cross-session persistent memory for the CAi agent. The agent accumulates
user preferences, project context, and domain facts across conversations,
enabling it to "remember" prior work without re-reading conversation logs.

---

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│  A1pro (orchestrator)                                       │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ MemoryStore  │───▶│MemorySection │───▶│ PromptBuilder│  │
│  │ (JSON disk)  │    │ (render)     │    │ (system msg) │  │
│  └──────┬───────┘    └──────────────┘    └──────────────┘  │
│         │                                                   │
│         │ on_change                                         │
│         ▼                                                   │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │MemoryManager │◀────────│ curator_llm  │                 │
│  │ (extraction) │         │ (cheap LLM)  │                 │
│  └──────────────┘         └──────────────┘                 │
└─────────────────────────────────────────────────────────────┘
         ▲                          │
         │ session_log              │ save/delete
         │                          ▼
  ┌──────┴───────┐          ┌──────────────┐
  │ Chat flow    │          │ memories.json│
  │ (SSE stream) │          │ (disk)       │
  └──────────────┘          └──────────────┘
```

The memory subsystem has four components:

| Component | File | Role |
|-----------|------|------|
| `MemoryEntry` | `_entry.py` | Immutable dataclass — one memory fact |
| `MemoryStore` | `_store.py` | Disk ↔ memory bridge — CRUD, search, dedup, eviction |
| `MemorySection` | `_section.py` | PromptSection — renders relevant memories into prompt |
| `MemoryManager` | `_manager.py` | Curator LLM — auto-extracts memories from session logs |

---

## Storage layout

```
agent_workspace/_memory/
├── memories.json          # all entries as a JSON array
└── _traces/               # MemoryManager LLM call traces
    ├── 2026-06-12T10-30-00_extract.json
    └── ...
```

A typical `memories.json`:

```json
[
  {
    "id": "a1b2c3d4e5f6",
    "category": "preference",
    "content": "User prefers Chinese language responses",
    "tags": ["language", "chinese"],
    "source": "auto",
    "importance": 7,
    "created_at": "2026-06-10T14:30:00",
    "updated_at": "2026-06-10T14:30:00",
    "access_count": 5,
    "last_accessed": "2026-06-12T09:15:00"
  },
  {
    "id": "f7e8d9c0b1a2",
    "category": "project_context",
    "content": "Target: EGFR kinase, lead optimization phase",
    "tags": ["egfr", "lead-optimization"],
    "source": "auto",
    "importance": 9,
    "created_at": "2026-06-11T10:00:00",
    "updated_at": "2026-06-11T10:00:00",
    "access_count": 3,
    "last_accessed": "2026-06-12T09:15:00"
  }
]
```

---

## MemoryEntry

`CAi/CAi_agent/memory/_entry.py`

Frozen (immutable) dataclass representing a single piece of memory.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | `uuid4().hex[:12]` | 12-char unique identifier |
| `category` | `str` | `"domain_fact"` | One of: `preference`, `project_context`, `domain_fact` |
| `content` | `str` | `""` | Self-contained natural language fact |
| `tags` | `list[str]` | `[]` | Keywords for retrieval |
| `source` | `str` | `"auto"` | Origin: `"auto"`, `"user"`, or `"session:<id>"` |
| `importance` | `int` | `5` | 1–10 scale; affects retrieval ranking and eviction |
| `created_at` | `datetime` | `now()` | Creation timestamp |
| `updated_at` | `datetime` | `now()` | Last modification timestamp |
| `access_count` | `int` | `0` | How many times this memory was retrieved by search |
| `last_accessed` | `datetime \| None` | `None` | When it was last retrieved |

### Categories

| Category | What it captures | Typical importance |
|----------|-----------------|-------------------|
| `preference` | User habits, workflow choices, language | 6–8 |
| `project_context` | Current goals, targets, constraints, stages | 7–10 |
| `domain_fact` | Tool results, thresholds, molecular properties | 3–7 |

### Key methods

```python
entry.to_dict()              # → JSON-safe dict
MemoryEntry.from_dict(d)     # → MemoryEntry (handles str and datetime)
entry.replace(**kwargs)      # → new MemoryEntry with fields replaced
```

The `replace()` method goes through `to_dict()` → update → `from_dict()`,
so it handles both raw `datetime` objects and ISO strings in `kwargs`.

---

## MemoryStore

`CAi/CAi_agent/memory/_store.py`

Thread-safe (RLock) disk ↔ memory bridge with CRUD, keyword search,
deduplication, and capacity management.

### Initialization

```python
from CAi.CAi_agent.memory import MemoryStore

store = MemoryStore(
    memory_dir=Path("agent_workspace/_memory"),
    max_memories=100,         # eviction kicks in above this
)
```

On construction the store loads `memories.json` from disk and enforces
the capacity limit (evicting lowest-priority entries if the file was
edited externally to exceed the max).

### CRUD operations

```python
# Create — returns the new entry, or None if merged with a duplicate
entry = store.save(
    "User prefers tabular output format",
    category="preference",
    tags=["output", "format"],
    source="user",            # "auto" for LLM-extracted, "user" for manual
    importance=7,
)

# Read
entry = store.get(entry_id)           # single entry by ID
all_entries = store.list_all()        # sorted by importance desc
prefs = store.list_all(category="preference")

# Update — returns updated entry, or None if ID not found
updated = store.update(entry_id, content="New text", importance=9)

# Delete — returns True if existed
store.delete(entry_id)
```

Every mutating operation (`save`, `update`, `delete`) persists to disk
immediately and fires `on_change` callbacks.

### Deduplication

Before saving, the store checks all existing memories in the **same
category** for content similarity. If Jaccard similarity on tokenized
content exceeds **0.8**, the new memory is **merged** instead of created:

- Tags: union of old and new
- Importance: max of old and new
- Content: kept as-is (the existing entry's content)
- `updated_at`: refreshed

```python
store.save("User prefers Chinese language responses", ...)  # created
store.save("User prefers Chinese language responses always", ...)  # merged → returns None
```

This prevents the memory library from growing stale duplicates when the
MemoryManager extracts the same fact from multiple sessions.

### Search

Keyword-based retrieval with importance × recency ranking:

```python
results = store.search(
    query="EGFR docking",      # natural language query
    tags=["screening"],         # optional tag filter
    category="domain_fact",     # optional category filter
    limit=15,                   # max results
)
```

#### Scoring algorithm

Each entry receives a score from three signals:

```
score = tag_match × 3.0
      + content_keyword_match × 1.0
      + tag_in_query × 2.0
      + importance × 0.1          (tiebreaker)
      + recency_bonus              (0–1.0, based on last_accessed)
```

Where:
- **tag_match**: number of query tags that overlap with entry tags
- **content_keyword_match**: number of query tokens found in entry content
- **tag_in_query**: number of entry tags found as query tokens
- **importance bonus**: `importance × 0.1` (max 1.0 for importance=10)
- **recency bonus**: `max(0, 1.0 - days_since_access / 30)`

Only entries with at least one real match (tag or keyword) are included.
When no filter is provided (`query=""`, no tags), all entries are returned
sorted by importance.

#### Tokenization

```python
def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())
    return {w for w in words if w not in _STOPWORDS}
```

- Splits on whitespace and punctuation
- Supports English, digits, and Chinese characters
- Filters ~90 common English stopwords
- No stemming or lemmatization (keeps it simple)

#### Access tracking

Search results automatically have their `access_count` incremented and
`last_accessed` refreshed. This feeds back into both retrieval ranking
(recently-accessed memories are boosted) and eviction priority (frequently
accessed memories are harder to evict).

### Eviction

When the store exceeds `max_memories`, the lowest-scoring entry is
removed. The eviction score combines three signals:

```python
eviction_score = importance × 2.0
               + min(access_count, 10)
               + max(0, 5.0 - days_since_access / 7)
```

Higher score = safer from eviction. A memory with importance=9 that was
accessed yesterday scores ~23. A memory with importance=2 that was never
accessed scores ~4.

Eviction happens in two scenarios:
1. **On save**: when adding a new entry would exceed the cap
2. **On load**: if `memories.json` was edited externally to exceed the cap

### Observer protocol

```python
def on_change(callback) -> Callable:
    """Subscribe to mutations. Returns unsubscribe function."""

store.on_change(lambda: print("Memory changed!"))
```

Listener exceptions are logged but do not prevent other listeners from
running (fail-isolated, same as ToolRegistry and UtilityRegistry).

A1pro subscribes `self._rebuild_prompt` so the system prompt stays
current when memories change.

---

## MemorySection

`CAi/CAi_agent/memory/_section.py`

`PromptSection` subclass that renders relevant memories into the agent's
system prompt.

### Position in prompt

```
CoreSection        ← persona + interaction rules
MemorySection      ← ★ relevant memories (this section)
UtilitiesSection   ← high-level helper functions
ToolsSection       ← low-level toolkit
SkillsSection      ← workflow SOPs
```

### Rendering

When the agent receives a user message, `A1pro.update_memory_context()`
calls `MemorySection.set_context(user_message)` to update the search
query. The next `render()` call searches the store and formats the
results:

```
MEMORY — Relevant context from previous sessions
=================================================
The following facts were remembered from prior interactions. Use them as
context for the current task, but do NOT treat them as absolute truth —
the user's current request always takes precedence over stale memories.

  [User Preferences]
  • User prefers Chinese language responses  [language, chinese]
  • Output results in tabular format  [output, format]

  [Project Context]
  • Target: EGFR kinase, lead optimization phase  [egfr, lead-optimization]

  [Domain Facts]
  • Best docking score for compound X: -9.2 kcal/mol  [docking, egfr]
```

If no memories match the search, `render()` returns `""` and
PromptBuilder silently drops the section.

### Context lifecycle

```
User sends "帮我筛选 EGFR 的高分对接结果"
    │
    ├── chat router calls agent.update_memory_context(message)
    │   └── MemorySection.set_context("帮我筛选 EGFR 的高分对接结果")
    │       └── MemorySection.render() searches for "egfr", "docking", "screening"
    │           └── Returns relevant memories → injected into system prompt
    │
    └── agent.run_with_history_streaming(prompt, history)
        └── LLM sees memories in system prompt → uses them as context
```

---

## MemoryManager

`CAi/CAi_agent/memory/_manager.py`

Independent curator (not a BaseAgent subclass) that uses the curator LLM
to analyze session logs and decide what to remember. Same architectural
pattern as `UtilityManager`.

### Extraction flow

```
Session ends (SSE stream done, had code executions)
    │
    └── fire-and-forget: _extract_memories(session)
        │
        ├── MemoryManager.extract(session_log, user_message)
        │   │
        │   ├── _summarize_session(log)
        │   │   └── Strip <execute>/<observation> tags, keep reasoning + results
        │   │
        │   ├── _build_extract_prompt(summary, user_message)
        │   │   └── Include: current library + user message + conversation summary
        │   │
        │   ├── _invoke_curator(prompt)
        │   │   └── LLM returns JSON array of actions
        │   │
        │   ├── _parse_actions(response)
        │   │   └── 3-strategy fallback: direct → fenced → greedy regex
        │   │
        │   └── _apply_actions(actions)
        │       └── Dispatch save/delete to MemoryStore
        │
        └── _save_trace(trace)
            └── Persist to _traces/ directory
```

### Curator prompt design

The extraction prompt instructs the LLM to identify three types of
information:

1. **preference** — explicit user statements ("I prefer...", "Don't...")
2. **project_context** — current state (targets, stages, constraints)
3. **domain_fact** — key results (scores, thresholds, parameters)

Skip rules prevent noise:
- Trivially derivable from workspace files
- Already captured in existing memory (the prompt includes the full library)
- One-off calculations with no future relevance

### Response parsing

The LLM returns a JSON array of actions. Three fallback strategies
handle different formatting styles:

```
Strategy 1: json.loads(response)                    # clean JSON
Strategy 2: regex ```json [...] ```                 # markdown fenced
Strategy 3: regex \[.*\] (greedy)                   # last resort
```

### Action validation

Before dispatching to the store:
- `content` must be non-empty (else rejected)
- `category` must be one of the three valid values (else defaults to `domain_fact`)
- `importance` is clamped to `[1, 10]`

### Trace persistence

Every `extract()` call writes a JSON trace to `_traces/`:

```json
{
  "timestamp": "2026-06-12T10:30:00",
  "mode": "extract",
  "status": "ok",
  "user_message": "帮我筛选 EGFR 的高分对接结果",
  "conversation_length": 5,
  "prompt": "...",
  "library_before": [...],
  "raw_response": "...",
  "parsed_actions": [...],
  "applied_result": {"saved": ["a1b2c3"], "deleted": [], "rejected": []},
  "library_after": [...]
}
```

Traces auto-prune to the 50 most recent files.

### Curator LLM

Reuses `A1pro.curator_llm` (the same lazy-built LLM used by
UtilityManager). Typically a cheaper/faster model than the main agent:

```bash
# CAi/.env
CURATOR_MODEL=deepseek-v4-flash
CURATOR_TEMPERATURE=0.2
```

---

## Integration with A1pro

`CAi/CAi_agent/agent.py`

### Initialization

```python
class A1pro(BaseAgent):
    def __init__(
        self,
        *,
        auto_load_memory: bool = True,
        memory_dir: str | None = None,
        max_memories: int = 100,
        ...
    ):
        # Memory subsystem
        self.memory_store = None
        self._memory_section = None
        if auto_load_memory:
            from CAi.CAi_agent.memory import MemoryStore
            mem_dir = Path(memory_dir) if memory_dir else Path("agent_workspace/_memory")
            self.memory_store = MemoryStore(mem_dir, max_memories=max_memories)

        # ... (other subsystems) ...

        # Prompt: MemorySection goes after CoreSection, before Utilities
        builder = PromptBuilder().add(CoreSection())
        if self.memory_store:
            from CAi.CAi_agent.memory import MemorySection
            self._memory_section = MemorySection(self.memory_store)
            builder.add(self._memory_section)
        # ... rest of sections ...

        # Auto-rebuild prompt when memories change
        if self.memory_store:
            self.memory_store.on_change(self._rebuild_prompt)
```

### Context update

```python
def update_memory_context(self, user_message: str) -> None:
    """Called once per user message."""
    if self._memory_section is not None:
        self._memory_section.set_context(user_message)
        self._rebuild_prompt()
```

### Session cloning

`clone_for_session()` uses `copy.copy()`, which shares `memory_store`
and `_memory_section` references across session clones. This is correct
— memory is global and shared across all conversations.

---

## Chat flow integration

`CAi/web_ui/backend/routers/chat.py`

### On user message

```python
# Update memory context BEFORE agent runs
if hasattr(session_agent, "update_memory_context"):
    session_agent.update_memory_context(request.message)
```

This ensures the MemorySection searches for memories relevant to the
current topic before the LLM sees the prompt.

### On session end

```python
# Fire-and-forget: extract memories from this session
if has_executions:
    asyncio.ensure_future(_extract_memories(session))
```

Memory extraction only runs when the session had code executions
(`has_executions = True`). Pure Q&A conversations don't trigger
extraction — they rarely produce savable facts.

### Background task

```python
async def _extract_memories(session: AgentSession) -> None:
    agent = session.agent
    store = getattr(agent, "memory_store", None)
    if store is None:
        return
    # ...
    manager = MemoryManager(store, llm=agent.curator_llm)
    await loop.run_in_executor(None, manager.extract, session_log, user_message)
```

Runs in a thread pool executor to avoid blocking the event loop.

---

## Web API

`CAi/web_ui/backend/routers/memory.py`

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memory/` | List all memories (optional `?category=preference`) |
| `GET` | `/api/memory/search` | Search by query (`?q=EGFR&limit=10`) |
| `GET` | `/api/memory/{id}` | Get one memory detail |
| `POST` | `/api/memory/` | Manually add a memory |
| `PATCH` | `/api/memory/{id}` | Edit a memory's fields |
| `DELETE` | `/api/memory/{id}` | Delete a memory |
| `POST` | `/api/memory/extract` | Trigger extraction from session log |
| `GET` | `/api/memory/traces` | List recent MemoryManager traces |
| `GET` | `/api/memory/traces/{filename}` | One trace (full prompt + response) |

### Manual memory creation

```bash
curl -X POST http://localhost:7000/api/memory/ \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Always show molecular weight in results",
    "category": "preference",
    "tags": ["output", "molecular-weight"],
    "importance": 7
  }'
```

### Search

```bash
curl "http://localhost:7000/api/memory/search?q=EGFR+docking&limit=5"
```

---

## Configuration

`CAi/config.py`

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `true` | Enable/disable the memory subsystem |
| `MEMORY_DIR` | `agent_workspace/_memory` | Storage directory |
| `MEMORY_MAX_ENTRIES` | `100` | Max memories before eviction |

Set in `CAi/.env`:

```bash
MEMORY_ENABLED=true
MEMORY_MAX_ENTRIES=200
```

---

## Design decisions

### Why keyword search, not vector embeddings?

1. **Zero new dependencies** — no sentence-transformers, no FAISS, no
   OpenAI embeddings API. The project already depends on langchain +
   FastAPI; adding a vector stack would increase complexity significantly.
2. **Latency** — keyword search is O(n) over a small set (≤100 entries),
   essentially free. Vector search would need an embedding API call per
   query.
3. **Sufficient for the use case** — memories are short, self-contained
   facts with explicit tags. The curator LLM is instructed to include
   good tags, making keyword matching effective.
4. **Upgrade path** — if semantic search becomes necessary later, the
   `MemoryStore.search()` method can be swapped to a hybrid approach
   (keyword + vector) without changing the public API.

### Why Jaccard dedup, not cosine similarity?

Jaccard on token sets is O(n) where n = token count, requires no
embedding model, and works well for short texts (1–2 sentences). For
the typical memory content length (~15 words), Jaccard > 0.8 catches
near-duplicates while allowing paraphrases.

### Why fire-and-forget extraction?

Memory extraction involves an LLM call that can take 5–15 seconds.
Running it as a background task avoids delaying the SSE `done` event
to the frontend. If extraction fails, it's logged but doesn't affect
the user experience.

### Why share MemoryStore across sessions?

Memory is global context — all conversations benefit from the same pool
of facts. When `clone_for_session()` creates a shallow copy of A1pro,
the `memory_store` and `_memory_section` references are shared (via
`copy.copy()`). Writes from any session's MemoryManager are visible to
all sessions immediately.

---

## Testing

Four test files cover the subsystem:

| File | Tests | What it exercises |
|------|-------|-------------------|
| `test_memory_entry.py` | 4 | Serialization roundtrip, defaults, replace, partial dict |
| `test_memory_store.py` | 22 | CRUD, persistence, dedup, search, eviction, observer |
| `test_memory_section.py` | 5 | Empty render, category grouping, tags, context update |
| `test_memory_manager.py` | 11 | Extract, delete, fenced JSON, clamping, traces, errors |

All use `FakeLLM` / `FakeCuratorLLM` — no network, no API keys.

Run:

```bash
pytest tests/test_memory_entry.py tests/test_memory_store.py \
       tests/test_memory_section.py tests/test_memory_manager.py -v
```

### Key invariants

- MemoryStore dedup merges entries with Jaccard > 0.8 (tags union, importance max)
- Eviction removes lowest `importance × 2 + access_count + recency` score
- Observer callbacks are fail-isolated
- `MemoryManager.extract()` never raises — all errors caught and logged
- `MemorySection.render()` returns empty string when no memories match
- `search()` updates `access_count` and `last_accessed` for returned entries
