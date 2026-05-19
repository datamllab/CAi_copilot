![CAiCopilot](assets/CAiCopilot.png)

# CAi 分子设计智能助手

面向分子生成、性质评估与候选优选的智能 Agent 平台。

[English](./README.md) | [简体中文](./README_zh.md)

## 项目概述

CAi 分子设计智能助手是一个集智能分子设计、基于骨架的分子生成、从头药物发现与多维度性能评估于一体的 Agent 平台。该系统面向药物发现研究人员与计算化学工作者设计，支持通过简单命令快速部署并运行复杂的分子设计工作流，降低环境配置、模型集成与评估流程构建带来的使用门槛。

平台将分子生成、性质评估与候选筛选整合到统一工作流中，使整个实验流程更加易用、可复现且具备较强的科学严谨性，从而帮助研究者节省时间与计算资源，并提升早期药物设计实验的整体效率。

**核心设计原则：**
- 混合交互模式 — Agent 可以直接回答问题、执行代码，或在同一回复中两者兼顾
- 精简系统提示词（约 1,700 tokens）— 只包含你实际使用的工具
- Skills（SOP）— 预验证的工作流按需加载，不占用每次对话的上下文
- 自主学习工具库（Utilities）— Agent 从执行经验中积累可复用函数，由独立的 LLM 管理器负责维护
- 清晰的分层架构 — `BaseAgent` 负责执行，`A1pro` 将工具、技能、工具库和提示词串联起来

## 为什么选择 CAi？

- **一键式部署**：支持端到端分子设计工作流的快速部署与执行  
- **Web 交互界面**：面向化学研究者的友好交互方式  
- **生成—评估—筛选一体化**：打通完整分子设计流程  
- **灵活工具选择**：既支持单工具独立调用，也支持流程化组合使用  

## 架构

```
BaseAgent  （核心：LangGraph + LLM + REPL）
    └── A1pro  （编排层）
              ├── execution/   （Jupyter kernel REPL + bash + timeout）
              ├── prompt/      （PromptBuilder + 可组合的 Section）
              ├── tools/       （ToolRegistry + ReplBridge + ModuleScanner）
              ├── utilities/   （自主学习代码复用库）
              ├── skills/      （SOP Markdown 文件）
              └── web_ui/      （FastAPI + 静态前端）
```

详细架构说明见 [docs/architecture.md](docs/architecture.md)。

## 快速开始

### 1. 配置环境变量

在 `CAi/` 目录下创建 `.env` 文件。Agent 会根据 `LLM_MODEL` 自动识别 provider：

```bash
# Anthropic（claude-*）
LLM_MODEL=claude-sonnet-4-5-20250929
LLM_API_KEY=sk-ant-...

# OpenAI（gpt-*, o1-*, o3-*）
# LLM_MODEL=gpt-4o-mini
# LLM_API_KEY=sk-...

# DeepSeek（deepseek-*）
# LLM_MODEL=deepseek-chat
# LLM_API_KEY=sk-...

# 自定义端点（SGLang / vLLM / 企业 OpenAI 兼容代理）
# LLM_MODEL=qwen2.5-72b
# LLM_BASE_URL=http://your-endpoint/v1/
# LLM_API_KEY=your_key_here   # 本地无鉴权服务器可以填 "EMPTY"

TOOL_SERVER_HOST=0.0.0.0
TOOL_SERVER_PORT=8001
```

### 2. 安装基础依赖

```bash
conda create -n CAi python=3.11
conda activate CAi
pip install -e .
```

### 3. 安装工具运行环境

每个工具运行在独立的 Conda 环境中：

```bash
cd CAi/toolkit/server

# 安装全部工具环境
bash install_all.sh

# 仅安装部分工具
bash install_all.sh vina scscore toxicity
```

