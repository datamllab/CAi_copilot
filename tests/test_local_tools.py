"""Tests for the local_tools subsystem."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from CAi.CAi_agent.local_tools.loader import LocalToolsLoader
from CAi.CAi_agent.local_tools.section import LocalToolsSection
from CAi.CAi_agent.local_tools.spec import LocalToolCommand, LocalToolSpec


# ---------------------------------------------------------------------------
# LocalToolSpec.from_file
# ---------------------------------------------------------------------------


def _write_tool_yaml(tmp_dir: Path, content: str, name: str = "test_tool.yaml") -> Path:
    path = tmp_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def test_from_file_parses_basic_fields(tmp_path):
    path = _write_tool_yaml(
        tmp_path,
        "name: GROMACS\ndescription: MD engine\ninit_command: source /opt/gmx/bin/GMXRC\n",
    )
    spec = LocalToolSpec.from_file(path)
    assert spec.name == "GROMACS"
    assert spec.description == "MD engine"
    assert spec.init_command == "source /opt/gmx/bin/GMXRC"
    assert spec.common_commands == []


def test_from_file_parses_commands(tmp_path):
    yaml_content = """\
name: GROMACS
description: MD engine
init_command: source /opt/gmx/bin/GMXRC
common_commands:
  - name: pdb2gmx
    description: PDB to topology
    example: gmx pdb2gmx -f protein.pdb
  - name: mdrun
    description: Run simulation
    example: gmx mdrun -deffnm md
"""
    path = _write_tool_yaml(tmp_path, yaml_content)
    spec = LocalToolSpec.from_file(path)
    assert len(spec.common_commands) == 2
    assert spec.common_commands[0].name == "pdb2gmx"
    assert spec.common_commands[0].example == "gmx pdb2gmx -f protein.pdb"
    assert spec.common_commands[1].name == "mdrun"


def test_from_file_missing_name_raises(tmp_path):
    path = _write_tool_yaml(tmp_path, "description: no name\n")
    with pytest.raises(ValueError, match="Missing 'name'"):
        LocalToolSpec.from_file(path)


def test_from_file_empty_file_raises(tmp_path):
    path = _write_tool_yaml(tmp_path, "")
    with pytest.raises(ValueError, match="Missing 'name'"):
        LocalToolSpec.from_file(path)


# ---------------------------------------------------------------------------
# LocalToolsLoader
# ---------------------------------------------------------------------------


def test_loader_empty_dir(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    loader = LocalToolsLoader(empty_dir)
    assert len(loader) == 0
    assert loader.tools == {}


def test_loader_nonexistent_dir(tmp_path):
    loader = LocalToolsLoader(tmp_path / "does_not_exist")
    assert len(loader) == 0


def test_loader_loads_one_tool(tmp_path):
    _write_tool_yaml(
        tmp_path,
        "name: GROMACS\ndescription: MD engine\ninit_command: source /opt/gmx/bin/GMXRC\n",
    )
    loader = LocalToolsLoader(tmp_path)
    assert len(loader) == 1
    assert "GROMACS" in loader.tools


def test_loader_loads_multiple_tools(tmp_path):
    _write_tool_yaml(tmp_path, "name: GROMACS\ndescription: MD engine\n", "gromacs.yaml")
    _write_tool_yaml(tmp_path, "name: AMBER\ndescription: Another MD engine\n", "amber.yaml")
    loader = LocalToolsLoader(tmp_path)
    assert len(loader) == 2
    assert "GROMACS" in loader.tools
    assert "AMBER" in loader.tools


def test_loader_skips_malformed_files(tmp_path):
    _write_tool_yaml(tmp_path, "name: GROMACS\n", "good.yaml")
    _write_tool_yaml(tmp_path, "description: no name\n", "bad.yaml")
    loader = LocalToolsLoader(tmp_path)
    assert len(loader) == 1
    assert "GROMACS" in loader.tools


def test_loader_reload(tmp_path):
    _write_tool_yaml(tmp_path, "name: GROMACS\ndescription: v1\n", "gromacs.yaml")
    loader = LocalToolsLoader(tmp_path)
    assert loader.tools["GROMACS"].description == "v1"

    # Update the file and reload
    _write_tool_yaml(tmp_path, "name: GROMACS\ndescription: v2\n", "gromacs.yaml")
    loader.reload()
    assert loader.tools["GROMACS"].description == "v2"


def test_loader_get_summaries(tmp_path):
    yaml_content = """\
