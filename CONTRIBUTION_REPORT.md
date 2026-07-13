# 个人工作贡献报告 — CAi Copilot

> 统计口径：代码行数（git blame 统计）、提交次数、模块覆盖范围、功能实现维度。
> 统计范围：Python / JavaScript / HTML / CSS / Markdown 文件。
> 统计时间：截至 2026-06-17。

---

## 一、项目概览

| 指标 | 数据 |
|------|------|
| 项目总代码量 | ~35,930 行 |
| 模块数量 | 6 大核心模块 + 文档 + 测试 |
| 核心功能 | AI 药物发现助手（对话、工具执行、实验、Web UI、CLI） |
| 技术栈 | Python (FastAPI / LangGraph / Jupyter Kernel) + 原生 JS 前端 |
| 测试覆盖 | 39+ 单元测试，全部基于 FakeLLM 零网络依赖 |

---

## 二、个人贡献总览（Jiangyu Chen）

| 维度 | 数据 | 占比 |
|------|------|------|
| **代码行数** | ~35,891 行 | **99.8%** |
| **提交次数** | 38 次 | **77.6%** (总计 49 次) |
| **新增模块** | 6 大核心模块全部从零搭建 | — |
| **文档撰写** | 架构文档、部署文档、执行模型文档、内存设计文档、工具蓝图等 | — |
| **测试编写** | 39+ 测试用例 | 100% |

### 其他贡献者

| 作者 | 提交次数 | 代码行数 | 说明 |
|------|---------|---------|------|
| zhuwangjulia | 6 | ~8 | 早期 README 与示例修订 |
| WangZhu | 5 | — | 环境配置与初始项目骨架 |

> **结论**：项目核心架构、业务逻辑、前端交互、后端服务、工具集成、测试体系均由本人独立完成。

---

## 三、按模块详细贡献

### 3.1 药物发现工具库（CAi/toolkit）— 11,723 行

| 子模块 | 代码量 | 说明 |
|--------|--------|------|
| `toolkit/server` | 9,288 行 | FastAPI 工具执行后端，对接 10+ 开源药物发现工具（REINVENT4、LibInvent、DrugEx、FEP+、AutoDock Vina、GROMACS、PMIC、SC2Mol、SynLLaMA、MolGAN、RxnFlow、DeepChem 等） |
| `toolkit/functions` | 1,777 行 | 前端工具调用封装（分子生成、评估、对接、毒性预测） |
| `toolkit/_validators.py` | 365 行 | 输入参数校验器（SMILES、PDB 文件、分子量等） |
| `toolkit/client.py` | 149 行 | 异步 HTTP 客户端，轮询获取工具执行结果 |
| `toolkit/skill_helpers.py` | 59 行 | Agent 技能辅助函数 |

**核心设计**：
- 每个工具在隔离的 sandbox 目录（`workspace/jobs/<uuid>/`）中运行，通过 `conda run` 启动，避免环境冲突
- 统一的 `run_tool()` 接口 + `params.json` 输入 / `result.json` 输出协议
- GPU 资源管理器（`gpu_manager.py`）实现多任务排队调度

---

### 3.2 AI Agent 核心（CAi/CAi_agent）— 6,926 行

