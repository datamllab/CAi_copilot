# AutoDock Vina 受体准备工具

单一工具 `vina_prep`，提供 5 个 action 覆盖 AutoDock Vina 受体准备全流程：

```text
raw receptor.pdb
  → vina_prep / prepare       → receptor_clean.pdb
  → vina_prep / convert       → receptor_clean.pdbqt
```

## Actions

| Action | 脚本 | 说明 |
|--------|------|------|
| `default` | `run.py` | 清洗受体 PDB（同 prepare） |
| `analyze` | `analyze.py` | 分析 PDB 结构（链、配体、金属、水） |
| `prepare` | `run.py` | 清洗受体 PDB，输出 cleaned PDB + 报告 |
| `batch_prepare` | `batch_prepare.py` | 批量清洗多个受体 PDB |
| `convert` | `convert.py` | PDB → PDBQT 转换（Meeko） |

## 文件结构

```text
vina_prep/
├── config.json          # 工具配置
├── _lib.py              # 核心逻辑（被 action 脚本导入）
├── run.py               # prepare action（default）
├── analyze.py           # analyze action
├── batch_prepare.py     # batch_prepare action
├── convert.py           # convert action
├── environment.yml      # conda 依赖
└── requirements.txt     # pip 依赖
```

## Conda 环境

```bash
conda env create -f vina_prep/environment.yml
```

核心依赖：`rdkit`、`meeko`、`vina`、`openbabel`

## Agent Wrapper

三个包装函数注册在 `CAi/toolkit/functions/evaluation.py`：

```python
analyze_receptor_pdb_for_vina(receptor_pdb_path, ...)
prepare_receptor_pdb_for_vina(receptor_pdb_path, ...)
convert_receptor_pdb_to_pdbqt_for_vina(receptor_pdb_path, ...)
```

内部调用 `run_tool("vina_prep", payload, action=...)`。

## 与 Vina docking 配合

```text
prepare_receptor_pdb_for_vina → convert_receptor_pdb_to_pdbqt_for_vina → receptor.pdbqt
                                                                                   ↓
                                              perform_molecular_docking_vina(receptor, ligand, center, box)
```
