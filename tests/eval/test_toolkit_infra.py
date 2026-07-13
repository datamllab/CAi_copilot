"""Infrastructure tests for the toolkit subsystem.

These tests run fast, need no LLM or tool server. They verify:
- All 10 tools are registered with correct signatures
- Validators reject invalid inputs correctly
- Tool return dicts match documented schema
- Prompt rendering includes all tools
"""

from __future__ import annotations

import inspect

import pytest

from CAi.CAi_agent.prompt import ToolsSection
from CAi.CAi_agent.tools import ModuleScanner, ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_TOOL_NAMES = {
    "generate_scaffold_analogs",
    "generate_libinvent_decorations",
    "generate_molecules_for_pocket",
    "generate_molecules_reinvent4_denovo",
    "generate_molecules_reinvent4_libinvent",
    "generate_molecules_reinvent4_mol2mol",
    "calculate_scscore",
    "predict_molecule_toxicity",
    "predict_antibacterial_pmic",
    "perform_molecular_docking_vina",
    "deepchem_molgan_generate",
    "deepchem_molgan_train",
    "deepchem_seq2seq_evaluate",
    "deepchem_seq2seq_train",
    "drugex_finetune",
    "drugex_generate",
    "drugex_rl",
    "generate_molecules_sc2mol",
    "infer_synthesis_synllama",
    "run_gromacs_md",
    "analyze_abfe_results",
    "prepare_abfe_fep",
    "run_abfe_fep",
    "run_abfe_legs",
    "analyze_receptor_pdb_for_vina",
    "prepare_receptor_pdb_for_vina",
    "convert_receptor_pdb_to_pdbqt_for_vina",
}

_HIDDEN_TOOL_NAMES = {"get_skill_content", "list_available_skills"}


@pytest.fixture
def populated_registry():
    """A ToolRegistry populated by scanning CAi.toolkit (mirrors A1pro)."""
    registry = ToolRegistry()
    scanner = ModuleScanner(
        "CAi.toolkit",
        exclude=set(),
        hidden=_HIDDEN_TOOL_NAMES,
    )
    for spec in scanner.scan():
        registry.register(spec)
    return registry


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def test_all_tools_registered(populated_registry):
    names = set(populated_registry.names(include_hidden=False))
    assert names == _EXPECTED_TOOL_NAMES


def test_hidden_tools_registered(populated_registry):
    all_names = set(populated_registry.names(include_hidden=True))
    assert _HIDDEN_TOOL_NAMES <= all_names
    # Hidden tools NOT in visible names
    visible = set(populated_registry.names(include_hidden=False))
    assert not (_HIDDEN_TOOL_NAMES & visible)


def test_tool_signatures(populated_registry):
    """Each tool should have a valid inspect.Signature."""
    for spec in populated_registry.all():
        sig = spec.signature  # e.g. "(smiles: str, num_analogs: int = 10) -> dict"
        assert "(" in sig and ")" in sig, f"Bad signature for {spec.name}: {sig}"
        # Verify it parses
        if sig != "()":
            fn = spec.func
            if fn is not None:
                inspect.signature(fn)  # raises if signature is invalid


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_prompt_rendering_contains_all_tools(populated_registry):
    section = ToolsSection(populated_registry)
    rendered = section.render()
    for name in _EXPECTED_TOOL_NAMES:
        assert name in rendered, f"Tool {name} missing from prompt"


def test_prompt_excludes_hidden_tools(populated_registry):
    section = ToolsSection(populated_registry)
    rendered = section.render()
    for name in _HIDDEN_TOOL_NAMES:
        assert name not in rendered, f"Hidden tool {name} appeared in prompt"


def test_empty_registry_renders_empty():
    registry = ToolRegistry()
    section = ToolsSection(registry)
    assert section.render() == ""


# ---------------------------------------------------------------------------
# Validators — generation wrappers
# ---------------------------------------------------------------------------


