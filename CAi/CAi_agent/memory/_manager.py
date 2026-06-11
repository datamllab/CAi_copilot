"""MemoryManager — independent curator for cross-session memory extraction.

Reviews session logs and uses an LLM to decide what information is worth
remembering. Does not inherit BaseAgent — makes a single LLM call per
extraction cycle, reusing the curator LLM.

Every extract() call writes a JSON trace to `agent_workspace/_memory/_traces/`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from ._store import MemoryStore

logger = logging.getLogger("CAi.memory.manager")


# ---------------------------------------------------------------------------
# Curator prompt template
# ---------------------------------------------------------------------------

EXTRACT_PROMPT_TEMPLATE = """\
You are a Memory Curator for a Drug Discovery AI Agent. Your job is to \
review a recent conversation and decide what information is worth remembering \
for future sessions.

## Current Memory Library

{library}

## User's Message in This Session

{user_message}

## Conversation Summary

{conversation}

## Instructions

Identify information worth remembering across sessions. Focus on:

1. **preference** — User preferences and habits:
   - "I prefer...", "Don't use...", "Always...", "I like..."
   - Workflow choices (output formats, visualization preferences)
   - Language preferences (Chinese vs English responses)

2. **project_context** — Current project state:
   - Target molecules, protein pockets, screening campaigns
   - Current stage (generation → evaluation → optimization)
   - Constraints (budget, timeline, specific requirements)

3. **domain_fact** — Important discoveries and parameters:
   - Tool results that inform future decisions (best docking scores, toxicity thresholds)
   - Successful parameter configurations
   - Key molecular properties discovered

**Skip if:**
- The information is trivially derivable from the current workspace files
- The information is already captured in an existing memory (check the library above)
- The information is a one-off calculation with no future relevance

## Response Format

Return a JSON array of actions:
```json
[
  {{
    "type": "save",
    "category": "preference" | "project_context" | "domain_fact",
    "content": "The fact to remember (concise, self-contained)",
    "tags": ["keyword1", "keyword2"],
    "importance": 7,
    "reasoning": "Why this is worth remembering"
  }},
  {{
    "type": "delete",
    "id": "existing_memory_id",
    "reasoning": "Why this memory is no longer relevant"
  }}
]
```

Rules:
- importance: 1-10 scale. Preferences ~7, critical project context ~9, minor facts ~4.
- tags: 2-5 relevant keywords for retrieval (lowercase).
- content must be self-contained — understandable without the original conversation.
- Keep it concise: one sentence per memory, max 2 sentences.
- If no memories are worth saving, return an empty array: []

