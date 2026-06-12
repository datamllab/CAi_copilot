"""Message importance scoring for context compression.

Scoring heuristic:
  - user messages: 10 (+5 if contains domain keywords)
  - assistant + <observation>: 8  (factual tool results)
  - assistant + domain keywords: 6
  - assistant + <execute>: 5
  - assistant plain reasoning: 2  (safe to drop)
"""

from __future__ import annotations

import re

# Keywords that signal important domain data worth preserving.
_IMPORTANT_KEYWORDS = re.compile(
    r"SMILES|scaffold|\.pdb|\.sdf|\.gro|\.xtc|\.top|"
    r"num_sample|num_analogs|score|energy|docking|"
    r"success|error|output_|result|file|path|"
    r"<observation>|<execute>",
    re.IGNORECASE,
)


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
