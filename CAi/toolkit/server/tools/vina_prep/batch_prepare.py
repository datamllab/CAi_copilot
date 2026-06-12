#!/usr/bin/env python3
"""Batch clean multiple receptor PDB files.

Params:
    receptor_pdb_paths: List of PDB file paths.
    input_dir:          Directory to scan for PDB files.
    pattern:            Glob pattern(s), comma-separated (default '*.pdb').
    output_dir:         Output directory (default: job sandbox).
    (plus all prepare params: chain_policy, keep_resname, etc.)
"""
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))
from _lib import batch_prepare_receptor_pdb_tool  # noqa


def main():
    try:
        with open("params.json", "r", encoding="utf-8") as f:
            params = json.load(f)
        params.pop("_action", None)
        if not params.get("output_dir"):
            params["output_dir"] = str(Path.cwd())
        with redirect_stdout(sys.stderr):
            result = batch_prepare_receptor_pdb_tool(**params)
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
