"""Tests for the gromacs_runner wrapper.

All HTTP calls are stubbed so no real GROMACS installation is needed.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from CAi.toolkit import client as client_mod
from CAi.toolkit.functions.generation import run_gromacs_md


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
# gromacs_runner
# ---------------------------------------------------------------------------


def test_gromacs_prep_happy_path(monkeypatch):
    """prep step returns topology and box files."""
    # Create a temp file to satisfy valid_existing_file check for input_pdb
    with tempfile.NamedTemporaryFile(suffix=".pdb", delete=False) as f:
        f.write(b"ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n")
        tmp_pdb = f.name

    try:
        def fake_post(url, **kwargs):
            return _Resp({"job_id": "gmx-prep-001"})

        def fake_get(url, **kwargs):
            return _Resp({
                "status": "finished",
                "data": {
                    "success": True,
                    "data": {
                        "output_gro": "box.gro",
                        "output_top": "topol.top",
                        "message": "拓扑建立完成",
                    },
                },
            })

        _patch_requests(monkeypatch, post=fake_post, get=fake_get)
        out = run_gromacs_md(step="prep", input_pdb=tmp_pdb)

        assert out["success"] is True
        assert out["step"] == "prep"
        assert out["data"]["output_gro"] == "box.gro"
        assert out["data"]["output_top"] == "topol.top"
    finally:
        os.unlink(tmp_pdb)


def test_gromacs_solvate_happy_path(monkeypatch):
    """solvate step returns ionized gro."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "gmx-solv-001"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "data": {
                    "output_gro": "ionized.gro",
                    "message": "溶剂化及离子添加完成",
                },
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = run_gromacs_md(step="solvate")

    assert out["success"] is True
    assert out["step"] == "solvate"
    assert out["data"]["output_gro"] == "ionized.gro"


def test_gromacs_minimize_happy_path(monkeypatch):
    """minimize step returns energy-minimized gro."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "gmx-min-001"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "data": {
                    "output_gro": "em.gro",
                    "message": "能量最小化完成",
                },
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = run_gromacs_md(step="minimize")

    assert out["success"] is True
    assert out["data"]["output_gro"] == "em.gro"


def test_gromacs_equilibrate_nvt(monkeypatch):
    """equilibrate with nvt mode."""

    captured_payload = {}

    def fake_post(url, **kwargs):
        body = kwargs.get("json", {})
        captured_payload.update(body)
        return _Resp({"job_id": "gmx-eq-001"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "data": {
                    "output_gro": "nvt.gro",
                    "message": "NVT 平衡完成",
                },
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = run_gromacs_md(step="equilibrate", mode="nvt")

    assert out["success"] is True
    assert captured_payload["mode"] == "nvt"
    assert out["data"]["output_gro"] == "nvt.gro"


def test_gromacs_equilibrate_npt(monkeypatch):
    """equilibrate with npt mode."""

    captured_payload = {}

    def fake_post(url, **kwargs):
        body = kwargs.get("json", {})
        captured_payload.update(body)
        return _Resp({"job_id": "gmx-eq-002"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "data": {
                    "output_gro": "npt.gro",
                    "message": "NPT 平衡完成",
                },
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = run_gromacs_md(step="equilibrate", mode="npt")

    assert out["success"] is True
    assert captured_payload["mode"] == "npt"


def test_gromacs_production_happy_path(monkeypatch):
    """production step returns trajectory xtc."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "gmx-prod-001"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": True,
                "data": {
                    "output_xtc": "md_0_1.xtc",
                    "message": "生产模拟完成",
                },
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = run_gromacs_md(step="production")

    assert out["success"] is True
    assert out["data"]["output_xtc"] == "md_0_1.xtc"


def test_gromacs_invalid_step():
    """Invalid step name returns an error dict."""
    out = run_gromacs_md(step="unknown_step")
    assert out["success"] is False
    assert "step must be one of" in out["error"]


def test_gromacs_server_error(monkeypatch):
    """Server-side GROMACS error is surfaced to the caller."""

    def fake_post(url, **kwargs):
        return _Resp({"job_id": "gmx-err-001"})

    def fake_get(url, **kwargs):
        return _Resp({
            "status": "finished",
            "data": {
                "success": False,
                "error": "GROMACS 执行失败: Fatal error: File not found",
            },
        })

    _patch_requests(monkeypatch, post=fake_post, get=fake_get)
    out = run_gromacs_md(step="minimize")

    assert out["success"] is False
    assert "GROMACS" in out["error"]


def test_gromacs_prep_missing_pdb():
    """prep step with non-existent PDB file returns an error."""
    out = run_gromacs_md(step="prep", input_pdb="/nonexistent/protein.pdb")
    assert out["success"] is False
    assert "does not exist" in out["error"].lower() or "不存在" in out["error"]


def test_gromacs_prep_custom_ff_and_water(monkeypatch):
    """Custom force field and water model are forwarded to payload."""

    captured_payload = {}
    with tempfile.NamedTemporaryFile(suffix=".pdb", delete=False) as f:
        f.write(b"ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n")
        tmp_pdb = f.name

    try:
        def fake_post(url, **kwargs):
            body = kwargs.get("json", {})
            captured_payload.update(body)
            return _Resp({"job_id": "gmx-prep-002"})

        def fake_get(url, **kwargs):
            return _Resp({
                "status": "finished",
                "data": {
                    "success": True,
                    "data": {"output_gro": "box.gro", "output_top": "topol.top"},
                },
            })

        _patch_requests(monkeypatch, post=fake_post, get=fake_get)
        run_gromacs_md(step="prep", input_pdb=tmp_pdb, ff="charmm36", water="tip4p")

        assert captured_payload["ff"] == "charmm36"
        assert captured_payload["water"] == "tip4p"
    finally:
        os.unlink(tmp_pdb)
