"""Context compression — strategies and orchestrator for conversation history.

Architecture note:
    Compression fires **once** when the user sends a message (i.e. at the
    entry point of ``BaseAgent.run_with_history*``). The generate→execute→
    generate loop appends directly to the messages list and MUST NOT
    re-invoke compression — mid-loop compression would discard observations
    the agent is actively reasoning about.

Public API:
    - :class:`ContextCompressor` — orchestrator (size check + hook + strategy)
    - :func:`hybrid_compress` — default three-zone partition strategy
    - :func:`_score_message` — message importance scoring heuristic
"""

from __future__ import annotations

from ._compressor import ContextCompressor
from ._hybrid import hybrid_compress
from ._plan_preserve import _has_plan_block, _preserve_plan
from ._scoring import _IMPORTANT_KEYWORDS, _score_message

__all__ = [
    "ContextCompressor",
    "hybrid_compress",
    "_score_message",
    "_IMPORTANT_KEYWORDS",
    "_preserve_plan",
    "_has_plan_block",
]
