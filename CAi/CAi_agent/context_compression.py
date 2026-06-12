"""Backward-compatibility shim — all symbols moved to ``CAi.CAi_agent.compression``.

This module re-exports everything from the new ``compression`` package so that
existing import paths (``from CAi.CAi_agent.context_compression import ...``)
continue to work without modification.
"""

from __future__ import annotations

from .compression import (
    _IMPORTANT_KEYWORDS,
    _has_plan_block,
    _preserve_plan,
    _score_message,
    hybrid_compress,
)

__all__ = [
    "hybrid_compress",
    "_score_message",
    "_preserve_plan",
    "_has_plan_block",
    "_IMPORTANT_KEYWORDS",
]
