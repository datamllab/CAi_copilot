"""Infrastructure tests for the Utility subsystem.

These tests verify:
- UtilityRegistry loads, persists, and manages utilities correctly
- Skills load correctly with descriptions
- Prompt section ordering (Utilities before Tools)
- Empty utilities sections are dropped from prompt

Tests involving actual kernel operations (injection, usage tracking,
restart survival) are marked @pytest.mark.slow and need a working
Jupyter kernel environment.
"""

from __future__ import annotations

import pytest

from CAi.CAi_agent.skills import SkillLoader
from CAi.CAi_agent.utilities.registry import UtilityRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_EXPECTED_SKILL_IDS = {
    "de_novo_without_base",
    "full_analog_design",
    "id_protein_search",
    "molecule_analysis",
    "protein_based_de_novo",
    "scaffold_design",
    "tools_guidance",
    "unique_molecule",
}


@pytest.fixture
def temp_utilities_dir(tmp_path):
    """Create a temporary utilities directory with sample .py files."""
    util_dir = tmp_path / "_utilities"
    util_dir.mkdir()

    util_file = util_dir / "add_numbers.py"
    util_file.write_text(
        '# @name: add_numbers\n'
        '# @description: Adds two numbers together.\n'
        '# @call_count: 0\n'
        '# @success_count: 0\n'
        '# @created: 2026-01-01T00:00:00\n'
        '# @last_used: 2026-01-01T00:00:00\n'
        '\n'
        'def add_numbers(a: int, b: int) -> int:\n'
        '    """Add two numbers together."""\n'
        '    return a + b\n',
    )

    util_file2 = util_dir / "multiply_numbers.py"
    util_file2.write_text(
        '# @name: multiply_numbers\n'
        '# @description: Multiplies two numbers.\n'
        '# @call_count: 5\n'
        '# @success_count: 4\n'
        '# @created: 2026-01-01T00:00:00\n'
        '# @last_used: 2026-01-02T00:00:00\n'
        '\n'
        'def multiply_numbers(a: float, b: float) -> float:\n'
        '    """Multiply two numbers."""\n'
        '    return a * b\n',
    )

    return util_dir


# ---------------------------------------------------------------------------
# UtilityRegistry — fast unit tests
# ---------------------------------------------------------------------------


def test_utility_registry_load(temp_utilities_dir):
    """load_snapshot() should exec utilities and return {name: callable}."""
    registry = UtilityRegistry(temp_utilities_dir)
    assert len(registry) == 2

    utilities = registry.load_snapshot()
    assert "add_numbers" in utilities
    assert "multiply_numbers" in utilities
    assert callable(utilities["add_numbers"])
    assert utilities["add_numbers"](3, 4) == 7
    assert utilities["multiply_numbers"](3.0, 4.0) == 12.0


def test_utility_registry_apply_usage(temp_utilities_dir):
    """apply_usage should update call_count and success_count on disk."""
    registry = UtilityRegistry(temp_utilities_dir)

    usage = {
        "add_numbers": {"calls": 3, "errors": 1},
        "multiply_numbers": {"calls": 2, "errors": 0},
    }
    registry.apply_usage(usage)

    registry2 = UtilityRegistry(temp_utilities_dir)
    specs = {s.name: s for s in registry2._specs.values()}
    assert specs["add_numbers"].call_count == 3
    assert specs["add_numbers"].success_count == 2
    assert specs["multiply_numbers"].call_count == 7
    assert specs["multiply_numbers"].success_count == 6


def test_utility_registry_auto_eviction(tmp_path):
    """When exceeding max_utilities, least-used should be evicted."""
    util_dir = tmp_path / "_utilities"
    util_dir.mkdir()

    for i in range(22):
        f = util_dir / f"util_{i:02d}.py"
        f.write_text(
            f'# @name: util_{i:02d}\n'
            f'# @description: Utility {i}.\n'
            f'# @call_count: {i}\n'
            f'# @success_count: {i}\n'
            f'# @created: 2026-01-01T00:00:00\n'
            f'# @last_used: 2026-01-{i+1:02d}T00:00:00\n'
            f'\n'
            f'def util_{i:02d}() -> int:\n'
            f'    return {i}\n',
        )

    registry = UtilityRegistry(util_dir, max_utilities=20)
    assert len(registry) == 20

    names = set(registry._specs.keys())
    assert "util_00" not in names
    assert "util_01" not in names
    assert "util_21" in names


