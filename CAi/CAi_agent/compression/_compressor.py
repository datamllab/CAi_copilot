"""ContextCompressor — decides whether and how to compress conversation history.

This is the orchestrator that absorbs the decision logic previously scattered
in BaseAgent: size check, custom hook with fallback, and default strategy dispatch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._hybrid import hybrid_compress

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class ContextCompressor:
    """Decides whether history needs compression and dispatches to a strategy.

    Parameters
    ----------
    max_pairs : int
        Maximum conversation pairs before compression triggers.
        Converted to ``max_pairs * 2`` messages internally.
    strategy : callable, optional
        ``(history, max_pairs=N) -> compressed_history``.
        Defaults to :func:`hybrid_compress`.
    custom_hook : callable, optional
        Legacy override: ``(history) -> compressed_history``.
        Takes precedence over *strategy* when set. If it raises,
        falls back to *strategy* with a warning.

    Examples
    --------
    Basic usage::

        compressor = ContextCompressor(max_pairs=40)
        compressed = compressor.compress(history)

    With a custom strategy::

        def my_strategy(history, max_pairs=40):
            return history[-(max_pairs * 2):]

        compressor = ContextCompressor(max_pairs=20, strategy=my_strategy)
    """

    def __init__(
        self,
        max_pairs: int = 40,
        strategy: Callable[..., list[dict]] | None = None,
        custom_hook: Callable[[list[dict]], list[dict]] | None = None,
    ):
        self.max_pairs = max_pairs
        self._strategy = strategy or hybrid_compress
        self._custom_hook = custom_hook

    def compress(self, history: list[dict]) -> list[dict]:
        """Compress *history* if it exceeds the budget; otherwise return as-is.

        This is the single entry point for compression. The method:
        1. Returns history unchanged if within budget.
        2. Tries the custom hook (if set), falling back on failure.
        3. Dispatches to the strategy (default: hybrid_compress).
        """
        max_msgs = self.max_pairs * 2
        if len(history) <= max_msgs:
            return history

        if self._custom_hook is not None:
            try:
                return self._custom_hook(history)
            except Exception as exc:
                logger.warning(
                    "Custom compress hook failed: %s; falling back to default strategy",
                    exc,
                )

        return self._strategy(history, max_pairs=self.max_pairs)

    # Allow calling the instance directly: ``compressor(history)``
    __call__ = compress

    def __repr__(self) -> str:
        hook = "with hook" if self._custom_hook else "no hook"
        return f"ContextCompressor(max_pairs={self.max_pairs}, {hook})"
