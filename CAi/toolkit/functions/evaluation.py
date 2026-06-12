"""Molecule evaluation tools.

Covers synthesizability (SCScore), toxicity, antibacterial potency (pMIC),
and docking-based binding affinity (AutoDock Vina).
"""

from __future__ import annotations

import base64
import os

from .._validators import valid_center_xyz, valid_complete_molecule_smiles, valid_existing_file
from ..client import run_tool


def calculate_scscore(
    smiles: str | None = None,
    smiles_list: list[str] | None = None,
    model_type: str = "1024bool",
) -> dict:
    """Estimate synthetic accessibility via the SCScore model.

    SCScore ranges roughly 1 (easy) to 5 (very hard to synthesize).

    Args:
        smiles:      Single SMILES string (convenience; turns into a 1-item list).
        smiles_list: Batch of SMILES.
        model_type:  Fingerprint model. Default '1024bool'.

    Returns:
        On success:
          {
            "success": True,
            "summary": {
              "total": int,
              "successful": int,
              "failed": int,
              "model": str,
              "avg_scscore": float,
              "min_scscore": float,
              "max_scscore": float,
              "median_scscore": float,
            },
            "results": [
              {
                "index": int,
                "input_smiles": str,
                "canonical_smiles": str,
                "scscore": float,
                "interpretation": str,
              },
              ...
            ],
            "errors": null | [{...}],
          }
        On error:
          {"success": False, "error": str}
    """
    if smiles:
        smiles_list = [smiles]
    if not smiles_list:
        return {"success": False, "error": "smiles or smiles_list must be provided"}

    return run_tool(
        "scscore",
        {"smiles_list": smiles_list, "model_type": model_type},
    )


def predict_molecule_toxicity(smiles: str) -> dict:
    """Predict hepatotoxicity (HepG2 from toxcast) with SHAP substructure contributions.

    If the server returns a visualization image, it is decoded and saved
    locally as 'latest_toxicity_explanation.png' in the agent workspace.

    Args:
        smiles: Complete molecule SMILES (not a scaffold).

    Returns:
        On success:
          {
            "success": True,
            "verdict": "Toxic" | "Non-Toxic",
            "toxicity_probability": float,        # 0.0 – 1.0
            "is_toxic": bool,                     # probability > 0.5
            "structural_explanation": [
              {"fragment": str, "contribution": float, ...},
              ...
            ],
            "image_saved_at": str | None,         # absolute path to saved PNG
            "vision_prompt": str | None,          # hint to open the image
          }
        On error:
          {"success": False, "error": str}
    """
    if err := valid_complete_molecule_smiles(smiles):
        return {"success": False, "error": err}

    result = run_tool("toxicity", {"smiles": smiles})
    if result.get("error"):
        return {"success": False, "error": result["error"]}

    summary = result.get("summary", {})
    results_data = result.get("results", {})

    agent_response = {
        "success": True,
        "verdict": "Toxic" if summary.get("is_toxic") else "Non-Toxic",
        "toxicity_probability": summary.get("toxicity_probability"),
        "is_toxic": summary.get("is_toxic"),
        "structural_explanation": results_data.get("interpretation", []),
    }

    image_base64 = results_data.get("image_base64")
    if image_base64:
        local_filename = "latest_toxicity_explanation.png"
        with open(local_filename, "wb") as f:
            f.write(base64.b64decode(image_base64))
        agent_response["image_saved_at"] = os.path.abspath(local_filename)
        agent_response["vision_prompt"] = (
            "The structural interpretation image has been saved locally. "
            "Open it to inspect the toxic fragments."
        )
    else:
        agent_response["image_saved_at"] = None
        agent_response["vision_prompt"] = None

    return agent_response


