"""Hybrid partition compression — Scheme B (zero extra LLM calls).

Three-zone model when history exceeds the budget:
  Zone 1 (recent ~50%): kept verbatim for coherent context.
  Zone 2 (middle): selectively keep high-score messages (score >= 6).
  Zone 3 (oldest): dropped, with a one-line summary notice prepended.
"""

from __future__ import annotations

from ._plan_preserve import _preserve_plan
from ._scoring import _score_message


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