Return ONLY the JSON array, no other text.
"""


class MemoryManager:
    """Independent curator that reviews session logs and maintains the memory library.

    Accepts a pre-configured LLM instance (reuses the agent's curator LLM).
    All failures are caught and logged without affecting the main agent.
    """

    def __init__(self, store: MemoryStore, llm=None):
        self._store = store
        self._llm = llm
        self._trace_dir = store._dir / "_traces"
        self._trace_dir.mkdir(parents=True, exist_ok=True)

    def _invoke_curator(self, prompt: str) -> str:
        """Call the LLM, defensively isolating from stop sequences."""
        llm = self._llm
        try:
            llm = self._llm.bind(stop=None)
        except Exception:
            llm = self._llm
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    def extract(
        self,
        session_log: list[dict],
        user_message: str | None = None,
    ) -> dict[str, list[str]]:
        """Analyze session and extract memories.

        Returns:
            {"saved": [...], "deleted": [...], "rejected": [...]}
        """
        trace = _new_trace("extract")
        trace["user_message"] = user_message
        try:
            if self._llm is None:
                trace["status"] = "skipped"
                trace["reason"] = "no LLM configured"
                return {"saved": [], "deleted": [], "rejected": []}

            conversation_summary = self._summarize_session(session_log)
            trace["conversation_length"] = len(conversation_summary)

            if not conversation_summary.strip():
                trace["status"] = "skipped"
                trace["reason"] = "empty conversation"
                return {"saved": [], "deleted": [], "rejected": []}

            prompt = self._build_extract_prompt(conversation_summary, user_message)
            trace["prompt"] = prompt
            trace["library_before"] = [e.to_dict() for e in self._store.list_all()]

            content = self._invoke_curator(prompt)
            trace["raw_response"] = content

            actions = self._parse_actions(content)
            trace["parsed_actions"] = actions

            result = self._apply_actions(actions)
            trace["applied_result"] = result
            trace["library_after"] = [e.to_dict() for e in self._store.list_all()]
            trace["status"] = "ok"
            return result
        except Exception as e:
            trace["status"] = "error"
            trace["error"] = str(e)
            logger.error("MemoryManager extraction failed: %s", e)
            return {"saved": [], "deleted": [], "rejected": []}
        finally:
            self._save_trace(trace)

    def _summarize_session(self, session_log: list[dict]) -> str:
        """Extract a readable summary from the session log."""
        parts: list[str] = []
        for step in session_log:
            stype = step.get("type", "")
            content = step.get("content", "")
            if stype == "message_end":
                # Strip execution tags, keep reasoning + conclusions
                cleaned = re.sub(
                    r"<execute[^>]*>.*?</execute>",
                    "[code executed]",
                    content,
                    flags=re.DOTALL,
                )
                cleaned = re.sub(
                    r"<observation>.*?</observation>",
                    "",
                    cleaned,
                    flags=re.DOTALL,
                )
                cleaned = cleaned.replace("<done/>", "").strip()
                if cleaned:
                    parts.append(f"Agent: {cleaned[:800]}")
            elif stype == "observation":
                # Keep short summary of observations
                obs = content.replace("<observation>", "").replace("</observation>", "").strip()
                if obs:
                    parts.append(f"Observation: {obs[:300]}")
        return "\n\n".join(parts[:20])  # Cap at 20 entries

    def _build_extract_prompt(
        self,
        conversation_summary: str,
        user_message: str | None = None,
    ) -> str:
        """Build the curator prompt."""
        current_lib = [e.to_dict() for e in self._store.list_all()]
        lib_section = json.dumps(
            [
                {
                    "id": e["id"],
                    "category": e["category"],
                    "content": e["content"],
                    "tags": e["tags"],
                    "importance": e["importance"],
                }
                for e in current_lib
            ],
            indent=2,
            ensure_ascii=False,
        ) if current_lib else "[]"

        user_section = (
            user_message.strip() if user_message and user_message.strip()
            else "(not provided)"
        )

        return EXTRACT_PROMPT_TEMPLATE.format(
            library=lib_section,
            user_message=user_section,
            conversation=conversation_summary,
        )

    def _parse_actions(self, response: str) -> list[dict]:
        """Parse LLM response into action dicts (3-strategy fallback)."""
        if not response or not response.strip():
            return []

        text = response.strip()

        # Strategy 1: direct JSON
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: markdown fence
        fence_match = re.search(
            r"```(?:json)?\s*(\[.*?\])\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            try:
                data = json.loads(fence_match.group(1))
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, ValueError):
                pass

        # Strategy 3: greedy outermost array
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, ValueError):
                pass

        logger.warning("Failed to parse MemoryManager response as JSON array")
        return []

    def _apply_actions(self, actions: list[dict]) -> dict[str, list[str]]:
        """Dispatch save/delete actions to the store."""
        result: dict[str, list[str]] = {
            "saved": [],
            "deleted": [],
            "rejected": [],
        }
        for action in actions:
            try:
                atype = action.get("type")
                if atype == "save":
                    content = action.get("content", "").strip()
                    if not content:
                        result["rejected"].append("save:empty_content")
                        continue
                    category = action.get("category", "domain_fact")
                    if category not in ("preference", "project_context", "domain_fact"):
                        category = "domain_fact"
                    tags = action.get("tags", [])
                    importance = action.get("importance", 5)
                    if not isinstance(importance, int):
                        importance = 5
                    importance = max(1, min(10, importance))
                    entry = self._store.save(
                        content,
                        category=category,
                        tags=tags,
                        source="auto",
                        importance=importance,
                    )
                    if entry:
                        result["saved"].append(entry.id)
                    else:
                        result["saved"].append("merged_duplicate")
                elif atype == "delete":
                    entry_id = action.get("id", "")
                    if entry_id and self._store.delete(entry_id):
                        result["deleted"].append(entry_id)
                    elif entry_id:
                        result["rejected"].append(f"delete:{entry_id}:not_found")
            except Exception as e:
                logger.warning("Failed to apply memory action %s: %s", action, e)
                result["rejected"].append(f"{action.get('type')}:error")
        return result

    # ------------------------------------------------------------------
    # Trace persistence
    # ------------------------------------------------------------------

    def _save_trace(self, trace: dict) -> None:
        """Persist a trace dict as JSON. Never raises."""
        try:
            ts = trace.get("timestamp", datetime.now().isoformat())
            stamp = ts.replace(":", "-").replace(".", "-")
            filename = f"{stamp}_{trace.get('mode', 'unknown')}.json"
            path = self._trace_dir / filename
            path.write_text(
                json.dumps(trace, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._prune_old_traces(keep=50)
        except Exception as e:
            logger.warning("Failed to save memory trace: %s", e)

    def _prune_old_traces(self, keep: int = 50) -> None:
        try:
            files = sorted(
                self._trace_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for f in files[keep:]:
                f.unlink()
        except Exception:
            pass

    def list_traces(self, limit: int = 20) -> list[dict]:
        """Return summaries of the most recent traces."""
        try:
            files = sorted(
                self._trace_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            summaries = []
            for f in files[:limit]:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    summaries.append({
                        "file": f.name,
                        "timestamp": data.get("timestamp"),
                        "mode": data.get("mode"),
                        "status": data.get("status"),
                        "saved_count": len(data.get("applied_result", {}).get("saved", [])),
                        "deleted_count": len(data.get("applied_result", {}).get("deleted", [])),
                        "error": data.get("error"),
                    })
                except Exception:
                    continue
            return summaries
        except Exception:
            return []

    def get_trace(self, filename: str) -> dict | None:
        """Load a single trace by filename."""
        try:
            path = self._trace_dir / filename
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------


def _new_trace(mode: str) -> dict:
    """Initialize a trace dict with timestamp and mode."""
    return {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "status": "running",
    }