def predict_antibacterial_pmic(smiles: str) -> dict:
    """Predict antibacterial potency of a complete molecule (Chemprop MPNN, pMIC).

    Higher pMIC and lower MIC_uM mean stronger activity. A typical active
    threshold is pMIC > 5.0 (MIC < 10 uM).

    Args:
        smiles: Complete molecule SMILES.

    Returns:
        On success:
          {
            "success": True,
            "smiles": str,                  # input SMILES echoed back
            "pMIC_value": float,            # predicted pMIC
            "estimated_MIC_uM": float,      # MIC in uM = 10^(6 - pMIC)
            "interpretation": str,          # human-readable guidance
          }
        On error:
          {"success": False, "error": str}
    """
    if err := valid_complete_molecule_smiles(smiles):
        return {"success": False, "error": err}

    result = run_tool("pmic", {"smiles": smiles})
    if result.get("error"):
        return {"success": False, "error": result["error"]}

    summary = result.get("summary", {})
    results_data = result.get("results", {})

    return {
        "success": True,
        "smiles": results_data.get("smiles", smiles),
        "pMIC_value": summary.get("pMIC_value"),
        "estimated_MIC_uM": summary.get("estimated_MIC_uM"),
        "interpretation": (
            "Higher pMIC means stronger activity. Typical active threshold: "
            "pMIC > 5.0 (MIC < 10 uM)."
        ),
    }


def perform_molecular_docking_vina(
    receptor_pdbqt_path: str,
    ligand_pdbqt_path: str,
    center_xyz: list,
    box_size_xyz: list,
    exhaustiveness: int = 32,
) -> dict:
    """Dock a ligand into a receptor with AutoDock Vina.

    Accepts receptor / ligand in .pdbqt, .pdb, or .sdf. Non-pdbqt inputs
    are auto-converted by the server.

    Args:
        receptor_pdbqt_path: Path to receptor file.
        ligand_pdbqt_path:   Path to ligand file.
        center_xyz:          Docking box center [x, y, z] in Angstrom.
        box_size_xyz:        Docking box dimensions [x, y, z] in Angstrom.
        exhaustiveness:      Vina exhaustiveness (default 32).

    Returns:
        On success:
          {
            "success": True,
            "best_docking_score_kcal_mol": float | None,   # more negative = stronger binding
            "score_before_minimization_kcal_mol": float,   # initial pose score
            "score_after_minimization_kcal_mol": float,    # after local optimization
            "docked_poses_file_path": str,                 # path to docked poses (.pdbqt)
            "minimized_pose_file_path": str,               # path to minimized pose (.pdbqt)
            "interpretation": str,                         # human-readable guidance
          }
        On error:
          {"success": False, "error": str}
    """
    if err := valid_existing_file(receptor_pdbqt_path, field_name="receptor_pdbqt_path"):
        return {"success": False, "error": err}
    if err := valid_existing_file(ligand_pdbqt_path, field_name="ligand_pdbqt_path"):
        return {"success": False, "error": err}
    if err := valid_center_xyz(center_xyz):
        return {"success": False, "error": err}

    payload = {
        "receptor_file": receptor_pdbqt_path,
        "ligand_file": ligand_pdbqt_path,
        "center": center_xyz,
        "box_size": box_size_xyz,
        "exhaustiveness": exhaustiveness,
        "n_poses": 20,
    }
    result = run_tool("vina", payload, timeout_mins=20)
    if result.get("error"):
        return {"success": False, "error": result["error"]}

    summary = result.get("summary", {})
    results_data = result.get("results", {})

    return {
        "success": True,
        "best_docking_score_kcal_mol": summary.get("best_docking_score"),
        "score_before_minimization_kcal_mol": results_data.get("score_before_minimization"),
        "score_after_minimization_kcal_mol": summary.get("score_after_minimization"),
        "docked_poses_file_path": results_data.get("docked_poses_file"),
        "minimized_pose_file_path": results_data.get("minimized_pose_file"),
        "interpretation": "More negative scores indicate stronger binding affinity.",
    }


