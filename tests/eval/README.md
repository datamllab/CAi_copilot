# CAi Agent 评测框架使用指南

## 目录

- [快速开始](#快速开始)
- [文件结构](#文件结构)
- [测试套件说明](#测试套件说明)
- [如何添加新的评测任务](#如何添加新的评测任务)
- [如何修改 Mock 数据](#如何修改-mock-数据)
- [Utility 效果评测](#utility-效果评测)
- [测试结果分析](#测试结果分析)

---

## 快速开始

### 终端交互式运行（单个任务，实时输出）

```bash
# 运行预定义任务 T1（有 Utility）
python -m tests.eval.run_eval --task T1

# 运行 T2（无 Utility，基线对比）
python -m tests.eval.run_eval --task T2 --no-utilities

# 自定义 prompt
python -m tests.eval.run_eval --prompt "生成 5 个分子并计算 SCScore"

# 详细输出（不截断）
python -m tests.eval.run_eval --task T1 -v

# 保存 metrics 到文件
python -m tests.eval.run_eval --task T1 --save-metrics
```

### 运行全部快速测试（无需 LLM API key）

```bash
# 基础设施测试 + 工具测试（< 1 秒）
pytest tests/eval/ -v -m "not slow"
```

### 运行全部测试（包括需要真实 LLM 的慢速测试）

```bash
# 需要先配置 LLM_API_KEY（在 CAi/.env 中）
pytest tests/eval/ -v -m slow
```

### 只运行某个测试文件

```bash
# 工具基础设施测试
pytest tests/eval/test_toolkit_infra.py -v

# Utility 基础设施测试
pytest tests/eval/test_utility_infra.py -v -m "not slow"

# Utility 效果评测（需真实 LLM）
pytest tests/eval/test_utility_effect.py -v -m slow
```

---

## 文件结构

```
tests/eval/
├── conftest.py                  # 共享 fixtures（mock_toolkit、real_llm_agent）
├── fixtures/
│   └── molecules.json           # 测试分子数据集
├── run_eval.py                  # 终端交互式评测脚本（单个任务，实时输出）
├── test_toolkit_infra.py        # 工具基础设施测试（32 个，快速）
├── test_utility_infra.py        # Utility 基础设施测试（9 快 + 3 慢）
└── test_utility_effect.py       # Utility 效果对比评测（13 个，需真实 LLM）
```

---

## 测试套件说明

### 1. `test_toolkit_infra.py` — 工具基础设施

验证工具子系统的正确性，无需 LLM。

| 测试类别 | 数量 | 验证内容 |
|---------|------|---------|
| 工具注册 | 3 | 10 个工具是否注册、hidden tools 是否正确、signature 是否有效 |
| Prompt 渲染 | 3 | 所有工具是否出现在 prompt、hidden tools 是否排除、空 registry 是否渲染为空 |
| Validator 测试 | 16 | 各工具对无效输入的拒绝行为（无 attachment point、手性、空输入等） |
| 返回 Schema | 10 | 每个工具 wrapper 返回的 dict key 是否与文档一致 |

### 2. `test_utility_infra.py` — Utility 基础设施

验证 Utility 子系统的正确性。

| 测试 | 速度 | 验证内容 |
|------|------|---------|
| `test_utility_registry_load` | 快 | load_snapshot() 正确执行 utility 代码 |
| `test_utility_registry_apply_usage` | 快 | apply_usage() 更新磁盘上的计数 |
| `test_utility_registry_auto_eviction` | 快 | 超过 20 个时驱逐低使用率 utility |
| `test_utility_registry_empty_dir` | 快 | 空目录返回 0 个 utility |
| `test_all_skills_loaded` | 快 | 8 个 skill 全部加载 |
| `test_skill_descriptions_not_truncated` | 快 | Skill 描述正确提取 |
| `test_skill_metadata_extraction` | 快 | Skill metadata 正确提取 |
| `test_empty_utilities_section_dropped` | 快 | 空 utility section 不出现 |
| `test_prompt_with_utilities_includes_them` | 快 | utility 名称出现在 prompt |
| `test_utility_kernel_injection` | **慢** | utility 在 kernel 中可调用 |
| `test_usage_tracking_accuracy` | **慢** | usage tracking 准确记录调用次数 |
| `test_kernel_restart_survival` | **慢** | kernel 重启后 utility 仍可用 |

### 3. `test_utility_effect.py` — Utility 效果对比

**需要真实 LLM API key。** Mock 工具服务器，用真实 LLM 做端到端测试。

对比实验：同一批任务，在「无 Utility」vs「有 Utility」条件下的表现差异。

| 任务 | Prompt 场景 | 预期工具链 |
|------|------------|-----------|
| T1 | 基于骨架生成类似物 + SCScore | scaffold → scscore |
| T2 | De novo 生成 + SCScore 排序 | reinvent4 → scscore |
| T3 | 分子毒性 + pMIC 分析 | toxicity + pmic |
| T4 | De novo + SCScore 过滤 | reinvent4 → scscore |
| T5 | Mol2Mol + 毒性 + SCScore | reinvent4 → scscore + toxicity |
| T6 | 多工具对比（RNN + LibINVENT） | scaffold + libinvent → scscore |

---

## 如何添加新的评测任务

### 步骤 1：在 `test_utility_effect.py` 中添加任务

在 `TASKS` 列表中添加新的任务元组：

```python
TASKS = [
    # ... 现有任务 ...
    (
        "T7",                                      # 任务 ID
        "基于骨架 c1cc([*])ccc1 生成 10 个类似物，"  # Prompt
        "预测毒性和 SCScore，筛选最佳 3 个。",
        {"scaffold", "scscore", "toxicity"},       # 期望调用的工具集
    ),
]
```

每个任务包含：
- **任务 ID**：用于标识和追踪
- **Prompt**：发送给 agent 的自然语言指令
- **期望工具集**：agent 完成任务应该调用的工具名

### 步骤 2：（可选）在 `molecules.json` 中添加测试分子

```json
{
  "scaffolds": [
    {
      "id": "my_new_scaffold",
      "smiles": "c1cc([*])c(O)cc1",
      "description": "苯酚骨架",
      "attachment_points": 1
    }
  ]
}
```

### 步骤 3：（可选）添加工具基础设施测试

在 `test_toolkit_infra.py` 中添加 validator 或 schema 测试：

```python
class TestMyNewValidator:
    def test_rejects_invalid_input(self, mock_toolkit):
        from CAi.toolkit.functions.generation import my_new_tool
        result = my_new_tool("invalid_input")
        assert not result["success"]
        assert "expected error message" in result["error"]
```

---

## 如何修改 Mock 数据

### Mock 数据定义位置

在 `tests/eval/conftest.py` 中，每个工具都有一个 mock 函数：

| 函数 | 工具 | 返回值 |
|------|------|--------|
| `_mock_scaffold()` | RNN scaffold | 5 个 SMILES + summary |
| `_mock_libinvent()` | LibINVENT | 3 个 decorated SMILES |
| `_mock_rxnflow()` | RxnFlow | 10 个 target-aware SMILES + QED/proxy |
| `_mock_reinvent4()` | REINVENT4 | 根据 action 返回不同结果 |
| `_mock_scscore()` | SC Score | 每个分子 1.5-4.5 分数 |
| `_mock_toxicity()` | Toxicity | 基于卤素判断毒性 |
| `_mock_pmic()` | pMIC | 基于 SMILES 长度计算 |
| `_mock_vina()` | Vina | 基于文件名计算 docking score |

### 修改示例：增加 scaffold 生成的分子数量

```python
# 在 conftest.py 中修改
_FAKE_SCAFFOLD_ANALOGS = [
    "CCOc1cc(*)ccc1",
    "c1cc(CCO)cc(*)c1",
    "CC(C)Oc1cc(*)ccc1",
    "c1cc(OCC(*)cc1)CCO",
    "CCOc1cc(C)cc(*)c1",
    "c1cc(CCC)cc(*)cc1",   # 新增
    "CCOc1cc(Cl)cc(*)c1",  # 新增
    # ... 更多
]
```

### 修改示例：调整毒性判断逻辑

```python
def _mock_toxicity(payload: dict) -> dict:
    smi = payload.get("smiles", "")
    # 修改判断逻辑
    is_toxic = "Cl" in smi or "Br" in smi or "NO2" in smi  # 新增 NO2
    prob = round(0.85 if is_toxic else 0.25, 3)
    return {
        "summary": {"is_toxic": is_toxic, "toxicity_probability": prob},
        "results": {
            "interpretation": [{"fragment": "...", "contribution": 0.15}],
            "image_base64": None,
        },
    }
```

### Mock 数据设计原则

1. **结构一致**：返回的 dict 结构必须与真实工具完全相同
2. **SMILES 有效**：使用可被 RDKit 解析的简单分子
3. **数值合理**：SCScore 1.5-4.5，Vina -5 到 -12 等
4. **可参数化**：根据 payload 返回不同数量的结果

---

## Utility 效果评测

### 运行评测

```bash
# 完整对比实验（6 个任务 × 2 组 = 12 次 agent 运行）
pytest tests/eval/test_utility_effect.py::test_utility_effect_comparison -v -m slow -s
```

`-s` 参数用于输出对比摘要表格。

### 输出示例

```
============================================================
Utility Effect Comparison
============================================================
Metric                        With Util   Without Util      Delta
------------------------------------------------------------
Avg turns                         4.50           6.83      -2.33
Avg tool calls                    3.17           4.50      -1.33
============================================================
```

### 结果文件

评测结果保存在 `agent_workspace/eval_metrics.jsonl`：

```jsonl
{"task_id": "T1", "variant": "with_utilities", "turns": 4, "tool_calls": 3, ...}
{"task_id": "T1", "variant": "without_utilities", "turns": 7, "tool_calls": 5, ...}
{"task_id": "SUMMARY", "variant": "comparison", ...}
```

### 指标说明

| 指标 | 含义 | 预期（有 Utility） |
|------|------|-------------------|
| `turns` | 完成任务的对话轮数 | 更少 |
| `tool_calls` | 底层工具调用总次数 | 更少 |
| `unique_tools` | 调用的不同工具数 | 相同或更少 |
| `has_error` | 执行中是否出现错误 | 更低 |
| `completion` | 任务是否成功完成 | 相同 |

---

## 测试结果分析

### 查看详细的测试失败信息

```bash
pytest tests/eval/ -v --tb=long  # 详细 traceback
pytest tests/eval/ -v --tb=short # 简洁 traceback
```

### 只运行特定的测试

```bash
# 只运行 validator 相关测试
pytest tests/eval/test_toolkit_infra.py -v -k "validator or Validator"

# 只运行 T1 任务（Utility 效果）
pytest tests/eval/test_utility_effect.py -v -k "T1" -m slow

# 只运行不含 kernel 的测试
pytest tests/eval/test_utility_infra.py -v -k "not kernel"
```

### 生成测试报告

```bash
# 生成 JUnit XML 报告
pytest tests/eval/ -v --junitxml=eval_report.xml

# 生成 HTML 报告（需要 pytest-html）
pip install pytest-html
pytest tests/eval/ -v --html=eval_report.html
```

---

## 常见修改场景

### 场景 1：修改工具调用的超时时间

在 `conftest.py` 的 `real_llm_agent` fixture 中：

```python
agent = A1pro(
    auto_load_tools=True,
    auto_load_skills=True,
    auto_load_utilities=True,
    timeout_seconds=60,  # 默认 120 秒
)
```

### 场景 2：禁用 skills（只测工具 + utility）

在 fixture 中修改：

```python
agent = A1pro(
    auto_load_tools=True,
    auto_load_skills=False,  # 禁用 skills
    auto_load_utilities=True,
)
```

### 场景 3：添加新的 mock 工具

1. 在 `conftest.py` 中添加 mock 函数
2. 注册到 `TOOL_RESPONSES` 字典

```python
def _mock_my_new_tool(payload: dict) -> dict:
    return {
        "summary": {"count": len(payload.get("smiles_list", []))},
        "results": [{"score": 3.5, "smiles": s} for s in payload.get("smiles_list", [])],
    }

TOOL_RESPONSES = {
    # ... 现有工具 ...
    "my_new_tool": _mock_my_new_tool,
}
```

### 场景 4：记录 mock 工具的调用详情

`mock_toolkit` fixture 返回 `call_log`，记录每次调用：

```python
def test_something(mock_toolkit):
    # ... 触发工具调用 ...
    for call in mock_toolkit:
        print(f"Tool: {call['tool']}, Action: {call['action']}, Payload: {call['payload']}")
```

---

## pytest markers 说明

| Marker | 含义 | 如何跳过 |
|--------|------|---------|
| `slow` | 需要 kernel 操作或真实 LLM，运行较慢 | `pytest -m "not slow"` |

在 `pyproject.toml` 中已注册：

```toml
[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow (requires kernel operations or real LLM)",
]
```
