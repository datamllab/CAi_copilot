#!/usr/bin/env python3
"""Convert a cleaned receptor PDB into AutoDock Vina PDBQT format.

Params:
    receptor_pdb_path (required): Path to the (cleaned) receptor PDB file.
    output_pdbqt_path:            Path for the output PDBQT.
    allow_bad_res:                Allow problematic residues (default False).
    overwrite:                    Overwrite existing output (default True).
"""
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
from _lib import convert_receptor_pdb_to_pdbqt_tool  # noqa


def main():
    try:
        with open("params.json", "r", encoding="utf-8") as f:
            params = json.load(f)
        params.pop("_action", None)
        if not params.get("output_pdbqt_path") and params.get("receptor_pdb_path"):
            input_name = Path(params["receptor_pdb_path"]).with_suffix(".pdbqt").name
            params["output_pdbqt_path"] = str(Path.cwd() / input_name)
        with redirect_stdout(sys.stderr):
            result = convert_receptor_pdb_to_pdbqt_tool(**params)
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