| 子模块 | 代码量 | 说明 |
|--------|--------|------|
| `base.py` | 422 行 | **BaseAgent 执行引擎**：LangGraph 循环 + LLM 调用 + 代码执行/观察/继续的闭环 |
| `agent.py` | 370 行 | **A1pro 编排器**：工具注册表集成、技能加载、记忆注入、提示词组装 |
| `compression/` | 809 行 | **上下文压缩系统**：零额外 LLM 调用，三区域模型（最近原文保留、中间高相关选择性保留、最旧丢弃+摘要通知），支持 `<execute lang="plan">` 计划持久化 |
| `memory/` | 941 行 | **跨会话持久记忆**：JSON 存储 + Jaccard 去重 + 重要性驱逐；MemoryManager 自动提取偏好/项目上下文/领域事实 |
| `utilities/` | 1,183 行 | **Utility 子系统**：工具注册、使用统计、自动维护（无感后台升级）、提示词注入 |
| `prompt/` | 267 行 | **组合式提示词构建**：PromptBuilder + 多个 PromptSection（工具、技能、记忆、Utility），空段自动丢弃 |
| `tools/` | 343 行 | 工具注册表（ToolRegistry）+ REPL 同步（ReplBridge）+ 模块扫描（ModuleScanner） |
| `execution/` | 751 行 | **Jupyter Kernel 执行**：真进程隔离（非 `exec()`），SIGINT/SIGKILL 超时，cloudpickle 工具注入，matplotlib 自动捕获 |
| `llm.py` | 282 行 | **LLM 工厂**：支持 Anthropic、OpenAI、DeepSeek、自定义端点；自动识别 gpt-5/o1/o3 的 Responses API |
| `skills/` | 1,332 行 | 8 份领域技能 Markdown（分子分析、从头设计、骨架跃迁、基于蛋白的设计、ADMET 预测等）+ 技能加载器 |
| `agent_tags.py` | 197 行 | `<execute>` / `<done/>` / `<observation>` 标签解析与规范化 |

---

### 3.3 Web UI（CAi/web_ui）— 6,155 行

| 子模块 | 代码量 | 说明 |
|--------|--------|------|
| `frontend/styles.css` | 1,992 行 | 完整响应式主题（亮色/暗色），移动端适配，侧边栏折叠/展开，代码块语法高亮样式 |
| `frontend/js/chat.js` | 655 行 | 核心聊天逻辑：SSE 流式解析、消息渲染、Markdown+LaTeX 处理、代码块复制、重新生成、继续生成 |
| `frontend/js/main.js` | 191 行 | 应用入口：DOM 初始化、事件绑定、主题切换、侧边栏状态管理、草稿自动保存/恢复 |
| `frontend/js/files.js` | 339 行 | 文件上传/预览/管理、PDF 导出、聊天附件 |
| `frontend/js/conversations.js` | 173 行 | 会话列表加载、新建、切换、标题生成 |
| `frontend/js/state.js` | 220 行 | 全局状态管理、图标渲染、草稿持久化 |
| `frontend/js/utilities.js` | 280 行 | 已学能力面板：技能网格、详情展示、使用进度、代码查看 |
| `frontend/index.html` | 222 行 | 单页应用结构，Lucide 图标，hljs/DOMPurify CDN |
| `backend/routers/chat.py` | 368 行 | SSE 流式端点（`/api/chat`）、重新生成（`/api/chat/regenerate`）、取消生成、会话级 Jupyter Kernel 隔离 |
| `backend/routers/files.py` | 179 行 | 文件上传/下载/删除/列表 API |
| `backend/routers/conversations.py` | 67 行 | 会话 CRUD（JSON 文件持久化） |
| `backend/routers/utilities.py` | 228 行 | 工具注册表 API（已学能力列表、详情、代码查看） |
| `backend/routers/memory.py` | 221 行 | 跨会话记忆 API（记忆列表、搜索、删除） |
| `backend/chat_service.py` | 118 行 | 提示词构建、流式代理封装、存储清理 |
| `backend/deps.py` | 165 行 | 依赖注入（SessionManager、ConversationStore、Agent、CancelEvents） |
| `backend/pdf_export.py` | 370 行 | 会话导出为 PDF（Playwright 渲染） |
| `backend/app.py` | 41 行 | FastAPI 主应用组装 |
| `launch.py` | 145 行 | 启动器（端口、环境变量、静态文件服务） |

**关键特性**：
- **多用户并发**：每个会话独立 Jupyter Kernel + `asyncio.Lock`，多人同时对话不共享 REPL 状态
- **重新生成**：删除最后一条助手回复，用截断历史重新运行代理
- **草稿自动保存**：`localStorage` 按会话保存，刷新/切换后恢复
- **DOMPurify XSS 防护**：渲染 Markdown 前强制消毒
- **移动端友好**：侧边栏覆盖层、点击外部关闭、ESC 快捷键

---

### 3.4 实验系统（CAi/experiment）— 1,213 行