def test_utility_registry_empty_dir(tmp_path):
    """Empty directory should yield 0 utilities."""
    util_dir = tmp_path / "_utilities"
    util_dir.mkdir()
    registry = UtilityRegistry(util_dir)
    assert len(registry) == 0
    assert registry.load_snapshot() == {}


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------


def test_all_skills_loaded():
    """All 8 skill files should load with descriptions."""
    loader = SkillLoader()
    summaries = loader.get_skill_summaries()
    ids = {s["id"] for s in summaries}
    assert ids == _EXPECTED_SKILL_IDS

    for s in summaries:
        assert s["name"], f"Skill {s['id']} has no name"
        assert s["description"], f"Skill {s['id']} has no description"


def test_skill_descriptions_not_truncated():
    """Skill descriptions should be extracted properly."""
    loader = SkillLoader()
    summaries = loader.get_skill_summaries()
    for s in summaries:
        assert len(s["description"]) > 10, f"Skill {s['id']} description too short"


def test_skill_metadata_extraction():
    """Skills should have metadata extracted."""
    loader = SkillLoader()
    summaries = loader.get_skill_summaries()
    for s in summaries:
        meta = s.get("metadata") or {}
        assert isinstance(meta, dict), f"Skill {s['id']} metadata is not a dict"


# ---------------------------------------------------------------------------
# Prompt section ordering
# ---------------------------------------------------------------------------


def test_empty_utilities_section_dropped(temp_utilities_dir):
    """When no utilities exist, UtilitiesSection should render empty."""
    empty_dir = temp_utilities_dir.parent / "_empty_utilities"
    empty_dir.mkdir(exist_ok=True)
    registry = UtilityRegistry(empty_dir)

    from CAi.CAi_agent.utilities import UtilitiesSection

    section = UtilitiesSection(registry)
    rendered = section.render()
    assert rendered == ""


def test_prompt_with_utilities_includes_them(temp_utilities_dir):
    """When utilities exist, UtilitiesSection should render their names."""
    registry = UtilityRegistry(temp_utilities_dir)

    from CAi.CAi_agent.utilities import UtilitiesSection

    section = UtilitiesSection(registry)
    rendered = section.render()
    assert "add_numbers" in rendered
    assert "multiply_numbers" in rendered


# ---------------------------------------------------------------------------
# Kernel-dependent tests (marked slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_utility_kernel_injection(temp_utilities_dir):
    """Injected utilities should be callable in the Jupyter kernel."""
    registry = UtilityRegistry(temp_utilities_dir)
    utilities = registry.load_snapshot()

    from CAi.CAi_agent.execution.repl import (
        _shutdown_kernel,
        inject_utilities_with_monitoring,
        run_python_repl,
    )

    try:
        inject_utilities_with_monitoring(utilities)
        code = "result = add_numbers(10, 20)\nprint(result)"
        stdout, error = run_python_repl(code, timeout=10)
        assert "30" in stdout
    finally:
        _shutdown_kernel()


@pytest.mark.slow
def test_usage_tracking_accuracy(temp_utilities_dir):
    """Usage tracking should accurately record calls."""
    registry = UtilityRegistry(temp_utilities_dir)
    utilities = registry.load_snapshot()

    from CAi.CAi_agent.execution.repl import (
        _shutdown_kernel,
        flush_utility_usage,
        inject_utilities_with_monitoring,
        run_python_repl,
    )

    try:
        inject_utilities_with_monitoring(utilities)
        code = "add_numbers(1, 2)\nadd_numbers(3, 4)\nadd_numbers(5, 6)\nprint('done')"
        run_python_repl(code, timeout=10)

        usage = flush_utility_usage()
        assert "add_numbers" in usage
        assert usage["add_numbers"]["calls"] == 3
        assert usage["add_numbers"]["errors"] == 0
    finally:
        _shutdown_kernel()


@pytest.mark.slow
def test_kernel_restart_survival(temp_utilities_dir):
    """After kernel restart, utilities should be re-injected."""
    registry = UtilityRegistry(temp_utilities_dir)
    utilities = registry.load_snapshot()

    from CAi.CAi_agent.execution.repl import (
        _shutdown_kernel,
        inject_utilities_with_monitoring,
        run_python_repl,
    )

    try:
        inject_utilities_with_monitoring(utilities)
        stdout, _ = run_python_repl("print(add_numbers(1, 1))", timeout=10)
        assert "2" in stdout

        _shutdown_kernel()

        stdout, _ = run_python_repl("print(add_numbers(5, 5))", timeout=10)
        assert "10" in stdout
    finally:
        _shutdown_kernel()
