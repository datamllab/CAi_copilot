![CAiCopilot](assets/CAiCopilot.png)

# CAi Copilot for Molecule Design

An agentic platform for molecular generation, evaluation, and candidate prioritization.

[English](./README.md) | [简体中文](./README_zh.md)

## Overview

CAi is an AI agent platform for drug discovery workflows. It combines a lightweight LangGraph-based execution engine with domain-specific tools for molecular generation, docking, toxicity prediction, and synthesizability assessment.

**Key design principles:**
- Mixed interaction — the agent can answer questions directly, execute code, or do both in one response
- Lean system prompt (~1,700 tokens) — only the tools you actually use
- Skills (SOPs) — pre-validated workflows loaded on demand, not baked into every prompt
- Self-learning utilities — the agent accumulates reusable functions from execution experience, curated by an independent LLM-based manager
- Clean layered architecture — `BaseAgent` handles execution, `A1pro` wires together tools, skills, utilities, and prompt

## Why CAi?
- One-click deployment for end-to-end molecular design workflows
- Web-based interaction for chemical researchers
- Integrated generation, evaluation, and screening
- Flexible tool selection for standalone or workflow-based use

## Architecture

```
BaseAgent  (core: LangGraph + LLM + REPL)
    ├── context_compression.py  (hybrid partition for long conversations)
    └── A1pro  (orchestrator)
              ├── execution/   (Jupyter kernel REPL + bash + timeout)
              ├── prompt/      (PromptBuilder + composable sections)
              ├── tools/       (ToolRegistry + ReplBridge + ModuleScanner)
              ├── utilities/   (self-learning code reuse library)
              ├── skills/      (SOP Markdown files)
              ├── cli/         (terminal REPL — theme, display, streaming, commands)
              └── web_ui/      (FastAPI + static frontend)
```

See [docs/architecture.md](docs/architecture.md) for full details.

## Getting Started

### 1. Configure environment

Create `CAi/.env`. The agent auto-detects the provider from `LLM_MODEL`:

```bash
# Anthropic (claude-*)
LLM_MODEL=claude-sonnet-4-5-20250929
LLM_API_KEY=sk-ant-...

# OpenAI (gpt-*, o1-*, o3-*)
# LLM_MODEL=gpt-4o-mini
# LLM_API_KEY=sk-...

# DeepSeek (deepseek-*)
# LLM_MODEL=deepseek-chat
# LLM_API_KEY=sk-...

# Custom endpoint (SGLang / vLLM / corporate OpenAI-compatible proxy)
# LLM_MODEL=qwen2.5-72b
# LLM_BASE_URL=http://your-endpoint/v1/
# LLM_API_KEY=your_key_here   # or "EMPTY" for unauthenticated local servers

TOOL_SERVER_HOST=0.0.0.0
TOOL_SERVER_PORT=8001
```

### 2. Install dependencies

```bash
conda create -n CAi python=3.11
conda activate CAi
pip install -e .
```

### 3. Install tool environments

Each tool runs in its own Conda environment:

```bash
cd CAi/toolkit/server

# Install all tool environments
bash install_all.sh

# Or install specific tools only
bash install_all.sh vina scscore toxicity
```