def analyze_receptor_pdb_for_vina(
    receptor_pdb_path: str,
    ligand_contact_cutoff: float = 6.0,
) -> dict:
    """Analyze a receptor PDB structure before AutoDock Vina preparation.

    Identifies chains, small-molecule ligands, metals, and water molecules.
    Use this to inspect a PDB before cleaning, or to determine which chains
    are near the binding site.

    Args:
        receptor_pdb_path:     Path to the receptor PDB file (must exist on server).
        ligand_contact_cutoff: Distance cutoff in Angstrom for detecting
                               ligand-contacting chains. Default 6.0.

    Returns:
        On success:
          {
            "success": True,
            "analysis": {
              "input_pdb": str,
              "structure_kind": str,
              "has_small_molecule": bool,
              "small_molecule_resnames": [str, ...],
              "metal_resnames": [str, ...],
              "protein_chains": [str, ...],
              "protein_chain_atom_counts": [[str, int], ...],
              "ligand_contact_chains": [str, ...],
              "recommended_chains": [str, ...],
              "nonstandard_protein_residues": [str, ...],
              "water_atom_count": int,
            },
          }
        On error:
          {"success": False, "error": str}
    """
    if err := valid_existing_file(receptor_pdb_path, field_name="receptor_pdb_path"):
        return {"success": False, "error": err}

    payload = {
        "receptor_pdb_path": receptor_pdb_path,
        "ligand_contact_cutoff": ligand_contact_cutoff,
    }
    return run_tool("vina_prep", payload, action="analyze", timeout_mins=5)


def prepare_receptor_pdb_for_vina(
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
) -> dict:
    """Clean a receptor PDB before AutoDock Vina PDBQT conversion.

    Removes unwanted chains, water molecules, and hetero atoms based on an
    automatic or user-specified strategy. Produces a cleaned PDB and a
    human-readable cleaning report.

    Typical workflow: raw PDB → this function → cleaned PDB → convert to PDBQT.

    Args:
        receptor_pdb_path:     Path to the raw receptor PDB file.
        output_clean_pdb_path: Path for the cleaned output PDB. If None,
                               auto-generated in output_dir.
        output_dir:            Output directory. Default is the job sandbox.
        output_prefix:         Prefix for output file names.
        chains:                Specific chain ID(s) to keep. None = auto.
        chain_policy:          Chain selection policy: 'auto', 'all', 'largest',
                               or 'ligand-contact'. Default 'auto'.
        ligand_contact_cutoff: Distance (Angstrom) for ligand-contact policy.
        keep_resname:          Residue name(s) to always keep.
        remove_resname:        Residue name(s) to always remove.
        keep_water_residue:    Water residue name(s) to keep.
        keep_all_waters:       Keep all water molecules. Default False.
        keep_all_hetero:       Keep all hetero atoms. Default False.
        auto_strategy:         Let the tool choose a sensible cleaning strategy.
        ph:                    pH for protonation state assignment. Default '7.4'.

    Returns:
        On success:
          {
            "success": True,
            "input_receptor_pdb_path": str,
            "cleaned_receptor_pdb_path": str,
            "report_path": str,
            "analysis": {...},
            "strategy": {...},
            "cleaning": {...},
          }
        On error:
          {
            "success": False,
            "input_receptor_pdb_path": str,
            "error": str,
          }
    """
    if err := valid_existing_file(receptor_pdb_path, field_name="receptor_pdb_path"):
        return {"success": False, "error": err}

    payload: dict = {
        "receptor_pdb_path": receptor_pdb_path,
        "chain_policy": chain_policy,
        "ligand_contact_cutoff": ligand_contact_cutoff,
        "keep_all_waters": keep_all_waters,
        "keep_all_hetero": keep_all_hetero,
        "auto_strategy": auto_strategy,
        "ph": ph,
    }
    if output_clean_pdb_path:
        payload["output_clean_pdb_path"] = output_clean_pdb_path
    if output_dir:
        payload["output_dir"] = output_dir
    if output_prefix:
        payload["output_prefix"] = output_prefix
    if chains is not None:
        payload["chains"] = chains
    if keep_resname is not None:
        payload["keep_resname"] = keep_resname
    if remove_resname is not None:
        payload["remove_resname"] = remove_resname
    if keep_water_residue is not None:
        payload["keep_water_residue"] = keep_water_residue

    return run_tool("vina_prep", payload, action="prepare", timeout_mins=10)


