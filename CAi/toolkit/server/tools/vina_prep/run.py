#!/usr/bin/env python3
"""Default action: clean a receptor PDB for AutoDock Vina.

Params:
    receptor_pdb_path (required): Path to the raw receptor PDB file.
    output_clean_pdb_path:        Path for the cleaned output PDB.
    output_dir:                   Output directory (default: job sandbox).
    output_prefix:                Prefix for output file names.
    chains:                       Chain ID(s) to keep.
    chain_policy:                 'auto', 'all', 'largest', 'ligand-contact'.
    ligand_contact_cutoff:        Distance cutoff in Angstrom.
    keep_resname:                 Residue name(s) to always keep.
    remove_resname:               Residue name(s) to always remove.
    keep_water_residue:           Water residue name(s) to keep.
    keep_all_waters:              Keep all water molecules.
    keep_all_hetero:              Keep all hetero atoms.
    auto_strategy:                Let the tool choose a sensible strategy.
    ph:                           pH for protonation state assignment.
"""
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
from _lib import prepare_receptor_pdb_tool  # noqa


def main():
    try:
        with open("params.json", "r", encoding="utf-8") as f:
            params = json.load(f)
        params.pop("_action", None)
        if not params.get("output_clean_pdb_path") and not params.get("output_dir"):
            params["output_dir"] = str(Path.cwd())
        with redirect_stdout(sys.stderr):
            result = prepare_receptor_pdb_tool(**params)
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
