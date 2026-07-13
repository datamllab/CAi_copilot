"""Tests for context compression (hybrid partition, Scheme B).

Covers:
- _score_message scoring logic
- _maybe_compress_history zones and budget enforcement
- Custom _context_compress_hook override
- No compression when history fits within budget
"""

from __future__ import annotations


def _make_history(n: int) -> list[dict]:
    """Generate a synthetic conversation history with alternating user/assistant messages."""
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append({"role": "user", "content": f"user question {i}"})
        else:
            msgs.append({"role": "assistant", "content": f"assistant reply {i}"})
    return msgs


def _make_history_with_observations(n: int) -> list[dict]:
    """Generate history where every other assistant message contains an <observation>."""
    msgs = []
    for i in range(n):
        if i % 3 == 0:
            msgs.append({"role": "user", "content": f"run step {i}"})
        elif i % 3 == 1:
            msgs.append({
                "role": "assistant",
                "content": f"<execute>tool_call({i})</execute>",
            })
        else:
            msgs.append({
                "role": "assistant",
                "content": f"<observation>\nsuccess: result_{i}\n</observation>",
            })
    return msgs


# ---------------------------------------------------------------------------
# _score_message
# ---------------------------------------------------------------------------


def test_score_user_message():
    from CAi.CAi_agent.context_compression import _score_message

    msg = {"role": "user", "content": "generate molecules for this scaffold"}
    assert _score_message(msg) >= 10


def test_score_user_with_keywords():
    from CAi.CAi_agent.context_compression import _score_message

    msg = {"role": "user", "content": "use num_sample=50 and scaffold C1CC1"}
    assert _score_message(msg) >= 15


def test_score_assistant_observation():
    from CAi.CAi_agent.context_compression import _score_message

    msg = {"role": "assistant", "content": "<observation>\nsuccess: true\n</observation>"}
    assert _score_message(msg) == 8


def test_score_assistant_execute():
    from CAi.CAi_agent.context_compression import _score_message

    msg = {"role": "assistant", "content": "<execute>print(1)</execute> some text"}
    # <execute> matches _IMPORTANT_KEYWORDS so score is 6
    assert _score_message(msg) == 6


def test_score_assistant_plain_reasoning():
    from CAi.CAi_agent.context_compression import _score_message

    msg = {"role": "assistant", "content": "Let me think about this approach..."}
    assert _score_message(msg) == 2


def test_score_assistant_with_important_keywords():
    from CAi.CAi_agent.context_compression import _score_message

    msg = {"role": "assistant", "content": "The docking score is -8.5 for this SMILES: CC(=O)Oc1ccccc1"}
    assert _score_message(msg) >= 6


# ---------------------------------------------------------------------------
# _maybe_compress_history — no compression
# ---------------------------------------------------------------------------


def test_no_compression_when_within_budget(base_agent):
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 10  # max 20 messages

    history = _make_history(16)
    compressed = agent._maybe_compress_history(history)
    assert compressed == history  # unchanged


def test_no_compression_when_exact_limit(base_agent):
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 5  # max 10 messages

    history = _make_history(10)
    compressed = agent._maybe_compress_history(history)
    assert len(compressed) == 10


# ---------------------------------------------------------------------------
# _maybe_compress_history — hybrid partition
# ---------------------------------------------------------------------------


def test_hybrid_keeps_recent_half(base_agent):
    """Recent half is preserved verbatim."""
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 5  # max 10 messages

    history = _make_history(20)
    compressed = agent._maybe_compress_history(history)

    # Should have notice + middle_kept + recent
    # Recent = max_msgs // 2 = 5
    recent_start = len(compressed) - 5
    recent_compressed = compressed[recent_start:]
    recent_expected = history[-5:]
    assert recent_compressed == recent_expected


def test_hybrid_drops_low_score_messages(base_agent):
    """Low-score assistant reasoning messages are dropped from middle zone."""
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 3  # max 6 messages

    # Create 12 messages: mix of user (score 10) and plain assistant (score 2)
    history = _make_history(12)
    compressed = agent._maybe_compress_history(history)

    # Total compressed should not exceed max_msgs significantly
    # (the notice adds 1 extra message)
    assert len(compressed) <= 7  # max 6 + 1 notice


def test_hybrid_preserves_observations(base_agent):
    """Observation messages (score 8) are retained in the middle zone."""
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 5  # max 10 messages

    history = _make_history_with_observations(20)
    compressed = agent._maybe_compress_history(history)

    # Count how many observations survived
    obs_count = sum(
        1 for m in compressed
        if m.get("role") == "assistant" and "<observation>" in m.get("content", "")
    )
    # Observations are high-score (8), so should be preserved
    assert obs_count > 0


def test_hybrid_notice_message(base_agent):
    """A notice is prepended when messages are dropped."""
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 3  # max 6 messages

    history = _make_history(14)
    compressed = agent._maybe_compress_history(history)

    # First message should be a notice
    assert compressed[0]["role"] == "assistant"
    assert "已省略" in compressed[0]["content"]