def convert_receptor_pdb_to_pdbqt_for_vina(
    receptor_pdb_path: str,
    output_pdbqt_path: str | None = None,
    allow_bad_res: bool = False,
    overwrite: bool = True,
) -> dict:
    """Convert a (cleaned) receptor PDB into AutoDock Vina PDBQT format.

    Uses Meeko to add hydrogens, assign charges, and produce a PDBQT file
    suitable for AutoDock Vina docking.

    This should be called AFTER prepare_receptor_pdb_for_vina() on a cleaned PDB.

    Args:
        receptor_pdb_path: Path to the (cleaned) receptor PDB file.
        output_pdbqt_path: Path for the output PDBQT. If None, auto-generated
                           in the job sandbox.
        allow_bad_res:     Allow problematic residues. Default False.
        overwrite:         Overwrite existing output file. Default True.

    Returns:
        On success:
          {
            "success": True,
            "input_receptor_pdb_path": str,
            "receptor_pdbqt_path": str,
            "allow_bad_res": bool,
            "overwrite": bool,
          }
        On error:
          {
            "success": False,
            "input_receptor_pdb_path": str,
            "error": str,
          }
    """
    if err := valid_existing_file(receptor_pdb_path, field_name="receptor_pdb_path"):
        return {"success": False, "error": err}

    payload: dict = {
        "receptor_pdb_path": receptor_pdb_path,
        "allow_bad_res": allow_bad_res,
        "overwrite": overwrite,
    }
    if output_pdbqt_path:
        payload["output_pdbqt_path"] = output_pdbqt_path

    return run_tool("vina_prep", payload, action="convert", timeout_mins=10)


def run_abfe_fep(
    smiles: str,
    protein: str,
    ligand_id: str = "ligand_000",
    charge: int = 0,
    pocket_center: str | None = None,
    mode: str = "full",
    production_steps: int = 250000,
    gpus: str | None = None,
    box_distance: float = 1.2,
    grompp_maxwarn: int = 3,
    workdir: str | None = None,
    pose_sdf: str | None = None,
    allow_unposed: bool = False,
    allow_missing_protein_atoms: bool = False,
    restraint_correction_kj: float = 0.0,
    standard_state_correction_kj: float = 0.0,
) -> dict:
    """Run a complete absolute binding free energy (ABFE) calculation for a single ligand.

    Full pipeline: prepares inputs (protein cleaning, ligand 3D, ACPYPE topology,
    system boxes, lambda MDP files), runs both complex and solvent legs with
    GROMACS GPU-accelerated MD (18 lambda windows by default), then analyzes
    bar.xvg outputs to compute DG_bind.

    ABFE formula: DG_bind = DG_complex_decouple - DG_solvent_decouple
                  + restraint_correction + standard_state_correction

    This is a long-running GPU calculation (hours per ligand in full mode).
    Use mode='smoke' for a quick 1-window, 1000-step validation run.

    Args:
        smiles:                    SMILES string of the ligand.
        protein:                   Path to the protein PDB file (must exist on server).
        ligand_id:                 Unique identifier (e.g. 'ligand_001'). Default 'ligand_000'.
        charge:                    Formal charge of the ligand. Default 0.
        pocket_center:             Binding pocket center as 'x,y,z' in Angstrom.
                                   If None, auto-detected from HETATM records in the PDB.
        mode:                      'full' (18 windows), 'partial' (subset of windows),
                                   or 'smoke' (1 window, 1000 steps for validation).
        production_steps:          MD steps per lambda window. 250000 = ~500 ps.
        gpus:                      GPU IDs string, e.g. '0' or '0,1'. With 2+ GPUs,
                                   complex and solvent legs run in parallel.
        box_distance:              Distance from solute to box edge in nm. Default 1.2.
        grompp_maxwarn:            Max warnings for gmx grompp. Default 3.
        workdir:                   Output directory. Default is server workspace.
        pose_sdf:                  Optional path to a pre-docked ligand pose SDF.
                                   If None, 3D coords are generated and translated to pocket.
        allow_unposed:             Allow setup without a detected pocket center (smoke tests only).
        allow_missing_protein_atoms: Pass -missing to pdb2gmx (non-production use).
        restraint_correction_kj:   Restraint correction in kJ/mol. Default 0.
        standard_state_correction_kj: Standard-state correction in kJ/mol. Default 0.

    Returns:
        On success:
          {
            "success": True,
            "ligand_id": str,
            "smiles": str,
            "project_dir": str,
            "mode": str,
            "production_steps": int,
            "lambda_windows": int,
            "dg_complex_decouple_kj_mol": float | None,
            "dg_complex_error_kj_mol": float | None,
            "dg_solvent_decouple_kj_mol": float | None,
            "dg_solvent_error_kj_mol": float | None,
            "dg_bind_kj_mol": float | None,         # more negative = stronger binding
            "dg_bind_error_kj_mol": float | None,
            "dg_bind_kcal_mol": float | None,
            "status": "completed" | "incomplete",
            "warning": str,
          }
        On error:
          {"success": False, "error": str}
    """
    payload = {
        "smiles": smiles,
        "protein": protein,
        "ligand_id": ligand_id,
        "charge": charge,
        "mode": mode,
        "production_steps": production_steps,
        "box_distance": box_distance,
        "grompp_maxwarn": grompp_maxwarn,
        "allow_unposed": allow_unposed,
        "allow_missing_protein_atoms": allow_missing_protein_atoms,
        "restraint_correction_kj": restraint_correction_kj,
        "standard_state_correction_kj": standard_state_correction_kj,
    }
    if pocket_center:
        payload["pocket_center"] = pocket_center
    if gpus:
        payload["gpus"] = gpus
    if workdir:
        payload["workdir"] = workdir
    if pose_sdf:
        payload["pose_sdf"] = pose_sdf

    return run_tool("fep", payload, timeout_mins=720)