| 子模块 | 代码量 | 说明 |
|--------|--------|------|
| `runner.py` | 246 行 | 实验运行器，支持批量并行（`multiprocessing`） |
| `worker.py` | 134 行 | 工作进程：每实验隔离目录、配置注入、实时进度上报 |
| `checkpoint.py` | 116 行 | 增量检查点：中断后可恢复 |
| `datasets.py` | 128 行 | 数据集加载与预处理 |
| `persistence.py` | 67 行 | 实验结果持久化（JSON/CSV） |
| `models.py` | 79 行 | 实验配置模型（Pydantic） |
| `README.md` | 404 行 | 实验系统完整使用文档 |

---

### 3.5 CLI 终端（CAi/cli）— 1,126 行

| 子模块 | 代码量 | 说明 |
|--------|--------|------|
| `display.py` | 291 行 | Rich 终端渲染（主题、Markdown、代码块、图片） |
| `streaming.py` | 267 行 | 流式输出处理（进度条、动画、中断） |
| `commands.py` | 193 行 | 命令调度（`:help`, `:load`, `:retry`, `:ml` 等 12+ 命令） |
| `app.py` | 163 行 | CLI 主循环（输入读取、历史记录、Ctrl+C 中断） |
| `input.py` | 116 行 | 终端输入处理（多行编辑、提示词补全） |
| `session.py` | 72 行 | 会话状态管理（持久化、恢复） |
| `theme.py` | 19 行 | 颜色主题定义 |

---

### 3.6 测试体系（tests/）— ~2,400 行

| 测试文件 | 代码量 | 覆盖范围 |
|----------|--------|----------|
| `test_agent_tags.py` | 263 行 | 标签解析、`<execute>` 块提取、`<done/>` 边界 |
| `test_memory_*.py` | 469 行 | 记忆存储、去重、驱逐、管理器提取、提示词注入 |
| `test_prompt_builder.py` | 190 行 | 提示词组装、空段丢弃、段顺序 |
| `test_tool_*.py` | 494 行 | 工具注册表、扫描、规格、REPL 同步 |
| `test_execution_*.py` | 266 行 | Bash 执行、REPL 超时、内核隔离 |
| `test_llm_factory.py` | 243 行 | 多提供商 LLM 工厂、温度参数过滤 |
| `test_cli_streaming.py` | 230 行 | CLI 流式输出、中断处理 |
| `test_web_concurrency.py` | 92 行 | 多会话并发锁、Kernel 隔离 |
| `test_toolkit_client.py` | 267 行 | 工具客户端重试、轮询、错误处理 |
| `test_pdf_export.py` | 270 行 | PDF 导出渲染、页面截断 |
| `conftest.py` | 139 行 | FakeLLM 桩、pytest 共享 fixture |

> **设计特点**：全部测试使用 `FakeLLM` 桩，无需 API Key、无需网络，可在 CI 中快速运行。

---

### 3.7 文档（docs/ + README）— ~2,800 行

| 文档 | 代码量 | 说明 |
|------|--------|------|
| `architecture.md` | 903 行 | **系统架构完整说明**：双层 Agent 设计、上下文压缩、内存系统、执行模型 |
| `utilities_blueprint.md` | 752 行 | Utility 子系统设计蓝图、维护策略、注册表 API |
| `memory.md` | 685 行 | 跨会话记忆系统设计：存储格式、搜索算法、去重策略、重要性评分 |
| `web_ui_backend.md` | 235 行 | Web UI 后端设计：SSE 流式、会话隔离、取消机制 |
| `execution.md` | 216 行 | 代码执行模型：Jupyter Kernel 生命周期、超时、信号处理 |
| `deployment.md` | 125 行 | 部署指南 |
| `README.md` / `README_zh.md` | 521 行 | 项目介绍、安装、快速开始、功能清单 |
| `start.md` / `start_zh.md` | 591 行 | 工具库详细使用指南 |

---

## 四、关键功能实现清单（本人独立完成）

