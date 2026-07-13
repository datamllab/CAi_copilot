"""Integration tests for sc2mol and synllama wrappers.

This script hits the ACTUAL tool server. Ensure the server is running
and accessible before executing these tests.
"""

from __future__ import annotations

import os
import pytest

from CAi.toolkit.functions.generation import (
    generate_molecules_sc2mol,
    infer_synthesis_synllama,
)

# 只要配置了任意一个，就激活测试
SERVER_AVAILABLE = os.getenv("CAI_API_BASE") is not None or os.getenv("RUN_INTEGRATION_TESTS") == "true"

pytestmark = pytest.mark.skipif(
    not SERVER_AVAILABLE,
    reason="Missing CAI_API_BASE environment variable. Skipping real server tests."
)


# ---------------------------------------------------------------------------
# sc2mol 真实测试
# ---------------------------------------------------------------------------

def test_sc2mol_real_execution():
    """验证 sc2mol 分子生成工具是否能真正与后端通信并返回有效分子。"""
    test_scaffolds = ["c1ccccc1"]
    
    print("\n[sc2mol] Sending real request to server...")
    out = generate_molecules_sc2mol(
        scaffolds=test_scaffolds,
        num_sample=1,
        max_len=64
    )
    print(f"[sc2mol] Server response received: {out}")

    assert out is not None
    assert isinstance(out, dict)
    assert out.get("success") is True, f"任务执行失败，错误信息: {out.get('error')}"
    assert "results" in out
    assert len(out["results"]) > 0
    
    generated_smiles = out["results"][0].get("smiles")
    assert isinstance(generated_smiles, str)
    assert len(generated_smiles) > 0


# ---------------------------------------------------------------------------
# synllama 真实测试
# ---------------------------------------------------------------------------

def test_synllama_real_execution():
    """验证 synllama 逆合成预测工具是否能真正运行并返回路线。"""
    test_smiles = ["CCO"]
    
    print("\n[synllama] Sending real request to server...")
    out = infer_synthesis_synllama(
        smiles=test_smiles,
        sample_mode="greedy"
    )
    print(f"[synllama] Server response received: {out}")

    assert out is not None
    assert isinstance(out, dict)
    assert out.get("success") is True, f"任务执行失败，错误信息: {out.get('error')}"
    assert "results" in out
    assert len(out["results"]) == 1
    
    result_entry = out["results"][0]
    assert "predictions" in result_entry
    
    # 【已修正】真实服务器返回的 predictions 是一个包含了多条可能路线的 list
    assert isinstance(result_entry["predictions"], list)
    if len(result_entry["predictions"]) > 0:
        # 顺便验证列表内部路线的结构
        first_route = result_entry["predictions"][0]
        assert "building_blocks" in first_route
        assert "reactions" in first_route


if __name__ == "__main__":
    print("=== 独立脚本运行模式 ===")
    test_sc2mol_real_execution()
    test_synllama_real_execution()
