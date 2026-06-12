"""
CAi Toolkit — drug-discovery tools exposed to the agent.

Layout:
    client.py         HTTP client for the tool server (lower-level)
    functions/        The agent-callable tool functions:
        generation.py   molecule generators (6)
        evaluation.py   molecule evaluators (4)
    skill_helpers.py  get_skill_content / list_available_skills
    server/           FastAPI tool server (separate process)

How to add a new tool:
    1. Put the backend implementation under  toolkit/server/tools/<your_tool>/
       with config.json + run.py (see server/tools/test_tool/README.md).
    2. Add a Python wrapper to  toolkit/functions/generation.py  or  evaluation.py.
       Use `from ..client import run_tool` to call the backend.
    3. Re-export the name below and in functions/__init__.py.
    4. Restart the agent (or call agent.reload_tools()).
"""

from .functions import (
    analyze_abfe_results,
    analyze_receptor_pdb_for_vina,
    calculate_scscore,
    convert_receptor_pdb_to_pdbqt_for_vina,
    deepchem_molgan_generate,
    deepchem_molgan_train,
    deepchem_seq2seq_evaluate,
    deepchem_seq2seq_train,
    drugex_finetune,
    drugex_generate,
    drugex_rl,
    generate_libinvent_decorations,
    generate_molecules_for_pocket,
    generate_molecules_reinvent4_denovo,
    generate_molecules_reinvent4_libinvent,
    generate_molecules_reinvent4_mol2mol,
    generate_molecules_sc2mol,
    generate_scaffold_analogs,
    infer_synthesis_synllama,
    perform_molecular_docking_vina,
    predict_antibacterial_pmic,
    predict_molecule_toxicity,
    prepare_abfe_fep,
    prepare_receptor_pdb_for_vina,
    run_abfe_fep,
    run_abfe_legs,
    run_gromacs_md,
)
from .skill_helpers import get_skill_content, list_available_skills

__all__ = [
    # evaluation
    "analyze_abfe_results",
    "analyze_receptor_pdb_for_vina",
    "calculate_scscore",
    "convert_receptor_pdb_to_pdbqt_for_vina",
    "perform_molecular_docking_vina",
    "predict_antibacterial_pmic",
    "predict_molecule_toxicity",
    "prepare_abfe_fep",
    "prepare_receptor_pdb_for_vina",
    "run_abfe_fep",
    "run_abfe_legs",
    # generation
    "deepchem_molgan_generate",
    "deepchem_molgan_train",
    "deepchem_seq2seq_evaluate",
    "deepchem_seq2seq_train",
    "drugex_finetune",
    "drugex_generate",
    "drugex_rl",
    "generate_libinvent_decorations",
    "generate_molecules_for_pocket",
    "generate_molecules_reinvent4_denovo",
    "generate_molecules_reinvent4_libinvent",
    "generate_molecules_reinvent4_mol2mol",
    "generate_molecules_sc2mol",
    "generate_scaffold_analogs",
    "infer_synthesis_synllama",
    "run_gromacs_md",
    # skill helpers (registered as hidden tools in A1pro)
    "get_skill_content",
    "list_available_skills",
]
