#!/usr/bin/env python3
"""Core library for AutoDock Vina receptor preparation.

Provides structure analysis, PDB cleaning, and PDBQT conversion.
Imported by the action scripts (run.py, analyze.py, etc.).
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WATER_NAMES = {"HOH", "WAT", "H2O", "DOD"}
COMMON_SALTS = {
    "CL", "BR", "IOD", "NA", "K", "CS", "LI", "RB", "CA", "MG", "MN",
    "SO4", "PO4", "NO3", "ACT", "ACE", "EDO", "GOL",
}
METALS = {
    "ZN", "MG", "MN", "FE", "FE2", "CU", "CO", "CA", "NI", "CD", "NA", "K",
}
STANDARD_RESIDUES = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY",
    "HIS", "HID", "HIE", "HIP", "ILE", "LEU", "LYS", "MET",
    "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL", "SEC", "PYL",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class AtomRecord:
    raw: str
    record: str
    serial: int
    atom_name: str
    altloc: str
    resname: str
    chain: str
    resseq: str
    icode: str
    x: float
    y: float
    z: float
    occupancy: float
    element: str

    @property
    def residue_key(self) -> tuple[str, str, str, str]:
        return (self.chain, self.resseq, self.icode, self.resname)


@dataclasses.dataclass(frozen=True)
class StructureAnalysis:
    input_pdb: str
    structure_kind: str
    has_small_molecule: bool
    small_molecule_resnames: tuple[str, ...]
    metal_resnames: tuple[str, ...]
    protein_chains: tuple[str, ...]
    protein_chain_atom_counts: tuple[tuple[str, int], ...]
    ligand_contact_chains: tuple[str, ...]
    recommended_chains: tuple[str, ...]
    nonstandard_protein_residues: tuple[str, ...]
    water_atom_count: int


# ---------------------------------------------------------------------------
# PDB parsing helpers
# ---------------------------------------------------------------------------

def parse_atom_line(line: str) -> AtomRecord:
    return AtomRecord(
        raw=line.rstrip("\n"),
        record=line[0:6].strip(),
        serial=int(line[6:11]),
        atom_name=line[12:16].strip(),
        altloc=line[16:17].strip(),
        resname=line[17:20].strip(),
        chain=line[21:22].strip(),
        resseq=line[22:26].strip(),
        icode=line[26:27].strip(),
        x=float(line[30:38]),
        y=float(line[38:46]),
        z=float(line[46:54]),
        occupancy=float(line[54:60] or 0.0),
        element=line[76:78].strip().upper() if len(line) >= 78 else "",
    )


def format_atom_line(atom: AtomRecord, serial: int | None = None) -> str:
    raw = atom.raw
    if len(raw) < 80:
        raw = raw.ljust(80)
    serial_text = f"{serial if serial is not None else atom.serial:5d}"
    return f"{raw[:6]}{serial_text}{raw[11:16]} {raw[17:]}"


def read_pdb(path: Path) -> tuple[list[str], list[AtomRecord], list[str]]:
    header: list[str] = []
    atoms: list[AtomRecord] = []
    tail: list[str] = []
    seen_atoms = False
    for line in path.read_text().splitlines():
        record = line[0:6].strip()
        if record in {"ATOM", "HETATM"}:
            seen_atoms = True
            atoms.append(parse_atom_line(line))
        elif not seen_atoms:
            header.append(line)
        elif record not in {"CONECT", "MASTER", "END"}:
            tail.append(line)
    return header, atoms, tail


def parse_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def choose_altlocs(atoms: Iterable[AtomRecord]) -> list[AtomRecord]:
    grouped: dict[tuple[str, str, str, str, str], AtomRecord] = {}
    for atom in atoms:
        key = (*atom.residue_key, atom.atom_name)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = atom
            continue
        existing_rank = (existing.altloc in {"", "A"}, existing.occupancy)
        atom_rank = (atom.altloc in {"", "A"}, atom.occupancy)
        if atom_rank > existing_rank:
            grouped[key] = atom
    return list(grouped.values())


def residue_id(atom: AtomRecord) -> str:
    return f"{atom.chain}:{atom.resname}{atom.resseq}{atom.icode}".upper()


def atom_distance2(left: AtomRecord, right: AtomRecord) -> float:
    return (
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )


# ---------------------------------------------------------------------------
# Structure analysis
# ---------------------------------------------------------------------------

def analyze_structure_file(pdb: Path, ligand_contact_cutoff: float = 6.0) -> StructureAnalysis:
    _header, atoms, _tail = read_pdb(pdb)
    atoms = choose_altlocs(atoms)

    protein_chain_counts: dict[str, int] = {}
    protein_atoms_by_chain: dict[str, list[AtomRecord]] = {}
    small_molecule_atoms: list[AtomRecord] = []
    small_molecule_resnames: set[str] = set()
    metal_resnames: set[str] = set()
    nonstandard_protein_residues: set[str] = set()
    water_atom_count = 0

    for atom in atoms:
        resname = atom.resname.upper()
        if atom.record == "ATOM":
            chain = atom.chain.upper() or "_"
            protein_chain_counts[chain] = protein_chain_counts.get(chain, 0) + 1
            protein_atoms_by_chain.setdefault(chain, []).append(atom)
            if resname not in STANDARD_RESIDUES:
                nonstandard_protein_residues.add(residue_id(atom))
            continue

        if resname in WATER_NAMES:
            water_atom_count += 1
        elif resname in METALS:
            metal_resnames.add(resname)
        elif resname not in COMMON_SALTS:
            small_molecule_resnames.add(resname)
            small_molecule_atoms.append(atom)

    cutoff2 = ligand_contact_cutoff * ligand_contact_cutoff
    ligand_contact_chains = set()
    if small_molecule_atoms:
        for chain, chain_atoms in protein_atoms_by_chain.items():
            if any(
                atom_distance2(protein_atom, ligand_atom) <= cutoff2
                for protein_atom in chain_atoms
                for ligand_atom in small_molecule_atoms
            ):
                ligand_contact_chains.add(chain)

    largest_chain = ""
    if protein_chain_counts:
        largest_chain = max(protein_chain_counts.items(), key=lambda item: item[1])[0]
    recommended_chains = ligand_contact_chains or ({largest_chain} if largest_chain else set())
    structure_kind = "complex" if small_molecule_resnames else "apo"
    return StructureAnalysis(
        input_pdb=str(pdb),
        structure_kind=structure_kind,
        has_small_molecule=bool(small_molecule_resnames),
        small_molecule_resnames=tuple(sorted(small_molecule_resnames)),
        metal_resnames=tuple(sorted(metal_resnames)),
        protein_chains=tuple(sorted(protein_chain_counts)),
        protein_chain_atom_counts=tuple(sorted(protein_chain_counts.items())),
        ligand_contact_chains=tuple(sorted(ligand_contact_chains)),
        recommended_chains=tuple(sorted(recommended_chains)),
        nonstandard_protein_residues=tuple(sorted(nonstandard_protein_residues)),
        water_atom_count=water_atom_count,
    )


# ---------------------------------------------------------------------------
# Processing strategy
# ---------------------------------------------------------------------------

def decide_processing_strategy(
    analysis: StructureAnalysis,
    keep_resnames: set[str] | None = None,
    remove_resnames: set[str] | None = None,
    requested_chains: set[str] | None = None,
    chain_policy: str = "auto",
) -> dict[str, object]:
    keep_resnames = keep_resnames or set()
    remove_resnames = remove_resnames or set()
    requested_chains = requested_chains or set()

    strategy_name = "apo_default"
    auto_remove_resnames: set[str] = set(remove_resnames)
    notes: list[str] = []
    selected_chains: set[str] = set(requested_chains)

    if analysis.has_small_molecule:
        strategy_name = "complex_strip_small_molecule"
        for resname in analysis.small_molecule_resnames:
            if resname not in keep_resnames:
                auto_remove_resnames.add(resname)
        notes.append(
            "Detected bound small molecules; removing them during receptor "
            "preparation unless explicitly kept."
        )

    if analysis.nonstandard_protein_residues:
        notes.append(
            "Detected non-standard protein residues; receptor PDBQT conversion "
            "may require allow_bad_res."
        )

    if analysis.metal_resnames:
        notes.append("Detected metal ions; these are kept by default.")

    if not selected_chains:
        if chain_policy == "all":
            selected_chains = set(analysis.protein_chains)
        elif chain_policy == "largest":
            selected_chains = (
                {max(analysis.protein_chain_atom_counts, key=lambda item: item[1])[0]}
                if analysis.protein_chain_atom_counts
                else set()
            )
        elif chain_policy == "ligand-contact":
            selected_chains = set(analysis.ligand_contact_chains)
        elif chain_policy == "auto":
            selected_chains = set(analysis.recommended_chains)
        else:
            raise ValueError(f"Unsupported chain policy: {chain_policy}")

    if selected_chains and len(analysis.protein_chains) > 1:
        notes.append(
            "Selected protein chains for receptor preparation: "
            + ",".join(sorted(selected_chains))
        )

    return {
        "strategy_name": strategy_name,
        "remove_resnames": auto_remove_resnames,
        "selected_chains": selected_chains,
        "chain_policy": chain_policy,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# PDB cleaning
# ---------------------------------------------------------------------------

def clean_receptor_file(
    pdb: Path,
    out: Path,
    chains: set[str] | None = None,
    keep_resnames: set[str] | None = None,
    remove_resnames: set[str] | None = None,
    keep_waters: set[str] | None = None,
    keep_all_waters: bool = False,
    keep_all_hetero: bool = False,
    ph: str | None = None,
) -> dict[str, object]:
    chains = chains or set()
    keep_resnames = keep_resnames or set()
    remove_resnames = (remove_resnames or set()) | COMMON_SALTS
    keep_waters = keep_waters or set()
    header, atoms, _tail = read_pdb(pdb)
    atoms = choose_altlocs(atoms)

    kept: list[AtomRecord] = []
    removed_counts: dict[str, int] = {}
    warnings: list[str] = []
    removed_unknown_hetero: set[str] = set()

    for atom in atoms:
        if chains and atom.chain.upper() not in chains:
            removed_counts["chain_filtered"] = removed_counts.get("chain_filtered", 0) + 1
            continue

        res_id = f"{atom.chain}:{atom.resname}{atom.resseq}{atom.icode}".upper()
        resname = atom.resname.upper()

        if resname in WATER_NAMES:
            if keep_all_waters or res_id in keep_waters:
                kept.append(atom)
            else:
                removed_counts["water"] = removed_counts.get("water", 0) + 1
            continue

        if resname in remove_resnames and resname not in keep_resnames:
            removed_counts["salt_or_buffer"] = removed_counts.get("salt_or_buffer", 0) + 1
            continue

        if atom.record == "HETATM":
            if keep_all_hetero or resname in keep_resnames or resname in METALS:
                kept.append(atom)
            else:
                removed_counts["hetero"] = removed_counts.get("hetero", 0) + 1
                removed_unknown_hetero.add(resname)
            continue

        kept.append(atom)

    residues = {atom.residue_key for atom in kept if atom.record == "ATOM"}
    het_residues = {atom.residue_key for atom in kept if atom.record == "HETATM"}
    for residue in sorted(het_residues):
        if residue[3].upper() not in METALS and residue[3].upper() not in keep_resnames:
            warnings.append(f"Kept HETATM residue {residue}; verify atom types and charges.")

    for residue in sorted(residues):
        resname = residue[3].upper()
        if resname not in STANDARD_RESIDUES:
            warnings.append(f"Non-standard protein residue {residue}; inspect before docking.")

    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [line for line in header if not line.startswith(("CONECT", "MASTER"))]
    lines.append("REMARK Cleaned for AutoDock Vina receptor preparation")
    if ph:
        lines.append(f"REMARK Intended protonation pH: {ph}")
    for index, atom in enumerate(kept, start=1):
        lines.append(format_atom_line(atom, index))
    lines.append("END")
    out.write_text("\n".join(lines) + "\n")

    report = out.with_suffix(".report.txt")
    report_lines = [
        f"input: {pdb}",
        f"cleaned_pdb: {out}",
        f"kept_atoms: {len(kept)}",
        "removed:",
    ]
    for key in sorted(removed_counts):
        report_lines.append(f"  {key}: {removed_counts[key]}")
    if removed_unknown_hetero:
        report_lines.append("removed_unknown_hetero:")
        report_lines.extend(f"  - {resname}" for resname in sorted(removed_unknown_hetero))
    if warnings:
        report_lines.append("warnings:")
        report_lines.extend(f"  - {warning}" for warning in warnings)
    else:
        report_lines.append("warnings: none")
    report.write_text("\n".join(report_lines) + "\n")

    return {
        "input": str(pdb),
        "cleaned_pdb": str(out),
        "report": str(report),
        "removed_counts": removed_counts,
        "removed_unknown_hetero": sorted(removed_unknown_hetero),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# PDB → PDBQT conversion (Meeko)
# ---------------------------------------------------------------------------

def pdbqt_trans(
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    allow_bad_res: bool = False,
    overwrite: bool = False,
) -> str:
    """Convert a receptor PDB file into a Vina-compatible PDBQT via Meeko."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Receptor file not found: {input_path}")

    if input_path.suffix.lower() == ".pdbqt":
        return str(input_path)

    if input_path.suffix.lower() != ".pdb":
        raise ValueError(f"Unsupported receptor format: {input_path}")

    output = Path(output_path) if output_path else input_path.with_suffix(".pdbqt")
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists() and output.stat().st_size > 0 and not overwrite:
        return str(output)

    command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "from rdkit.Chem import rdchem; "
            "rdchem.Mol.HasQuery = lambda self: False; "
            "from meeko.cli.mk_prepare_receptor import main; "
            f"sys.argv = ['mk_prepare_receptor.py', '--read_pdb', {str(input_path)!r}, "
            f"'-p', {str(output)!r}"
            + (", '-a'" if allow_bad_res else "")
            + "]; "
            "sys.exit(main())"
        ),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Receptor PDB→PDBQT conversion failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"Receptor PDBQT generation failed: {output}")

    return str(output)


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------