class TestScaffoldValidator:
    def test_rejects_no_attachment_point(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_scaffold_analogs

        result = generate_scaffold_analogs("c1ccccc1")
        assert not result["success"]
        assert "attachment point" in result["error"].lower()

    def test_rejects_chiral(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_scaffold_analogs

        result = generate_scaffold_analogs("CC1(C)S[C@@H]2(NC(=O)*)C(=O)N2[C@H]1C(=O)O")
        assert not result["success"]
        assert "@" in result["error"] or "stereochemistry" in result["error"].lower()

    def test_accepts_valid_scaffold(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_scaffold_analogs

        result = generate_scaffold_analogs("c1cc(*)ccc1", num_analogs=3)
        assert result["success"]
        assert "molecules" in result


class TestLibinventValidator:
    def test_rejects_no_attachment(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_libinvent_decorations

        result = generate_libinvent_decorations("c1ccccc1")
        assert not result["success"]

    def test_rejects_chiral(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_libinvent_decorations

        result = generate_libinvent_decorations("CC1(C)S[C@@H]2(NC(=O)[*])C(=O)N2[C@H]1C(=O)O")
        assert not result["success"]

    def test_accepts_valid_scaffold(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_libinvent_decorations

        result = generate_libinvent_decorations("c1cc([*])cc([*:1])c1")
        assert result["success"]


class TestMol2MolValidator:
    def test_rejects_wildcard(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_molecules_reinvent4_mol2mol

        result = generate_molecules_reinvent4_mol2mol("c1cc(*)ccc1")
        assert not result["success"]
        assert "attachment" in result["error"].lower() or "wildcard" in result["error"].lower()

    def test_accepts_complete_molecule(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_molecules_reinvent4_mol2mol

        result = generate_molecules_reinvent4_mol2mol("CC(=O)Oc1ccccc1C(=O)O", num_variants=3)
        assert result["success"]


class TestPocketValidator:
    def test_rejects_missing_pocket(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_molecules_for_pocket

        result = generate_molecules_for_pocket("/tmp/nonexistent.pdb")
        assert not result["success"]

    def test_rejects_missing_center_and_ref_ligand(self, mock_toolkit, tmp_path):
        from CAi.toolkit.functions.generation import generate_molecules_for_pocket

        pdb = tmp_path / "protein.pdb"
        pdb.write_text("ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00  0.00           C")
        result = generate_molecules_for_pocket(str(pdb))
        assert not result["success"]
        assert "pocket" in result["error"].lower() or "center" in result["error"].lower()


class TestDockingValidator:
    def test_rejects_nonexistent_files(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import perform_molecular_docking_vina

        result = perform_molecular_docking_vina(
            "/tmp/no_receptor.pdbqt",
            "/tmp/no_ligand.pdbqt",
            [15.0, 23.0, 6.0],
            [20.0, 20.0, 20.0],
        )
        assert not result["success"]
        assert "does not exist" in result["error"]

    def test_rejects_invalid_center(self, mock_toolkit, tmp_path):
        from CAi.toolkit.functions.evaluation import perform_molecular_docking_vina

        receptor = tmp_path / "receptor.pdbqt"
        ligand = tmp_path / "ligand.pdbqt"
        receptor.write_text("REMARK test")
        ligand.write_text("REMARK test")

        result = perform_molecular_docking_vina(
            str(receptor), str(ligand),
            [15.0],  # only 1 coordinate
            [20.0, 20.0, 20.0],
        )
        assert not result["success"]
        assert "3 values" in result["error"]


# ---------------------------------------------------------------------------
# Validators — evaluation wrappers
# ---------------------------------------------------------------------------


class TestScscoreValidator:
    def test_rejects_empty(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import calculate_scscore

        result = calculate_scscore()
        assert not result["success"]
        assert "must be provided" in result["error"]

    def test_accepts_single_smiles(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import calculate_scscore

        result = calculate_scscore(smiles="CCO")
        # calculate_scscore returns raw run_tool result (no "success" wrapper)
        assert "summary" in result
        assert result["summary"]["total"] == 1


class TestToxicityValidator:
    def test_rejects_scaffold(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import predict_molecule_toxicity

        result = predict_molecule_toxicity("c1cc(*)ccc1")
        assert not result["success"]
        assert "attachment" in result["error"].lower() or "wildcard" in result["error"].lower()

    def test_accepts_complete_molecule(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import predict_molecule_toxicity

        result = predict_molecule_toxicity("CC(=O)Oc1ccccc1C(=O)O")
        assert result["success"]


class TestPmicValidator:
    def test_rejects_empty(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import predict_antibacterial_pmic

        result = predict_antibacterial_pmic("")
        assert not result["success"]

    def test_accepts_complete_molecule(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import predict_antibacterial_pmic

        result = predict_antibacterial_pmic("CC(=O)Nc1ccc(O)cc1")
        assert result["success"]


# ---------------------------------------------------------------------------
# Return schema
# ---------------------------------------------------------------------------


class TestReturnSchema:
    """Verify each wrapper returns a dict with the documented keys."""

    def test_scaffold_schema(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_scaffold_analogs

        result = generate_scaffold_analogs("c1cc(*)ccc1", num_analogs=3)
        assert result["success"] is True
        for key in ("input_scaffold", "requested_batch_size", "generated_count", "molecules"):
            assert key in result, f"Missing key: {key}"

    def test_libinvent_schema(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_libinvent_decorations

        result = generate_libinvent_decorations("c1cc(*)ccc1")
        assert result["success"] is True
        for key in ("input_scaffold", "requested_num_decorations", "generated_count",
                     "csv_columns", "molecules_smiles", "decorated_molecules_preview"):
            assert key in result, f"Missing key: {key}"

    def test_reinvent4_denovo_schema(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_molecules_reinvent4_denovo

        result = generate_molecules_reinvent4_denovo(num_variants=5)
        assert result["success"] is True
        for key in ("mode", "requested_variants", "generated_count", "molecules_smiles"):
            assert key in result, f"Missing key: {key}"
        assert result["mode"] == "de_novo"

    def test_reinvent4_libinvent_schema(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_molecules_reinvent4_libinvent

        result = generate_molecules_reinvent4_libinvent("c1cc(*)ccc1", num_variants=3)
        assert result["success"] is True
        for key in ("mode", "input_scaffold", "requested_variants", "generated_count",
                     "molecules_smiles"):
            assert key in result, f"Missing key: {key}"
        assert result["mode"] == "libinvent"

    def test_reinvent4_mol2mol_schema(self, mock_toolkit):
        from CAi.toolkit.functions.generation import generate_molecules_reinvent4_mol2mol

        result = generate_molecules_reinvent4_mol2mol(
            "CC(=O)Oc1ccccc1C(=O)O", num_variants=3, strategy="beamsearch", temperature=1.0
        )
        assert result["success"] is True
        for key in ("mode", "input_smiles", "strategy", "temperature",
                     "requested_variants", "generated_count", "molecules_smiles"):
            assert key in result, f"Missing key: {key}"
        assert result["mode"] == "mol2mol"

    def test_scscore_schema(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import calculate_scscore

        result = calculate_scscore(smiles_list=["CCO", "CC(=O)O"])
        # calculate_scscore returns raw run_tool result (no "success" wrapper)
        for key in ("summary", "results", "errors"):
            assert key in result, f"Missing key: {key}"
        summary = result["summary"]
        for key in ("total", "successful", "failed", "model", "avg_scscore",
                     "min_scscore", "max_scscore", "median_scscore"):
            assert key in summary, f"Missing summary key: {key}"

    def test_toxicity_schema(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import predict_molecule_toxicity

        result = predict_molecule_toxicity("CC(=O)Oc1ccccc1C(=O)O")
        assert result["success"] is True
        for key in ("verdict", "toxicity_probability", "is_toxic",
                     "structural_explanation", "image_saved_at", "vision_prompt"):
            assert key in result, f"Missing key: {key}"

    def test_pmic_schema(self, mock_toolkit):
        from CAi.toolkit.functions.evaluation import predict_antibacterial_pmic

        result = predict_antibacterial_pmic("CC(=O)Nc1ccc(O)cc1")
        assert result["success"] is True
        for key in ("smiles", "pMIC_value", "estimated_MIC_uM", "interpretation"):
            assert key in result, f"Missing key: {key}"