def prepare_abfe_fep(
    smiles: str,
    protein: str,
    ligand_id: str = "ligand_000",
    charge: int = 0,
    pocket_center: str | None = None,
    mode: str = "full",
    production_steps: int = 250000,
    gpus: str | None = None,
    box_distance: float = 1.2,
    grompp_maxwarn: int = 3,
    workdir: str | None = None,
    pose_sdf: str | None = None,
    allow_unposed: bool = False,
    allow_missing_protein_atoms: bool = False,
) -> dict:
    """Prepare ABFE inputs for a single ligand without running the simulation.

    Generates all GROMACS input files: cleaned protein PDB, ligand 3D coordinates,
    ACPYPE/GAFF2 ligand topology, complex and solvent system boxes, lambda-window
    MDP files (18 windows by default), and run_leg.sh scripts.

    Use this when you want to inspect or modify inputs before running,
    or to prepare multiple ligands and run them later.

    After preparation, call run_abfe_legs(project_dir=...) to execute.

    Args:
        smiles:                    SMILES string of the ligand.
        protein:                   Path to protein PDB file.
        ligand_id:                 Unique identifier. Default 'ligand_000'.
        charge:                    Formal charge. Default 0.
        pocket_center:             'x,y,z' in Angstrom. None = auto-detect from PDB.
        mode:                      'full', 'partial', or 'smoke'.
        production_steps:          Steps per lambda window.
        gpus:                      GPU IDs for the later run step (stored in metadata).
        box_distance:              Box edge distance in nm. Default 1.2.
        grompp_maxwarn:            Max grompp warnings. Default 3.
        workdir:                   Output directory.
        pose_sdf:                  Pre-docked ligand pose SDF path.
        allow_unposed:             Allow without pocket detection.
        allow_missing_protein_atoms: Pass -missing to pdb2gmx.

    Returns:
        On success:
          {
            "success": True,
            "ligand_id": str,
            "project_dir": str,
            "lambda_windows": int,
            "message": str,
          }
        On error:
          {"success": False, "error": str}
    """
    payload = {
        "smiles": smiles,
        "protein": protein,
        "ligand_id": ligand_id,
        "charge": charge,
        "mode": mode,
        "production_steps": production_steps,
        "box_distance": box_distance,
        "grompp_maxwarn": grompp_maxwarn,
        "allow_unposed": allow_unposed,
        "allow_missing_protein_atoms": allow_missing_protein_atoms,
    }
    if pocket_center:
        payload["pocket_center"] = pocket_center
    if gpus:
        payload["gpus"] = gpus
    if workdir:
        payload["workdir"] = workdir
    if pose_sdf:
        payload["pose_sdf"] = pose_sdf

    return run_tool("fep", payload, action="prepare", timeout_mins=30)