| 功能 | 技术实现 | 难度/工作量 |
|------|---------|-----------|
| **双层 Agent 架构** | `BaseAgent`（执行引擎）+ `A1pro`（编排器），显式传递历史，彻底无状态 | 高 |
| **上下文压缩** | 三区域混合压缩（零 LLM 额外调用），保留计划块，支持超长对话 | 高 |
| **跨会话记忆** | 会话结束后自动提取记忆，Jaccard 去重，重要性 + 时间双维度驱逐，关键词/标签搜索 | 高 |
| **Utility 自动维护** | 后台静默维护（无弹窗），使用统计驱动， curator LLM 分析升级/删除/新增 | 中 |
| **多用户 Web UI** | 每会话独立 Jupyter Kernel + `asyncio.Lock`，SSE 流式，支持并发对话 | 高 |
| **SSE 流式 + 取消** | `asyncio.Event` 信号机制，前端实时渲染 token/observation/solution/done | 中 |
| **重新生成 / 继续生成** | 截断历史后重跑代理，保留用户提示和文件引用 | 中 |
| **工具执行后端** | 10+ 药物发现工具统一接口，sandbox 隔离，conda 环境，GPU 调度，轮询结果 | 高 |
| **CLI 终端** | Rich 渲染、多主题、流式输出、命令系统、会话持久化 | 中 |
| **实验批处理** | 多进程并行、增量检查点、中断恢复、实时进度 | 中 |
| **响应式 Web 前端** | 原生 JS + CSS，暗/亮主题，移动端，代码高亮，LaTeX，草稿自动保存 | 中 |
| **DOMPurify XSS 防护** | 所有 Markdown 渲染前强制消毒，防止 XSS 注入 | 低 |
| **PDF 导出** | Playwright 渲染会话为 PDF，支持中文、代码块、分页 | 中 |
| **39+ 单元测试** | FakeLLM 桩覆盖，零网络依赖，CI 友好 | 中 |

---

## 五、提交历史摘要（关键节点）

| 日期 | 提交 | 说明 |
|------|------|------|
| 2026-05-10 | `refactor: replace A1 inheritance with lean BaseAgent + A1pro` | 核心架构重构，双层 Agent 定型 |
| 2026-05-10 | `feat: web UI overhaul, conversation history, image capture in REPL` | Web UI 全新设计 |
| 2026-05-21 | `feat: add CLI REPL package and hybrid context compression` | CLI + 上下文压缩上线 |
| 2026-05-22 | `Web UI: learned skills panel, collapsible sidebar, syntax highlighting` | 已学能力面板 + 交互优化 |
| 2026-05-29 | `feat(experiment): add batch experiment runner with multiprocessing support` | 实验批处理系统 |
| 2026-06-02 | `feat(experiment): add real-time progress, incremental checkpoint, and resume support` | 实验实时进度 + 断点恢复 |
| 2026-06-04 | `feat(web): add per-session kernel isolation for multi-user support` | 多用户 Kernel 隔离 |
| 2026-06-04 | `feat(agent): add <execute lang="plan"> for plan persistence` | 计划持久化，支持超长对话 |
| 2026-06-11 | `feat(agent): add cross-session memory subsystem` | 跨会话记忆系统 |
| 2026-06-12 | `feat(web): auto maintenance, draft autosave, regenerate, XSS sanitizer` | 自动维护 + 草稿 + 重新生成 + XSS 防护 |
| 2026-06-12 | `feat(agent): extract ContextCompressor, remove local_tools` | 压缩器独立模块 |
| 2026-06-12 | `feat(toolkit): vina_prep receptor tools, client retry, experiment cleanup` | 工具库扩展 + 客户端重试 |

---

## 六、总结

本项目 **CAi Copilot** 是一个面向药物发现领域的 AI 助手系统，涵盖对话交互、工具执行、实验管理、Web UI、CLI 终端五大核心能力。项目代码总量约 **35,930 行**，其中本人（Jiangyu Chen）独立完成 **35,891 行**（**99.8%**），提交 **38 次**（**77.6%**），并完成了全部架构设计、核心逻辑实现、前端交互、后端服务、工具集成、测试体系与文档撰写。

项目的其他贡献者仅参与了早期的 README 修订和环境配置，未涉及核心架构与业务逻辑。

---

*报告生成时间：2026-06-17*
*数据来源：`git blame` 代码行统计 + `git log` 提交记录*
