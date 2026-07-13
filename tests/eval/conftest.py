"""Shared fixtures for the evaluation test suite.

Provides:
- `mock_toolkit`: stubs run_tool() at module level (fast, non-REPL tests)
- `real_llm_agent`: A1pro with real LLM + kernel-injected mock toolkit
- `real_llm_agent_no_utilities`: same but without utilities (baseline)

REPL subprocess mock strategy:
    The Jupyter kernel is a separate process. Monkeypatching in the parent
    doesn't affect it. Instead, we inject mock `run_tool` functions into
    the kernel via `_execute_in_kernel()` (raw code execution) and use a
    temp file for call_log communication between subprocess and parent.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Mock tool response builders (same as before — used for non-REPL tests)
# ---------------------------------------------------------------------------

_FAKE_SCAFFOLD_ANALOGS = [
    "CCOc1cc(*)ccc1",
    "c1cc(CCO)cc(*)c1",
    "CC(C)Oc1cc(*)ccc1",
    "c1cc(OCC(*)cc1)CCO",
    "CCOc1cc(C)cc(*)c1",
]

_FAKE_LIBINVENT_SMILES = [
    "CCOc1ccc(CCO)cc1",
    "c1cc(CCO)ccc1OCC",
    "CC(C)Oc1ccc(C)cc1",
]

_FAKE_DENOVO_SMILES = [
    "CCOC(=O)c1ccccc1",
    "CCN(CC)CC(=O)Nc1ccc(O)cc1",
    "COc1ccc(C(=O)NCCN)cc1",
    "CC(C)(C)NCC(O)c1ccc(O)c(O)c1",
    "CCOC(=O)Nc1ccc(C(=O)O)cc1",
    "CCN1CCCC1C(=O)Nc1ccccc1",
    "c1ccc2c(c1)CCNC2=O",
    "CCOC(=O)c1cnc(N)nc1N",
    "COc1cc(CCN(C)C)ccc1",
    "CC(C)CC(=O)Nc1ccc(Cl)cc1",
]

_FAKE_MOL2MOL_SMILES = [
    "CCOc1ccc(NC(=O)c2ccc(O)cc2)cc1",
    "CCNc1ccc(NC(=O)c2ccccc2)cc1",
    "COc1ccc(NC(=O)c2ccc(Cl)cc2)cc1",
]


def _mock_scaffold(payload: dict) -> dict:
    n = min(payload.get("num_analogs", 5), len(_FAKE_SCAFFOLD_ANALOGS))
    results = [{"smiles": s} for s in _FAKE_SCAFFOLD_ANALOGS[:n]]
    return {
        "summary": {
            "input_scaffold": payload.get("smiles", ""),
            "requested_batch_size": payload.get("num_analogs", 10),
            "valid_unique_generated": n,
        },
        "results": results,
    }


def _mock_libinvent(payload: dict) -> dict:
    n = min(
        payload.get("number_of_decorations_per_scaffold", 3),
        len(_FAKE_LIBINVENT_SMILES),
    )
    rows = [{"SMILES": s, "status": "ok", "message": ""} for s in _FAKE_LIBINVENT_SMILES[:n]]
    return {
        "summary": {
            "row_count": n,
            "columns": ["SMILES", "status", "message"],
            "preview": rows[:3],
        },
        "results": rows,
    }


def _mock_rxnflow(payload: dict) -> dict:
    n = min(payload.get("num_samples", 10), len(_FAKE_DENOVO_SMILES))
    preview = [
        {"smiles": s, "qed": round(0.4 + i * 0.05, 3), "proxy_score": round(-5.0 - i * 0.3, 2)}
        for i, s in enumerate(_FAKE_DENOVO_SMILES[:n])
    ]
    return {
        "summary": {
            "generated_count": n,
            "sampling_time_sec": 12.5,
            "output_file": "/tmp/rxnflow_results.csv",
        },
        "results": {"generated_preview": preview},
    }


def _mock_reinvent4(payload: dict, action: str = "default") -> dict:
    if action == "de_novo":
        n = min(payload.get("num_variants", 10), len(_FAKE_DENOVO_SMILES))
        mols = [{"smiles": s} for s in _FAKE_DENOVO_SMILES[:n]]
        return {
            "summary": {"generated_count": n},
            "results": {"molecules": mols},
        }
    if action == "libinvent":
        n = min(payload.get("num_variants", 5), len(_FAKE_LIBINVENT_SMILES))
        mols = [{"smiles": s} for s in _FAKE_LIBINVENT_SMILES[:n]]
        return {
            "summary": {"generated_count": n},
            "results": {"molecules": mols},
        }
    if action == "mol2mol":
        n = min(payload.get("num_variants", 5), len(_FAKE_MOL2MOL_SMILES))
        mols = [{"smiles": s} for s in _FAKE_MOL2MOL_SMILES[:n]]
        return {
            "summary": {"generated_count": n},
            "results": {"molecules": mols},
        }
    return {"error": f"Unknown reinvent4 action: {action}"}


def _mock_scscore(payload: dict) -> dict:
    smiles_list = payload.get("smiles_list", [])
    results = []
    scores = []
    for i, smi in enumerate(smiles_list):
        score = round(1.5 + i * 0.6, 2)
        scores.append(score)
        results.append({
            "index": i,
            "input_smiles": smi,
            "canonical_smiles": smi,
            "scscore": score,
            "interpretation": "Easy to synthesize" if score < 3 else "Moderate difficulty",
        })
    avg_score = sum(scores) / len(scores) if scores else 0
    return {
        "summary": {
            "total": len(smiles_list),
            "successful": len(smiles_list),
            "failed": 0,
            "model": payload.get("model_type", "1024bool"),
            "avg_scscore": round(avg_score, 2),
            "min_scscore": min(scores) if scores else 0,
            "max_scscore": max(scores) if scores else 0,
            "median_scscore": sorted(scores)[len(scores) // 2] if scores else 0,
        },
        "results": results,
        "errors": None,
    }


def _mock_toxicity(payload: dict) -> dict:
    smi = payload.get("smiles", "")
    is_toxic = "Cl" in smi or "Br" in smi
    prob = round(0.85 if is_toxic else 0.25, 3)
    return {
        "summary": {
            "is_toxic": is_toxic,
            "toxicity_probability": prob,
        },
        "results": {
            "interpretation": [
                {"fragment": "aromatic_ring", "contribution": 0.15},
                {"fragment": "halogen", "contribution": 0.35 if is_toxic else -0.05},
            ],
            "image_base64": None,
        },
    }


def _mock_pmic(payload: dict) -> dict:
    smi = payload.get("smiles", "")
    pmic = round(4.5 + len(smi) * 0.02, 2)
    mic_um = round(10 ** (6 - pmic), 2)
    return {
        "summary": {
            "pMIC_value": pmic,
            "estimated_MIC_uM": mic_um,
        },
        "results": {
            "smiles": smi,
        },
    }


def _mock_vina(payload: dict) -> dict:
    best = round(-7.5 - len(payload.get("ligand_file", "")) * 0.01, 2)
    return {
        "summary": {
            "best_docking_score": best,
            "score_after_minimization": round(best - 0.3, 2),
        },
        "results": {
            "score_before_minimization": round(best + 0.5, 2),
            "docked_poses_file": "/tmp/docked_poses.pdbqt",
            "minimized_pose_file": "/tmp/minimized_pose.pdbqt",
        },
    }


TOOL_RESPONSES = {
    "scaffold": _mock_scaffold,
    "libinvent": _mock_libinvent,
    "rxnflow": _mock_rxnflow,
    "reinvent4": _mock_reinvent4,
    "scscore": _mock_scscore,
    "toxicity": _mock_toxicity,
    "pmic": _mock_pmic,
    "vina": _mock_vina,
}


# ---------------------------------------------------------------------------
# Kernel-side mock injection
# ---------------------------------------------------------------------------
# Generates Python source code that, when executed in the kernel subprocess,
# patches run_tool in both generation and evaluation modules.
# Call log is written to a temp file for cross-process communication.


def _generate_kernel_mock_source(call_log_path: str) -> str:
    """Generate source code to inject into the kernel subprocess.

    The code:
    1. Defines mock response builders (same logic as parent process)
    2. Defines a fake_run_tool that logs calls and returns mock data
    3. Patches generation.run_tool and evaluation.run_tool
    """
    return f'''
# ---- Eval mock: patch run_tool in kernel subprocess ----
import json as _json, os as _os

_EVAL_CALL_LOG_PATH = {call_log_path!r}

_FAKE_SCAFFOLD_ANALOGS = {repr(_FAKE_SCAFFOLD_ANALOGS)}
_FAKE_LIBINVENT_SMILES = {repr(_FAKE_LIBINVENT_SMILES)}
_FAKE_DENOVO_SMILES = {repr(_FAKE_DENOVO_SMILES)}
_FAKE_MOL2MOL_SMILES = {repr(_FAKE_MOL2MOL_SMILES)}

def _eval_mock_run_tool(tool, payload, *, action="default", **kwargs):
    """Mock run_tool for eval — logs to file and returns fake data."""
    # Log call
    _log = {{"tool": tool, "action": action, "payload": dict(payload)}}
    try:
        with open(_EVAL_CALL_LOG_PATH, "a") as _f:
            _f.write(_json.dumps(_log, ensure_ascii=False) + "\\n")
    except Exception:
        pass

    def _mock_scaffold(p):
        n = min(p.get("num_analogs", 5), len(_FAKE_SCAFFOLD_ANALOGS))
        return {{"summary": {{"input_scaffold": p.get("smiles", ""), "requested_batch_size": p.get("num_analogs", 10), "valid_unique_generated": n}}, "results": [{{"smiles": s}} for s in _FAKE_SCAFFOLD_ANALOGS[:n]]}}

    def _mock_libinvent(p):
        n = min(p.get("number_of_decorations_per_scaffold", 3), len(_FAKE_LIBINVENT_SMILES))
        rows = [{{"SMILES": s, "status": "ok", "message": ""}} for s in _FAKE_LIBINVENT_SMILES[:n]]
        return {{"summary": {{"row_count": n, "columns": ["SMILES", "status", "message"], "preview": rows[:3]}}, "results": rows}}

    def _mock_rxnflow(p):
        n = min(p.get("num_samples", 10), len(_FAKE_DENOVO_SMILES))
        preview = [{{"smiles": s, "qed": round(0.4 + i * 0.05, 3), "proxy_score": round(-5.0 - i * 0.3, 2)}} for i, s in enumerate(_FAKE_DENOVO_SMILES[:n])]
        return {{"summary": {{"generated_count": n, "sampling_time_sec": 12.5, "output_file": "/tmp/rxnflow_results.csv"}}, "results": {{"generated_preview": preview}}}}

    def _mock_reinvent4(p, action="default"):
        if action == "de_novo":
            n = min(p.get("num_variants", 10), len(_FAKE_DENOVO_SMILES))
            return {{"summary": {{"generated_count": n}}, "results": {{"molecules": [{{"smiles": s}} for s in _FAKE_DENOVO_SMILES[:n]]}}}}
        if action == "libinvent":
            n = min(p.get("num_variants", 5), len(_FAKE_LIBINVENT_SMILES))
            return {{"summary": {{"generated_count": n}}, "results": {{"molecules": [{{"smiles": s}} for s in _FAKE_LIBINVENT_SMILES[:n]]}}}}
        if action == "mol2mol":
            n = min(p.get("num_variants", 5), len(_FAKE_MOL2MOL_SMILES))
            return {{"summary": {{"generated_count": n}}, "results": {{"molecules": [{{"smiles": s}} for s in _FAKE_MOL2MOL_SMILES[:n]]}}}}
        return {{"error": f"Unknown reinvent4 action: {{action}}"}}

    def _mock_scscore(p):
        smiles_list = p.get("smiles_list", [])
        scores = [round(1.5 + i * 0.6, 2) for i in range(len(smiles_list))]
        results = [{{"index": i, "input_smiles": s, "canonical_smiles": s, "scscore": sc, "interpretation": "Easy to synthesize" if sc < 3 else "Moderate difficulty"}} for i, (s, sc) in enumerate(zip(smiles_list, scores))]
        avg = sum(scores) / len(scores) if scores else 0
        return {{"summary": {{"total": len(smiles_list), "successful": len(smiles_list), "failed": 0, "model": p.get("model_type", "1024bool"), "avg_scscore": round(avg, 2), "min_scscore": min(scores) if scores else 0, "max_scscore": max(scores) if scores else 0, "median_scscore": sorted(scores)[len(scores) // 2] if scores else 0}}, "results": results, "errors": None}}

    def _mock_toxicity(p):
        smi = p.get("smiles", "")
        is_toxic = "Cl" in smi or "Br" in smi
        prob = round(0.85 if is_toxic else 0.25, 3)
        return {{"summary": {{"is_toxic": is_toxic, "toxicity_probability": prob}}, "results": {{"interpretation": [{{"fragment": "aromatic_ring", "contribution": 0.15}}, {{"fragment": "halogen", "contribution": 0.35 if is_toxic else -0.05}}], "image_base64": None}}}}

    def _mock_pmic(p):
        smi = p.get("smiles", "")
        pmic = round(4.5 + len(smi) * 0.02, 2)
        mic_um = round(10 ** (6 - pmic), 2)
        return {{"summary": {{"pMIC_value": pmic, "estimated_MIC_uM": mic_um}}, "results": {{"smiles": smi}}}}

    def _mock_vina(p):
        best = round(-7.5 - len(p.get("ligand_file", "")) * 0.01, 2)
        return {{"summary": {{"best_docking_score": best, "score_after_minimization": round(best - 0.3, 2)}}, "results": {{"score_before_minimization": round(best + 0.5, 2), "docked_poses_file": "/tmp/docked_poses.pdbqt", "minimized_pose_file": "/tmp/minimized_pose.pdbqt"}}}}

    _mocks = {{
        "scaffold": _mock_scaffold,
        "libinvent": _mock_libinvent,
        "rxnflow": _mock_rxnflow,
        "reinvent4": lambda p: _mock_reinvent4(p, action),
        "scscore": _mock_scscore,
        "toxicity": _mock_toxicity,
        "pmic": _mock_pmic,
        "vina": _mock_vina,
    }}
    builder = _mocks.get(tool)
    if builder is None:
        return {{"error": f"Unknown tool: {{tool}}"}}
    return builder(payload)

# Patch both modules
import CAi.toolkit.functions.generation as _eval_gen_mod
import CAi.toolkit.functions.evaluation as _eval_evl_mod
_eval_gen_mod.run_tool = _eval_mock_run_tool
_eval_evl_mod.run_tool = _eval_mock_run_tool
'''


def _inject_mock_into_kernel(call_log_path: str) -> None:
    """Execute mock patching code in the running kernel subprocess."""
    from CAi.CAi_agent.execution.repl import _execute_in_kernel, _get_or_start_kernel

    kc = _get_or_start_kernel()
    source = _generate_kernel_mock_source(call_log_path)
    _execute_in_kernel(kc, source, timeout=15)


def _read_kernel_call_log(call_log_path: str) -> list[dict]:
    """Read the call log written by the kernel subprocess."""
    path = Path(call_log_path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


class _LazyCallLog(list):
    """List that lazily reads from a JSONL file on first access.

    The kernel subprocess appends call records to the file during test
    execution. This wrapper ensures the test sees up-to-date data.
    """

    def __init__(self, path: str):
        super().__init__()
        self._path = path
        self._loaded = False

    def _load(self):
        if not self._loaded:
            self.clear()
            self.extend(_read_kernel_call_log(self._path))
            self._loaded = False  # re-read each time (file grows during test)

    def __iter__(self):
        self._load()
        return super().__iter__()

    def __len__(self):
        self._load()
        return super().__len__()

    def __bool__(self):
        self._load()
        return len(self) > 0

    def __getitem__(self, index):
        self._load()
        return super().__getitem__(index)

    def __contains__(self, item):
        self._load()
        return super().__contains__(item)

    def __repr__(self):
        self._load()
        return f"_LazyCallLog({list(self)!r})"


# ---------------------------------------------------------------------------
# Fixture: mock_toolkit (parent-process only, for non-REPL tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_toolkit(monkeypatch):
    """Stub run_tool() in the parent process only.

    Returns a call_log list. Does NOT affect the REPL subprocess.
    Use `real_llm_agent` for end-to-end tests with kernel mocking.
    """
    call_log: list[dict] = []

    def fake_run_tool(tool: str, payload: dict, *, action: str = "default", **kwargs):
        call_log.append({
            "tool": tool,
            "action": action,
            "payload": dict(payload),
        })
        builder = TOOL_RESPONSES.get(tool)
        if builder is None:
            return {"error": f"Unknown tool: {tool}"}
        if tool == "reinvent4":
            return builder(payload, action=action)
        return builder(payload)

    monkeypatch.setattr("CAi.toolkit.functions.generation.run_tool", fake_run_tool)
    monkeypatch.setattr("CAi.toolkit.functions.evaluation.run_tool", fake_run_tool)
    return call_log


# ---------------------------------------------------------------------------
# Fixture: real_llm_agent (kernel-level mock)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_llm_agent(monkeypatch):
    """A1pro with real LLM credentials + kernel-injected mock toolkit.

    Requires valid LLM_API_KEY in CAi/.env or environment.
    The mock is injected into the Jupyter kernel subprocess so tool calls
    made by the REPL are intercepted. Yields (agent, call_log).
    """
    # Create a temp file for kernel → parent call_log communication
    call_log_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, prefix="eval_calllog_"
    )
    call_log_file.close()
    call_log_path = call_log_file.name

    from CAi.CAi_agent.agent import A1pro

    agent = A1pro(
        auto_load_tools=True,
        auto_load_skills=True,
        auto_load_utilities=True,
        timeout_seconds=120,
    )

    # Trigger kernel startup so we can inject mocks
    # We need to ensure the kernel is started before injecting
    from CAi.CAi_agent.execution.repl import _get_or_start_kernel

    _get_or_start_kernel()

    # Inject mock run_tool into the kernel subprocess
    _inject_mock_into_kernel(call_log_path)

    # Lazy call log — reads from file whenever the test accesses it
    call_log = _LazyCallLog(call_log_path)

    yield agent, call_log

    # Cleanup
    try:
        from CAi.CAi_agent.execution.repl import _shutdown_kernel

        _shutdown_kernel()
    except Exception:
        pass
    try:
        Path(call_log_path).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def real_llm_agent_no_utilities(monkeypatch):
    """A1pro with real LLM + kernel-injected mock toolkit, WITHOUT utilities."""
    call_log_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, prefix="eval_calllog_"
    )
    call_log_file.close()
    call_log_path = call_log_file.name

    from CAi.CAi_agent.agent import A1pro

    agent = A1pro(
        auto_load_tools=True,
        auto_load_skills=True,
        auto_load_utilities=False,
        timeout_seconds=120,
    )

    from CAi.CAi_agent.execution.repl import _get_or_start_kernel

    _get_or_start_kernel()
    _inject_mock_into_kernel(call_log_path)

    call_log = _LazyCallLog(call_log_path)

    yield agent, call_log

    try:
        from CAi.CAi_agent.execution.repl import _shutdown_kernel

        _shutdown_kernel()
    except Exception:
        pass
    try:
        Path(call_log_path).unlink(missing_ok=True)
    except Exception:
        pass
