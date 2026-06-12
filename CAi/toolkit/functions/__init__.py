"""Agent-facing tool functions.

Two submodules:
    generation — molecule generation tools (6)
    evaluation — molecule property / binding evaluation tools (4)

All functions take agent-friendly arguments and return a JSON string so
the REPL can dump the result cleanly.
"""

from .evaluation import (
    analyze_abfe_results,
    analyze_receptor_pdb_for_vina,
    calculate_scscore,
    convert_receptor_pdb_to_pdbqt_for_vina,
    perform_molecular_docking_vina,
    predict_antibacterial_pmic,
    predict_molecule_toxicity,
    prepare_abfe_fep,
    prepare_receptor_pdb_for_vina,
    run_abfe_fep,
    run_abfe_legs,
)
from .generation import (
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
    run_gromacs_md,
)

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
]