name: GROMACS
description: MD engine
init_command: source /opt/gmx/bin/GMXRC
common_commands:
  - name: mdrun
    description: Run sim
    example: gmx mdrun
"""
    _write_tool_yaml(tmp_path, yaml_content)
    loader = LocalToolsLoader(tmp_path)
    summaries = loader.get_summaries()
    assert len(summaries) == 1
    assert summaries[0]["name"] == "GROMACS"
    assert summaries[0]["has_init"] is True
    assert summaries[0]["command_count"] == 1


# ---------------------------------------------------------------------------
# LocalToolsSection
# ---------------------------------------------------------------------------


def test_section_render_empty_when_no_loader():
    section = LocalToolsSection(None)
    assert section.render() == ""


def test_section_render_empty_when_no_tools(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    loader = LocalToolsLoader(empty_dir)
    section = LocalToolsSection(loader)
    assert section.render() == ""


def test_section_render_shows_tool_name_and_description(tmp_path):
    _write_tool_yaml(tmp_path, "name: GROMACS\ndescription: MD engine v2026\n")
    loader = LocalToolsLoader(tmp_path)
    section = LocalToolsSection(loader)
    text = section.render()
    assert "GROMACS" in text
    assert "MD engine v2026" in text


def test_section_render_shows_init_command(tmp_path):
    _write_tool_yaml(
        tmp_path,
        "name: GROMACS\ndescription: MD\ninit_command: source /opt/gmx/bin/GMXRC\n",
    )
    loader = LocalToolsLoader(tmp_path)
    text = LocalToolsSection(loader).render()
    assert "source /opt/gmx/bin/GMXRC" in text
    assert "BEFORE first use" in text


def test_section_render_shows_commands(tmp_path):
    yaml_content = """\
name: GROMACS
description: MD engine
init_command: source /opt/gmx/bin/GMXRC
common_commands:
  - name: pdb2gmx
    description: PDB to topology
    example: gmx pdb2gmx -f protein.pdb
  - name: mdrun
    description: Run simulation
    example: gmx mdrun -v
"""
    _write_tool_yaml(tmp_path, yaml_content)
    loader = LocalToolsLoader(tmp_path)
    text = LocalToolsSection(loader).render()
    assert "pdb2gmx" in text
    assert "PDB to topology" in text
    assert "gmx pdb2gmx -f protein.pdb" in text
    assert "mdrun" in text
    assert "gmx mdrun -v" in text


def test_section_render_header(tmp_path):
    _write_tool_yaml(tmp_path, "name: GROMACS\ndescription: MD\n")
    loader = LocalToolsLoader(tmp_path)
    text = LocalToolsSection(loader).render()
    assert "LOCALLY INSTALLED CLI TOOLS" in text
    assert "#!BASH" in text


# ---------------------------------------------------------------------------
# Integration: gromacs.yaml in workspace
# ---------------------------------------------------------------------------


def test_gromacs_workspace_config_loads():
    """Verify the actual gromacs.yaml in agent_workspace loads correctly."""
    workspace_dir = Path("agent_workspace/_local_tools")
    if not workspace_dir.is_dir():
        pytest.skip("agent_workspace/_local_tools not found")

    loader = LocalToolsLoader(workspace_dir)
    assert "GROMACS" in loader.tools
    spec = loader.tools["GROMACS"]
    assert "GMXRC" in spec.init_command
    assert len(spec.common_commands) >= 5

    section = LocalToolsSection(loader)
    text = section.render()
    assert "GROMACS" in text
    assert "pdb2gmx" in text
    assert "mdrun" in text