def run_abfe_legs(
    project_dir: str,
    gpus: str | None = None,
    parallel_legs: bool | None = None,
) -> dict:
    """Execute prepared ABFE legs (EM, NVT, NPT, production MD, BAR analysis).

    Runs the run_leg.sh scripts in the complex/ and solvent/ subdirectories
    of a project prepared by prepare_abfe_fep().

    With 2+ GPUs, complex and solvent legs run simultaneously.
    With 1 GPU, they run sequentially (complex first, then solvent).

    Args:
        project_dir:    Path to the ligand project directory (from prepare_abfe_fep).
        gpus:           GPU IDs, e.g. '0' or '0,1,2'. With 2+ GPUs, legs run in parallel.
        parallel_legs:  Force parallel or sequential execution. None = auto based on GPU count.

    Returns:
        On success:
          {
            "success": True,
            "project_dir": str,
            "message": str,
          }
        On error:
          {"success": False, "error": str}
    """
    payload = {"project_dir": project_dir}
    if gpus:
        payload["gpus"] = gpus
    if parallel_legs is not None:
        payload["parallel_legs"] = parallel_legs

    return run_tool("fep", payload, action="run", timeout_mins=720)


def analyze_abfe_results(
    search_dir: str | None = None,
    project_dirs: list[str] | None = None,
    restraint_correction_kj: float = 0.0,
    standard_state_correction_kj: float = 0.0,
) -> dict:
    """Analyze completed ABFE calculations and extract binding free energies.

    Scans ligand project directories for bar.xvg files in complex/ and solvent/
    subdirectories, computes DG_bind = DG_complex - DG_solvent + corrections.

    Args:
        search_dir:                 Directory to scan for ligand_*/ subdirectories.
        project_dirs:               Specific ligand project directories to analyze.
        restraint_correction_kj:    Restraint correction in kJ/mol. Default 0.
        standard_state_correction_kj: Standard-state correction in kJ/mol. Default 0.

    Returns:
        On success:
          {
            "success": True,
            "summary": {
              "total": int,
              "completed": int,
              "incomplete": int,
              "min_dg_bind_kj_mol": float,
              "max_dg_bind_kj_mol": float,
              "mean_dg_bind_kj_mol": float,
              "min_dg_bind_kcal_mol": float,
              "max_dg_bind_kcal_mol": float,
              "mean_dg_bind_kcal_mol": float,
            },
            "results": [
              {
                "ligand_id": str,
                "smiles": str,
                "dg_bind_kj_mol": float | None,
                "dg_bind_kcal_mol": float | None,
                "dg_complex_decouple_kj_mol": float | None,
                "dg_solvent_decouple_kj_mol": float | None,
                "status": str,
                ...
              },
              ...
            ],
          }
        On error:
          {"success": False, "error": str}
    """
    payload = {
        "restraint_correction_kj": restraint_correction_kj,
        "standard_state_correction_kj": standard_state_correction_kj,
    }
    if search_dir:
        payload["search_dir"] = search_dir
    if project_dirs:
        payload["project_dirs"] = project_dirs

    return run_tool("fep", payload, action="analyze", timeout_mins=30)

