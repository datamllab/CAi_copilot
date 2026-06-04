"""Context compression strategies for conversation history.

Default strategy: **Scheme B — hybrid partition** (zero extra LLM calls).

Three-zone model when history exceeds the budget:
  Zone 1 (recent ~50%): kept verbatim for coherent context.
  Zone 2 (middle): selectively keep high-score messages (score >= 6).
  Zone 3 (oldest): dropped, with a one-line summary notice prepended.

Scoring heuristic (_score_message):
  - user messages: 10 (+5 if contains domain keywords)
  - assistant + <observation>: 8  (factual tool results)
  - assistant + domain keywords: 6
  - assistant + <execute>: 5
  - assistant plain reasoning: 2  (safe to drop)

Plan preservation:
  Messages containing ``<execute lang="plan">`` are special-cased: the
  **latest** plan message is always preserved through compression (prepended
  to the result), while older plan messages participate in normal compression
  and may be dropped. This ensures the agent never loses track of its
  current task plan.

Users can swap in a custom strategy (e.g. LLM-based summarisation) via
``BaseAgent._context_compress_hook``.
"""

from __future__ import annotations

import functools
import re

# Keywords that signal important domain data worth preserving.
_IMPORTANT_KEYWORDS = re.compile(
    r"SMILES|scaffold|\.pdb|\.sdf|\.gro|\.xtc|\.top|"
    r"num_sample|num_analogs|score|energy|docking|"
    r"success|error|output_|result|file|path|"
    r"<observation>|<execute>",
    re.IGNORECASE,
)

#: Detect <execute lang="plan"> blocks for plan preservation.
_PLAN_RE = re.compile(r'<execute\s+lang="plan"', re.IGNORECASE)


def _has_plan_block(content: str) -> bool:
    """Return True if the message content contains a plan execute block."""
    return bool(_PLAN_RE.search(content))


def _preserve_plan(compress_fn):
    """Decorator: extract the latest ``<execute lang="plan">`` message before
    compression, then prepend it to the compressed result.

    This guarantees the current task plan survives context compression
    regardless of how aggressively older messages are pruned.
    """
    @functools.wraps(compress_fn)
    def wrapper(history: list[dict], **kw) -> list[dict]:
        # Find all messages containing plan blocks.
        plan_indices = [
            i for i, m in enumerate(history)
            if _has_plan_block(m.get("content", ""))
        ]
        if not plan_indices:
            return compress_fn(history, **kw)

        # Keep only the latest plan message; older ones participate in compression.
        latest_idx = plan_indices[-1]
        latest_plan = history[latest_idx]

        # Remove ALL plan messages from the history fed to compression.
        filtered = [m for i, m in enumerate(history) if i not in plan_indices]
        compressed = compress_fn(filtered, **kw)

        # Prepend the latest plan so it's always the first message seen.
        return [latest_plan, *compressed]

    return wrapper


def _score_message(msg: dict) -> int:
    """Score a message by importance — higher means more critical to keep.

    Scoring logic:
      - user messages: high base score (instructions are critical)
      - assistant + observation / tool result: high (factual data)
      - assistant + code blocks or important keywords: medium
      - assistant plain text reasoning: low (can be safely dropped)
    """
    role = msg.get("role", "")
    content = msg.get("content", "")

    if role == "user":
        score = 10
        if _IMPORTANT_KEYWORDS.search(content):
            score += 5
        return score

    # Assistant messages: score by content type
    if "<observation>" in content:
        return 8  # Tool execution results — factual data
    if _IMPORTANT_KEYWORDS.search(content):
        return 6  # References important data / files / results
    if "<execute>" in content:
        return 5  # Contains code that was run
    # Pure reasoning / conversational filler
    return 2


@_preserve_plan
def hybrid_compress(history: list[dict], max_pairs: int = 40) -> list[dict]:
    """Compress history using the hybrid partition strategy.

    Parameters
    ----------
    history : list[dict]
        Conversation history as ``{"role": str, "content": str}`` dicts.
    max_pairs : int
        Maximum number of message *pairs* to fit into the budget.
        The function converts this to individual messages (``* 2``).

    Returns
    -------
    list[dict]
        Compressed history that fits within ``max_pairs * 2`` messages
        (plus at most one summary notice).
    """
    max_msgs = max_pairs * 2

    if len(history) <= max_msgs:
        return history

    # Zone 1: most recent half — keep verbatim.
    recent_count = max_msgs // 2
    recent = history[-recent_count:]

    # Zone 2: middle region — keep only high-value messages.
    middle_end = len(history) - recent_count
    middle = history[:middle_end]
    middle_kept = [m for m in middle if _score_message(m) >= 6]

    # Trim middle if the combined count still exceeds budget.
    budget_left = max_msgs - recent_count - len(middle_kept)
    if budget_left < 0:
        middle_kept.sort(key=_score_message, reverse=True)
        excess = len(middle_kept) + recent_count - max_msgs
        middle_kept = middle_kept[:len(middle_kept) - excess]

    total_dropped = len(history) - len(middle_kept) - len(recent)

    result: list[dict] = []
    if total_dropped > 0:
        result.append({
            "role": "assistant",
            "content": (
                f"[注意：已省略 {total_dropped} 条低优先级消息以节省上下文。"
                f"保留中间 {len(middle_kept)} 条关键消息 + 最近 {len(recent)} 条原始对话。]"
            ),
        })
    result.extend(middle_kept)
    result.extend(recent)
    return result