启动前请先从 [Google Drive](https://drive.google.com/drive/folders/1tjYJrMcVJnMopzbTyrf9KskvAxg2Xfin?usp=sharing) 下载工具源码，解压到 `CAi/toolkit/server/tools/`。

### 4. 启动工具后端

```bash
# 在仓库根目录运行
python -m CAi.toolkit.server.app
# 监听 http://0.0.0.0:8001，访问 /health 可自检
```

### 5. 启动 Agent

```bash
python CAi/main.py
# Web UI 地址：http://localhost:7001
```

## 交互模式

Agent 支持三种回复模式：

| 模式 | 示例 |
|---|---|
| 直接回答 | "什么是 LogP？" → 直接输出文字解释 |
| 代码执行 | "计算阿司匹林的 SCScore" → 执行代码并展示结果 |
| 混合模式 | "分析这个分子" → 先说明计划，再执行分析 |

不再强制每次回复都包含 `<solution>` 标签。

## 示例 Prompt

**基于骨架的类似物生成**
```
给定青霉素母核骨架
CC1(C)S[C@@H]2(NC(=O)*)C(=O)N2[C@H]1C(=O)O，
使用LibINVENT 和  RNN-based Constrained Scaffold Generation 分别生成 10 个基于骨架的小分子类似物，并按照 SC score进行排序。
```

**基于靶点的从头分子设计**
```
以 HIV-1 protease 作为目标蛋白，使用 1HVR.pdb 作为目标结构文件，结合位点中心坐标为 [15.2,23.5,6.8]，调用 Rxnflow 和 Reinvent4 工具生成候选小分子，并按照 Vina score排名。
```

**分子性质评估**
```
对前面生成的小分子计算 toxicity、MIC，用于评估分子的化学性质成药过程中可能表现出的性质。
```

## 项目结构

```
CAi_copilot/
├── CAi/
│   ├── config.py                    # 全局配置
│   ├── .env                         # 本地环境变量
│   ├── main.py                      # 启动入口
│   ├── CAi_agent/
│   │   ├── base.py                  # BaseAgent — LangGraph + LLM + REPL
│   │   ├── agent.py                 # A1pro — 编排层
│   │   ├── llm.py                   # LLM 工厂（Anthropic/OpenAI/DeepSeek/Custom）
│   │   ├── prompt/                  # PromptBuilder + 可组合的 Section
│   │   ├── tools/                   # ToolRegistry + Scanner + ReplBridge
│   │   ├── utilities/               # 自主学习代码复用库
│   │   ├── execution/               # Jupyter kernel REPL + bash + timeout
│   │   └── skills/                  # SOP Markdown 文件
│   ├── toolkit/                     # 面向 Agent 的药物发现工具集
│   │   ├── client.py                # 工具服务端 HTTP 客户端
│   │   ├── _validators.py           # SMILES 与口袋输入校验器
│   │   ├── skill_helpers.py         # get_skill_content / list_available_skills
│   │   ├── functions/
│   │   │   ├── generation.py        # 6 个分子生成工具
│   │   │   └── evaluation.py        # 4 个分子评估工具
│   │   └── server/                  # 工具执行后端（FastAPI）
│   └── web_ui/
│       ├── backend/
│       │   ├── app.py               # FastAPI 聊天 + 文件接口
│       │   ├── conversation_store.py
│       │   └── pdf_export.py        # 对话 → Markdown → PDF
│       └── frontend/                # 静态 HTML/JS/CSS
├── agent_workspace/
│   └── _utilities/                  # 持久化的工具函数（.py 文件）
├── tests/                           # Pytest 测试套件（无需 API key）
└── docs/
    └── architecture.md              # 详细架构文档
```

## 工具调用链路

```
Agent（CAi/toolkit/functions/*.py）
    │  POST /run/{tool}/{action}
    ▼
工具服务（CAi/toolkit/server/app.py）→ JobManager
    │  conda run -n <env> python run.py
    │  cwd = workspace/jobs/<uuid>/
    ▼
工具执行（run.py）→ result.json
    ▼
Agent 接收结果
```

## 工具说明
| 功能类型     | 工具                                        | 函数                      | 详细说明                                                                                             |
| -------- | ----------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 骨架约束分子生成 | RNN-based Constrained Scaffold Generation | `generate_scaffold_analogs` | 输入骨架结构，修改部分可以包括R-groups或者linking，在保留核心骨架的前提下生成结构类似的小分子。适用于先导化合物扩展、母核优化和定向类似物探索。 |
| 骨架约束分子生成 | LibINVENT                                 | `generate_libinvent_decorations`            | 以骨架为中心生成可修饰的分子库，尤其适合围绕固定母核开展系统化 R-group 扩展和可控分子设计，并支持反应类型约束以提升分子合成可行性。|
| 骨架约束分子生成 | Reinvent 4                                | `generate_molecules_reinvent4_libinvent`    | 更进一步，在多目标打分函数引导下，基于骨架生成具备反应约束的化学分子库。|
| 从头分子设计   | RXNFlow                                   | `generate_molecules_for_pocket`                  | 不依赖固定骨架，基于目标蛋白、靶点信息或指定化学空间进行从头设计的小分子生成，适用于靶点导向药物设计与全新候选分子发现。                                   |
| 从头分子设计   | Reinvent 4                                | `generate_molecules_reinvent4_denovo` | 在多目标打分函数引导下，实现多目标驱动的分子生成。 |            
| 从头分子生成   | Reinvent 4                                | `generate_molecules_reinvent4_mol2mol` |接收完整分子输入并以该分子为条件，在多目标优化驱动下生成结构相似的候选分子，实现局部优化。       |
| 逆向合成评估   | SC Score                                  | `calculate_scscore`                  | 对生成分子的结构可合成性进行评估，衡量其与已知合成模式的一致性和潜在可行性，可用于候选分子的初步可合成性筛选。                                      |
| 亲和力性能评估  | Vina Score                                | `perform_molecular_docking_vina`                | 需要蛋白质和小分子文件作为输入，计算 docking score，用于预测分子与目标蛋白之间的结合亲和力，支持靶点导向候选分子的筛选与排序。|                       
| ADMET性能评估  | Toxicity Prediction                       | `predict_molecule_toxicity`                    | 使用Toxcast肝细胞毒性数据对模型微调后，用于预测分子的肝细胞毒性反应风险，为早期药物筛选提供安全性参考，并且支持子结构的Shapley value 可视化分析，展示不同子结构对毒性的贡献程度。 |                                      
| 抑菌浓度性能评估  | MIC Prediction                            | `predict_antibacterial_pmic`                         | 基于化学性质预测模型使用ChEMBL中的所有包括MIC数据的分子训练，并预测分子的最低抑菌浓度（MIC），并辅助抗菌药物设计任务中的分子排序与筛选。                                 |

---

## 扩展 CAi

### 添加工具

1. 在 `CAi/toolkit/functions/generation.py` 或 `evaluation.py` 中添加函数
2. 使用 `CAi/toolkit/_validators.py` 中的校验器进行输入验证（如 `valid_complete_molecule_smiles`、`require_attachment_point`）
3. 在 `CAi/toolkit/__init__.py` 和 `functions/__init__.py` 中导出
4. 重启 Agent 或调用 `agent.reload_tools()`

```python
from CAi.toolkit._validators import valid_complete_molecule_smiles

def my_tool(smiles: str) -> dict:
    """一句话描述，会显示在 Agent 的工具目录中。"""
    if err := valid_complete_molecule_smiles(smiles):
        return {"success": False, "error": err}
    ...
```

### 添加技能（SOP）

在 `CAi/CAi_agent/skills/` 下创建包含 `## Description` 和 `## Metadata` 章节的 Markdown 文件，文件名即为技能 ID。
格式说明见 [docs/architecture.md](docs/architecture.md#adding-skills)。

完整开发指南见 [CAi/start.md](CAi/start.md)。

## 贡献

CAi Copilot 构建了一套统一的分子生成、性质评估与候选优选的 Agent 化工作流。通过将基于骨架的分子设计、从头分子生成、可合成性评估、毒性预测、抗菌活性预测以及基于 docking 的亲和力估计整合到同一系统中，平台有效降低了传统分子设计流程中工具链分散、流程割裂和使用复杂的问题，使高级分子设计流程能够更便捷地服务于药物发现研究人员。

当前，该平台已经可用于基于骨架的类似物生成、面向靶点的从头分子设计以及多目标候选分子筛选。借助 Web 交互界面与自然语言指令方式，CAi 使研究者能够以更高效率、更强可复现性和更灵活的方式开展分子设计实验。

## 引用

```bibtex
@misc{cai_molecule_design_copilot_2026,
  author    = {Datalab},
  title     = {CAi Molecule Design Copilot},
  year      = {2026},
  month     = {May},
  publisher = {GitHub},
  note      = {An agentic platform for molecular generation, evaluation, and candidate selection}
}
```
