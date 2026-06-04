"""
Inspect the system prompt that A1pro builds at initialization.

Usage:
    python scripts/inspect_prompt.py                  # full prompt
    python scripts/inspect_prompt.py --section tools  # one section only
    python scripts/inspect_prompt.py --stats          # token/char counts only
    python scripts/inspect_prompt.py --save out.txt   # write to file

The script does NOT call any LLM — it just builds A1pro and prints
prompt_builder.build(). Safe to run without API keys (we pass a fake LLM).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from anywhere
ROOT = Path(__file__).resolve().parent.parent.parent  # repo root (tests/scripts/ → 3 levels up)
sys.path.insert(0, str(ROOT))


def _build_agent_without_llm():
    """Build A1pro but skip the real LLM init.

    We monkey-patch get_llm in BOTH the llm module and base.py's namespace
    (since base.py does `from .llm import get_llm`, it has its own reference).
    """
    from CAi.CAi_agent import base as base_module
    from CAi.CAi_agent import llm as llm_module

    class _StubLLM:
        def invoke(self, *_a, **_k):
            raise RuntimeError("Stub LLM — inspect script should not call invoke")

        def stream(self, *_a, **_k):
            return iter([])

    stub_factory = lambda *a, **k: _StubLLM()  # noqa: E731
    original_llm = llm_module.get_llm
    original_base = base_module.get_llm
    llm_module.get_llm = stub_factory
    base_module.get_llm = stub_factory
    try:
        from CAi.CAi_agent.agent import A1pro

        agent = A1pro(
            llm="stub-model",
            #local_tools_dir=str(ROOT / "agent_workspace/_local_tools"),
        )
        return agent
    finally:
        llm_module.get_llm = original_llm
        base_module.get_llm = original_base


def _section_breakdown(agent) -> list[tuple[str, str]]:
    """Return [(section_name, rendered_text), ...] for each prompt section."""
    sections = agent.prompt_builder.sections
    return [(s.__class__.__name__, s.render()) for s in sections]


def _print_stats(agent) -> None:
    full = agent.system_prompt
    sections = _section_breakdown(agent)

    # Rough token estimate: 1 token ≈ 4 chars for English, ≈ 1.5 for CJK
    def est_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    print("=" * 70)
    print("PROMPT STATISTICS")
    print("=" * 70)
    print(f"{'Section':<25} {'Chars':>10} {'~Tokens':>10} {'%':>8}")
    print("-" * 70)
    total_chars = len(full)
    for name, text in sections:
        chars = len(text)
        pct = (chars / total_chars * 100) if total_chars else 0
        print(f"{name:<25} {chars:>10} {est_tokens(text):>10} {pct:>7.1f}%")
    print("-" * 70)
    print(f"{'TOTAL':<25} {total_chars:>10} {est_tokens(full):>10} {100.0:>7.1f}%")
    print("=" * 70)
    print(f"Tools loaded:       {len(agent.tool_registry)}")
    print(f"Skills loaded:      {len(agent.list_skills())}")
    print(f"Utilities loaded:   {len(agent.utility_registry) if agent.utility_registry else 0}")
    print(f"Local tools loaded: {len(agent.local_tools_loader) if getattr(agent, 'local_tools_loader', None) else 0}")


def _print_section(agent, section_filter: str) -> None:
    target = section_filter.lower()
    sections = _section_breakdown(agent)
    matched = [(n, t) for n, t in sections if target in n.lower()]
    if not matched:
        available = ", ".join(n for n, _ in sections)
        print(f"No section matches '{section_filter}'. Available: {available}")
        return
    for name, text in matched:
        print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
        print(text or "(empty)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect A1pro's system prompt.")
    parser.add_argument(
        "--section", help="Print only sections whose name contains this substring "
                         "(case-insensitive). E.g. 'tools', 'utilities', 'skills'."
    )
    parser.add_argument("--stats", action="store_true", help="Print only size statistics.")
    parser.add_argument("--save", metavar="PATH", help="Save the full prompt to a file.")
    args = parser.parse_args()

    print("Building A1pro (no LLM call)...", flush=True)
    agent = _build_agent_without_llm()
    print("Done.\n")

    if args.save:
        Path(args.save).write_text(agent.system_prompt, encoding="utf-8")
        print(f"Saved full prompt to {args.save}")

    if args.stats:
        _print_stats(agent)
        return

    if args.section:
        _print_section(agent, args.section)
        return

    # Default: print everything with section dividers
    print("=" * 70)
    print("FULL SYSTEM PROMPT")
    print("=" * 70)
    for name, text in _section_breakdown(agent):
        print(f"\n┌─ {name} {'─' * (66 - len(name))}")
        if text:
            for line in text.split("\n"):
                print(f"│ {line}")
        else:
            print("│ (empty — section dropped from final prompt)")
        print(f"└{'─' * 69}")

    print()
    _print_stats(agent)


if __name__ == "__main__":
    main()
