"""Tests for sc2mol and synllama wrappers.

All HTTP calls are stubbed so no real tool server is needed.
"""

from __future__ import annotations

import pytest

from CAi.toolkit import client as client_mod
from CAi.toolkit.client import run_tool
from CAi.toolkit.functions.generation import (
    generate_molecules_sc2mol,
    infer_synthesis_synllama,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            err = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


def _patch_requests(monkeypatch, *, get=None, post=None):
    import requests
    if get is not None:
        monkeypatch.setattr(requests, "get", get)
    if post is not None:
        monkeypatch.setattr(requests, "post", post)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(client_mod.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------------
# sc2mol
# ---------------------------------------------------------------------------


def test_sc2mol_happy_path(monkeypatch):
    """End-to-end: sc2mol returns generated molecules from scaffolds."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "sc2mol-001"})

    polls = [
        {"status": "running"},
        {
            "status": "finished",
            "data": {
                "success": True,
                "summary": {
                    "task": "Sc2Mol scaffold-conditioned molecule generation",
                    "mode": "scaffold",
                    "checkpoint": "sc2mol_smoke/ckpt-9",
                    "num_scaffolds": 2,
                    "num_sample_requested": 2,
                    "num_sample_used": 2,
                    "num_results_returned": 2,
                },
                "results": [
                    {"index": 0, "input_scaffold": "c1ccccc1", "smiles": "CCc1ccccc1"},
                    {"index": 1, "input_scaffold": "C1CCCCC1", "smiles": "CC1CCCCC1"},
                ],
                "errors": None,
            },
        },
    ]

    def fake_get(url, **kwargs):
        return _Resp(polls.pop(0))

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = generate_molecules_sc2mol(scaffolds=["c1ccccc1", "C1CCCCC1"])

    assert out["success"] is True
    assert out["mode"] == "scaffold"
    assert out["num_scaffolds"] == 2
    assert len(out["results"]) == 2
    assert out["results"][0]["smiles"] == "CCc1ccccc1"


def test_sc2mol_empty_scaffolds():
    """Empty scaffolds list should return an error dict."""
    out = generate_molecules_sc2mol(scaffolds=[])
    assert out["success"] is False
    assert "scaffolds" in out["error"]


def test_sc2mol_server_error(monkeypatch):
    """When the server returns success=False, the wrapper surfaces the error."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "sc2mol-err"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": False,
                "error": "Missing required parameter: scaffolds",
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = generate_molecules_sc2mol(scaffolds=["c1ccccc1"])

    assert out["success"] is False
    assert "scaffolds" in out["error"]


def test_sc2mol_custom_params(monkeypatch):
    """Custom ckpt and max_len should be forwarded to the payload."""

    captured_payload = {}

    def fake_post(url, **kwargs):
        body = kwargs.get("json", {})
        captured_payload.update(body)
        return _Resp({"job_id": "sc2mol-002"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "summary": {
                    "checkpoint": "custom/ckpt-5",
                    "num_scaffolds": 1,
                    "num_sample_requested": 1,
                    "num_sample_used": 1,
                },
                "results": [{"index": 0, "smiles": "Cc1ccccc1"}],
                "errors": None,
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    generate_molecules_sc2mol(
        scaffolds=["c1ccccc1"],
        num_sample=1,
        ckpt="custom/ckpt-5",
        max_len=128,
    )

    assert captured_payload.get("ckpt") == "custom/ckpt-5"
    assert captured_payload.get("max_len") == 128
    assert captured_payload.get("num_sample") == 1


# ---------------------------------------------------------------------------
# synllama
# ---------------------------------------------------------------------------


def test_synllama_happy_path(monkeypatch):
    """End-to-end: synllama returns synthesis pathway predictions."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "synllama-001"})

    polls = [
        {"status": "running"},
        {
            "status": "finished",
            "data": {
                "success": True,
                "summary": {
                    "task": "SynLlama raw synthesis-pathway inference",
                    "model": "91rxns",
                    "sample_mode": "frozen_only",
                    "num_input_smiles": 1,
                    "num_results_returned": 1,
                },
                "results": [
                    {
                        "index": 0,
                        "smiles": "CCOc1ccc2nc(S(N)(=O)=O)sc2c1",
                        "predictions": {"route_1": ["CCO", "c1ccc2nc(S)sc2c1"]},
                    },
                ],
                "errors": None,
            },
        },
    ]

    def fake_get(url, **kwargs):
        return _Resp(polls.pop(0))

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = infer_synthesis_synllama(
        smiles=["CCOc1ccc2nc(S(N)(=O)=O)sc2c1"],
    )

    assert out["success"] is True
    assert out["model"] == "91rxns"
    assert out["sample_mode"] == "frozen_only"
    assert out["num_input_smiles"] == 1
    assert len(out["results"]) == 1


def test_synllama_empty_smiles():
    """Empty smiles list should return an error dict."""
    out = infer_synthesis_synllama(smiles=[])
    assert out["success"] is False
    assert "smiles" in out["error"]


def test_synllama_server_error(monkeypatch):
    """When the server returns success=False, the wrapper surfaces the error."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "synllama-err"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": False,
                "error": "Invalid SMILES input",
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = infer_synthesis_synllama(smiles=["invalid_smiles!!!"])

    assert out["success"] is False
    assert "invalid smiles" in out["error"].lower()


def test_synllama_custom_params(monkeypatch):
    """Custom sample_mode, gpus, and max_molecules should be forwarded."""

    captured_payload = {}

    def fake_post(url, **kwargs):
        body = kwargs.get("json", {})
        captured_payload.update(body)
        return _Resp({"job_id": "synllama-002"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "summary": {
                    "model": "91rxns",
                    "sample_mode": "greedy",
                    "num_input_smiles": 1,
                },
                "results": [{"index": 0, "smiles": "c1ccccc1", "predictions": {}}],
                "errors": None,
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    infer_synthesis_synllama(
        smiles=["c1ccccc1"],
        sample_mode="greedy",
        gpus=2,
        max_molecules=10,
    )

    assert captured_payload.get("sample_mode") == "greedy"
    assert captured_payload.get("gpus") == 2
    assert captured_payload.get("max_molecules") == 10