Before starting, download tool source code from [Google Drive](https://drive.google.com/drive/folders/1tjYJrMcVJnMopzbTyrf9KskvAxg2Xfin?usp=sharing) and extract into `CAi/toolkit/server/tools/`.

### 4. Start the tool backend

```bash
# Run from the repo root:
python -m CAi.toolkit.server.app
# Listens on http://0.0.0.0:8001 — check http://localhost:8001/health
```

### 5. Launch the agent

```bash
# Web UI
python CAi/main.py
# Web UI at http://localhost:7001

# Or interactive CLI REPL
python CAi/main.py --cli
# Optionally resume a conversation: --resume <conv_id>
```

## Interaction Modes

The agent supports three response modes:

| Mode | Example |
|---|---|
| Direct answer | "What is LogP?" → plain text explanation |
| Code execution | "Calculate SCScore for aspirin" → runs code, shows result |
| Mixed | "Analyze this molecule" → explains plan + executes analysis |

No more forced `<solution>` tags for every response.

## Example Prompts

**Scaffold-based analog generation**
```
Given the penicillin core scaffold with the SMILES string:
`CC1CSC2(NC(=O)*)C(=O)N2[C@H]1C(=O)O`
Generate 10 scaffold-derived small molecule analogues by adopting LibINVENT and RNN-based Constrained Scaffold Generation respectively, then sort the generated analogues according to the SC score.
```

**De novo design**
```
Take HIV-1 protease as the target protein, and adopt `1HVR.pdb` as the target structure file. The coordinate of the binding site center is set to [15.2, 23.5, 6.8].
Invoke Rxnflow and Reinvent4 to generate candidate small molecules, and rank all candidates based on Vina score.
```

**Molecule evaluation**
```
Calculate the toxicity and MIC values of the aforementioned generated small molecules, so as to evaluate their chemical characteristics and potential performance in the drug discovery and druggability development process.
```

## File Structure

```
CAi_copilot/
├── CAi/
│   ├── config.py                    # Global configuration
│   ├── .env                         # Local environment variables
│   ├── main.py                      # Entry point
│   ├── CAi_agent/
│   │   ├── base.py                  # BaseAgent — LangGraph + LLM + REPL
│   │   ├── agent.py                 # A1pro — orchestrator
│   │   ├── llm.py                   # LLM factory (Anthropic/OpenAI/DeepSeek/Custom)
│   │   ├── context_compression.py   # Hybrid partition strategy for long conversations
│   │   ├── prompt/                  # PromptBuilder + composable sections
│   │   ├── tools/                   # ToolRegistry + Scanner + ReplBridge
│   │   ├── utilities/               # Self-learning code reuse library
│   │   ├── execution/               # Jupyter kernel REPL + bash + timeout
│   │   └── skills/                  # SOP Markdown files
│   ├── cli/                         # Terminal REPL (theme, display, streaming, commands)
│   ├── toolkit/                     # Agent-facing drug discovery tools
│   │   ├── client.py                # HTTP client for the tool server
│   │   ├── _validators.py           # SMILES & pocket input validators
│   │   ├── skill_helpers.py         # get_skill_content / list_available_skills
│   │   ├── functions/
│   │   │   ├── generation.py        # 6 molecule generators
│   │   │   └── evaluation.py        # 4 molecule evaluators
│   │   └── server/                  # Tool execution backend (FastAPI)
│   └── web_ui/
│       ├── backend/
│       │   ├── app.py               # FastAPI chat + file endpoints
│       │   ├── conversation_store.py
│       │   └── pdf_export.py        # Conversation → Markdown → PDF
│       └── frontend/                # Static HTML/JS/CSS
├── agent_workspace/
│   └── _utilities/                  # Persisted utility functions (.py files)
├── tests/                           # Pytest suite (no API keys needed)
└── docs/
    └── architecture.md              # Detailed architecture documentation
```

## Tool Workflow

```
Agent (CAi/toolkit/functions/*.py)
    │  POST /run/{tool}/{action}
    ▼
Tool server (CAi/toolkit/server/app.py) → JobManager
    │  conda run -n <env> python run.py
    │  cwd = workspace/jobs/<uuid>/
    ▼
Tool (run.py) → result.json
    ▼
Agent receives result
```

## Tool Description
| Module Type                       | Tool                                      | Function                                 | Detailed Description                                                                                                                                                                                                                                                                                              |
| --------------------------------- | ----------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Constrained Scaffold Generation   | RNN-based Constrained Scaffold Generation | `generate_scaffold_analogs`              | Takes a scaffold structure as input and generates structurally similar small molecules while preserving the core scaffold. The modified regions may include R-groups or linkers. It is suitable for lead expansion, scaffold optimization, and targeted analog exploration.                                       |
| Constrained Scaffold Generation   | LibINVENT                                 | `generate_libinvent_decorations`         | Generates modifiable molecular libraries centered on a scaffold. It is especially suitable for systematic R-group expansion and controllable molecular design around a fixed core scaffold, and supports reaction-type constraints to improve synthetic feasibility.                                              |
| Constrained Scaffold Generation   | Reinvent 4                                | `generate_molecules_reinvent4_libinvent` | Further enables the generation of reaction-constrained chemical libraries based on a scaffold under the guidance of multi-objective scoring functions.                                                                                                                                                            |
| De Novo Molecular Design          | RXNFlow                                   | `run_rxnflow_design()`                   | Performs de novo small-molecule generation without relying on a fixed scaffold, based on a target protein, target-related information, or a specified chemical space. It is suitable for target-driven drug design and novel candidate discovery.                                                                 |
| De Novo Molecular Design          | Reinvent 4                                | `generate_molecules_reinvent4_denovo`    | Performs multi-objective driven molecular generation under the guidance of multi-objective scoring functions.                                                                                                                                                                                                     |
| De Novo Molecular Generation      | Reinvent 4                                | `generate_molecules_reinvent4_mol2mol`   | Takes a complete molecule as input and generates structurally similar candidate molecules conditioned on that molecule under multi-objective optimization, enabling local optimization.                                                                                                                           |
| Retrosynthesis Evaluation         | SC Score                                  | `calculate_scscore`                      | Evaluates the structural synthesizability of generated molecules by measuring their consistency with known synthesis patterns and their potential feasibility. It can be used for preliminary synthesizability screening of candidate molecules.                                                                  |
| Binding Affinity Evaluation       | Vina Score                                | `perform_molecular_docking_vina`         | Requires protein and small-molecule files as input and calculates docking scores to predict the binding affinity between a molecule and its target protein, supporting the screening and ranking of target-oriented candidate molecules.                                                                          |
| ADMET Evaluation                  | Toxicity Prediction                       | `predict_molecule_toxicity`              | Predicts the hepatotoxicity risk of molecules using a model fine-tuned on the Toxcast hepatotoxicity dataset, providing safety references for early-stage drug screening. It also supports Shapley value visualization at the substructure level to show the contribution of different substructures to toxicity. |
| Antibacterial Activity Evaluation | MIC Prediction                            | `predict_antibacterial_pmic`             | Predicts the minimum inhibitory concentration (MIC) of molecules using a chemical property prediction model trained on all molecules with MIC-related data from ChEMBL, and supports the ranking and screening of candidate molecules in antimicrobial drug design tasks.                                         |


## Extending CAi

### Add a tool

1. Add a function to `CAi/toolkit/functions/generation.py` or `evaluation.py`
2. Add input validation using validators from `CAi/toolkit/_validators.py` (e.g. `valid_complete_molecule_smiles`, `require_attachment_point`)
3. Re-export it from `CAi/toolkit/__init__.py` (and `functions/__init__.py`)
4. Restart or call `agent.reload_tools()`

```python
from CAi.toolkit._validators import valid_complete_molecule_smiles

def my_tool(smiles: str) -> dict:
    """One-line description shown in the agent's tool catalog."""
    if err := valid_complete_molecule_smiles(smiles):
        return {"success": False, "error": err}
    ...
```

### Add a skill (SOP)

Create `CAi/CAi_agent/skills/my_workflow.md` with `## Description` and `## Metadata` sections. The filename becomes the skill ID.
See [docs/architecture.md](docs/architecture.md#adding-skills) for the full Markdown format.

See [CAi/start.md](CAi/start.md) for the full development guide.

## Contribution

CAi Molecule Design Copilot contributes a unified agentic workflow for molecular generation, evaluation, and candidate selection. By integrating scaffold-based design, de novo generation, synthesizability assessment, toxicity prediction, antibacterial activity prediction, and docking-based evaluation into one system, it reduces the overhead of fragmented molecular design pipelines and makes advanced workflows more accessible to drug discovery researchers.

The platform is currently applied to scaffold-based analog generation, target-aware de novo molecular design, and multi-objective candidate screening. Through its web-based interface and natural-language interaction, CAi enables researchers to perform molecular design experiments more efficiently, reproducibly, and with greater flexibility in tool selection and workflow composition.

## Citation

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
