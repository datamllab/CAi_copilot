#!/usr/bin/env python3
"""Analyze a receptor PDB structure before preparation.

Params:
    receptor_pdb_path (required): Path to the receptor PDB file.
    ligand_contact_cutoff:        Distance cutoff in Angstrom (default 6.0).
"""
import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
from _lib import analyze_receptor_pdb_tool  # noqa


def main():
    try:
        with open("params.json", "r", encoding="utf-8") as f:
            params = json.load(f)
        params.pop("_action", None)
        result = analyze_receptor_pdb_tool(**params)
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