def test_hybrid_compress_directly():
    """Call hybrid_compress directly without going through BaseAgent."""
    from CAi.CAi_agent.context_compression import hybrid_compress

    history = _make_history_with_observations(20)
    compressed = hybrid_compress(history, max_pairs=5)

    # Should fit within budget (max 10 msgs + 1 notice)
    assert len(compressed) <= 11
    # Notice should be present
    assert "已省略" in compressed[0]["content"]
    # Recent messages should be preserved at the tail
    assert compressed[-5:] == history[-5:]


# ---------------------------------------------------------------------------
# Custom _context_compress_hook
# ---------------------------------------------------------------------------


def test_custom_compress_hook(base_agent):
    """A custom hook replaces the default hybrid partition."""
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 2  # max 4 messages

    def keep_only_last_two(history):
        return history[-2:]

    agent._context_compress_hook = keep_only_last_two

    history = _make_history(10)
    compressed = agent._maybe_compress_history(history)

    assert len(compressed) == 2
    assert compressed == history[-2:]


def test_compress_hook_failure_falls_back(base_agent):
    """When the custom hook raises, fall back to hybrid partition."""
    agent, fake = base_agent(responses=["ok"])
    agent.max_history_pairs = 2

    def broken_hook(history):
        raise RuntimeError("hook crashed")

    agent._context_compress_hook = broken_hook

    history = _make_history(10)
    compressed = agent._maybe_compress_history(history)

    # Should still return a valid compressed history (via fallback)
    assert len(compressed) > 0
    assert all("role" in m for m in compressed)


# ---------------------------------------------------------------------------
# ContextCompressor — direct usage
# ---------------------------------------------------------------------------


def test_compressor_no_compression_within_budget():
    """ContextCompressor returns history unchanged when within budget."""
    from CAi.CAi_agent.compression import ContextCompressor

    c = ContextCompressor(max_pairs=10)
    history = _make_history(16)
    result = c.compress(history)
    assert result is history  # same object, no copy


def test_compressor_compresses_when_over_budget():
    """ContextCompressor triggers compression when history exceeds budget."""
    from CAi.CAi_agent.compression import ContextCompressor

    c = ContextCompressor(max_pairs=3)  # max 6 messages
    history = _make_history(14)
    result = c.compress(history)
    assert len(result) <= 7  # 6 + 1 notice


def test_compressor_custom_strategy():
    """ContextCompressor accepts a custom strategy function."""
    from CAi.CAi_agent.compression import ContextCompressor

    def keep_last_four(history, max_pairs=40):
        return history[-4:]

    c = ContextCompressor(max_pairs=2, strategy=keep_last_four)
    history = _make_history(10)
    result = c.compress(history)
    assert len(result) == 4
    assert result == history[-4:]


def test_compressor_custom_hook_takes_precedence():
    """custom_hook is tried before strategy."""
    from CAi.CAi_agent.compression import ContextCompressor

    def hook(history):
        return [{"role": "assistant", "content": "hooked!"}]

    def should_not_run(history, max_pairs=40):
        raise AssertionError("strategy should not be called")

    c = ContextCompressor(max_pairs=1, strategy=should_not_run, custom_hook=hook)
    history = _make_history(10)
    result = c.compress(history)
    assert len(result) == 1
    assert result[0]["content"] == "hooked!"


def test_compressor_hook_failure_falls_back_to_strategy():
    """When custom_hook raises, strategy is used as fallback."""
    from CAi.CAi_agent.compression import ContextCompressor

    def broken_hook(history):
        raise RuntimeError("boom")

    def fallback(history, max_pairs=40):
        return history[-2:]

    c = ContextCompressor(max_pairs=1, strategy=fallback, custom_hook=broken_hook)
    history = _make_history(10)
    result = c.compress(history)
    assert len(result) == 2


def test_compressor_callable_protocol():
    """ContextCompressor instances can be called directly."""
    from CAi.CAi_agent.compression import ContextCompressor

    c = ContextCompressor(max_pairs=2)
    history = _make_history(10)
    # __call__ should work the same as .compress()
    assert c(history) == c.compress(history)


def test_compressor_repr():
    """ContextCompressor has a useful repr."""
    from CAi.CAi_agent.compression import ContextCompressor

    c = ContextCompressor(max_pairs=20)
    assert "max_pairs=20" in repr(c)
    assert "no hook" in repr(c)

    c2 = ContextCompressor(max_pairs=5, custom_hook=lambda h: h)
    assert "with hook" in repr(c2)


def test_compressor_via_agent_constructor():
    """BaseAgent accepts a pre-built compressor."""
    from CAi.CAi_agent.compression import ContextCompressor

    agent, fake = _make_base_agent_with_compressor(
        ContextCompressor(max_pairs=7)
    )
    assert agent.max_history_pairs == 7


def _make_base_agent_with_compressor(compressor):
    """Helper: build a BaseAgent with a FakeLLM and a given compressor."""
    import unittest.mock

    from CAi.CAi_agent.base import BaseAgent

    fake = type("FakeLLM", (), {
        "invoke": lambda self, msgs: type("R", (), {"content": "<done/>"})(),
        "calls": [],
        "call_count": 0,
    })()

    with unittest.mock.patch("CAi.CAi_agent.base.get_llm", return_value=fake):
        agent = BaseAgent(
            llm="fake",
            source="Custom",
            base_url="http://fake",
            api_key="fake",
            compressor=compressor,
        )
    return agent, fake