def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _csv_or_list(value: str | list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return parse_csv(value)
    return {item.strip().upper() for item in value if item and item.strip()}


# ---------------------------------------------------------------------------
# Tool-level functions (called by action scripts)
# ---------------------------------------------------------------------------

def analyze_receptor_pdb_tool(
    receptor_pdb_path: str,
    ligand_contact_cutoff: float = 6.0,
) -> dict[str, Any]:
    """Analyze receptor PDB structure before preparation."""
    try:
        analysis = analyze_structure_file(
            Path(receptor_pdb_path),
            ligand_contact_cutoff=ligand_contact_cutoff,
        )
        return {"success": True, "analysis": _jsonable(analysis)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def prepare_receptor_pdb_tool(
    receptor_pdb_path: str,
    output_clean_pdb_path: str | None = None,
    output_dir: str | None = None,
    output_prefix: str | None = None,
    chains: str | list[str] | None = None,
    chain_policy: str = "auto",
    ligand_contact_cutoff: float = 6.0,
    keep_resname: str | list[str] | None = None,
    remove_resname: str | list[str] | None = None,
    keep_water_residue: str | list[str] | None = None,
    keep_all_waters: bool = False,
    keep_all_hetero: bool = False,
    auto_strategy: bool = True,
    ph: str = "7.4",
) -> dict[str, Any]:
    """Clean receptor PDB and select receptor chains."""
    try:
        receptor_pdb = Path(receptor_pdb_path)
        if output_clean_pdb_path:
            clean_pdb = Path(output_clean_pdb_path)
        else:
            out_dir = Path(output_dir) if output_dir else receptor_pdb.parent
            prefix = output_prefix or receptor_pdb.stem
            clean_pdb = out_dir / f"{prefix}_clean.pdb"

        keep_resnames = _csv_or_list(keep_resname)
        remove_resnames = _csv_or_list(remove_resname)
        requested_chains = _csv_or_list(chains)
        analysis = analyze_structure_file(
            receptor_pdb, ligand_contact_cutoff=ligand_contact_cutoff,
        )
        if auto_strategy:
            strategy = decide_processing_strategy(
                analysis,
                keep_resnames=keep_resnames,
                remove_resnames=remove_resnames,
                requested_chains=requested_chains,
                chain_policy=chain_policy,
            )
        else:
            strategy = {
                "strategy_name": "manual",
                "remove_resnames": remove_resnames,
                "selected_chains": requested_chains,
                "chain_policy": "manual",
                "notes": [],
            }

        clean_result = clean_receptor_file(
            pdb=receptor_pdb,
            out=clean_pdb,
            chains=strategy["selected_chains"],
            keep_resnames=keep_resnames,
            remove_resnames=strategy["remove_resnames"],
            keep_waters=_csv_or_list(keep_water_residue),
            keep_all_waters=keep_all_waters,
            keep_all_hetero=keep_all_hetero,
            ph=ph,
        )
        return {
            "success": True,
            "input_receptor_pdb_path": str(receptor_pdb),
            "cleaned_receptor_pdb_path": str(clean_pdb),
            "report_path": clean_result["report"],
            "analysis": _jsonable(analysis),
            "strategy": _jsonable(strategy),
            "cleaning": _jsonable(clean_result),
        }
    except Exception as exc:
        return {
            "success": False,
            "input_receptor_pdb_path": receptor_pdb_path,
            "error": str(exc),
        }


def batch_prepare_receptor_pdb_tool(
    receptor_pdb_paths: list[str] | None = None,
    input_dir: str | None = None,
    pattern: str = "*.pdb",
    output_dir: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Batch clean receptor PDB files."""
    try:
        paths: list[Path] = []
        if receptor_pdb_paths:
            paths.extend(Path(p) for p in receptor_pdb_paths)
        if input_dir:
            for item in [part.strip() for part in pattern.split(",") if part.strip()]:
                paths.extend(sorted(Path(input_dir).glob(item)))
        paths = sorted(dict.fromkeys(paths))
        if not paths:
            return {"success": False, "error": "No receptor PDB files were provided or found."}

        results = []
        for pdb_path in paths:
            results.append(
                prepare_receptor_pdb_tool(
                    receptor_pdb_path=str(pdb_path),
                    output_dir=output_dir,
                    output_prefix=pdb_path.stem,
                    **kwargs,
                )
            )
        return {
            "success": all(r.get("success") for r in results),
            "results": results,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def convert_receptor_pdb_to_pdbqt_tool(
    receptor_pdb_path: str,
    output_pdbqt_path: str | None = None,
    allow_bad_res: bool = False,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Convert a cleaned receptor PDB into Vina-compatible PDBQT."""
    try:
        pdbqt_path = pdbqt_trans(
            input_path=receptor_pdb_path,
            output_path=output_pdbqt_path,
            allow_bad_res=allow_bad_res,
            overwrite=overwrite,
        )
        return {
            "success": True,
            "input_receptor_pdb_path": receptor_pdb_path,
            "receptor_pdbqt_path": pdbqt_path,
            "allow_bad_res": allow_bad_res,
            "overwrite": overwrite,
        }
    except Exception as exc:
        return {
            "success": False,
            "input_receptor_pdb_path": receptor_pdb_path,
            "error": str(exc),
        }
