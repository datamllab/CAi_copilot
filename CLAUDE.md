# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run all tests (no API keys needed — uses FakeLLM stubs)
pytest

# Run a single test file
pytest tests/test_prompt_builder.py

# Lint
ruff check .

# Start tool backend (from repo root)
python -m CAi.toolkit.server.app

# Launch agent Web UI
python CAi/main.py --port 7000

# Launch agent CLI REPL
python CAi/main.py --cli
```

## Architecture

Two-layer agent design. `BaseAgent` is the execution engine (LangGraph loop + LLM + Jupyter-kernel REPL). `A1pro` extends it with domain tools, skills, and prompt composition. Both are stateless — conversation history is passed explicitly by callers via `run_with_history_streaming(prompt, history)`.

```
BaseAgent  (core: generate→execute→generate loop + LLM + REPL)
    ├── context_compression.py  (hybrid partition for long conversations)
    └── A1pro  (orchestrator: tools + skills + prompt sections)
              ├── memory/       (MemoryStore + MemoryManager — cross-session persistent memory)
              ├── cli/         (terminal REPL: theme, display, streaming, commands)
              └── Web UI  (FastAPI + static frontend)
```

### Core interaction model

The agent can mix text and code in a single response. Code goes in `<execute>...</execute>` blocks (Python by default, `#!BASH` prefix for shell). The loop runs: LLM generates → code blocks extracted and run → output injected as `<observation>` → LLM continues. The agent signals completion with `<done/>`.

### Key subsystems

- **`CAi/CAi_agent/llm.py`** — LLM factory supporting Anthropic, OpenAI, DeepSeek, and Custom (any OpenAI-compatible endpoint). Auto-detects provider from model name prefix. Special handling for gpt-5/o1/o3 (Responses API, no `stop`/`temperature`).
- **`CAi/CAi_agent/context_compression.py`** — Hybrid partition strategy for long conversations. Three-zone model: recent verbatim, middle high-score selective, oldest dropped with summary notice. Zero extra LLM calls.
- **`CAi/CAi_agent/memory/`** — Cross-session persistent memory. `MemoryStore` (JSON-backed, keyword+tag search, Jaccard dedup, importance eviction). `MemoryManager` (curator LLM auto-extracts preferences/project context/domain facts from session logs). `MemorySection` (PromptSection injecting relevant memories into agent prompt).
- **`CAi/CAi_agent/execution/repl.py`** — Python execution via a Jupyter IPython kernel subprocess (not exec()). True process isolation, SIGINT/SIGKILL timeout enforcement, cloudpickle-based tool injection, matplotlib figure auto-capture.
- **`CAi/CAi_agent/prompt/`** — Composition-based prompt building. Each section is a `PromptSection` subclass. `PromptBuilder.add()` assembles them; empty sections are silently dropped. `ToolsSection` reads from `ToolRegistry` (hides `hidden` tools). `SkillsSection` reads from `SkillLoader`.
- **`CAi/CAi_agent/tools/`** — `ToolSpec.from_function(func)` extracts name/signature/docstring. `ToolRegistry` is observable (`on_change` callbacks). `ModuleScanner` discovers top-level functions from a Python module. `ReplBridge` syncs the registry into the REPL's `builtins`.
- **`CAi/cli/`** — Terminal REPL with rich theming, streaming output, command dispatch (`:help`, `:load`, `:retry`, `:ml`, etc.), conversation persistence, and Ctrl+C interrupt handling. Modular package: `app.py`, `commands.py`, `display.py`, `input.py`, `session.py`, `streaming.py`, `theme.py`.
- **`CAi/toolkit/`** — Drug discovery tools. Wrapper functions in `functions/{generation,evaluation}.py` call `run_tool()` from `client.py`, which POSTs to the tool server, then polls for results.
- **`CAi/toolkit/server/`** — FastAPI tool execution backend. Jobs run in isolated sandbox directories (`workspace/jobs/<uuid>/`). Tools execute via `conda run -n <env> python run.py` with stdin=params.json, output=result.json.

### Web UI

Static HTML/JS/CSS frontend served alongside a FastAPI backend. SSE streaming (`POST /api/chat`), conversation persistence as JSON files (`ConversationStore`), cancel support via `asyncio.Event`. Chat requests are serialized via `asyncio.Lock` because the REPL kernel is shared. See `docs/web_ui_backend.md` for rationale.

### Configuration

All config in `CAi/config.py`, loaded from `CAi/.env`. `LLM_MODEL` determines the provider; override with `LLM_SOURCE`. CLI flags (`--port`, `--model`, `--source`, `--base-url`, `--api-key`, `--temperature`) override env vars.

### Testing

All tests use `FakeLLM` from `conftest.py` — no network, no API keys. The `fake_llm_factory` fixture patches `get_llm` to return scripted responses. Key invariants exercised: stateless agent (history passed explicitly, no cross-call leaks), `<done/>` doesn't bleed into output fields, tool docstrings truncated before `Args:`, registry observers are fail-isolated, hidden tools injected into REPL but excluded from prompt catalog, memory dedup merges similar entries, memory eviction respects importance + recency.
