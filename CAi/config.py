"""
Global configuration — all ports, hosts, and LLM parameters live here.

Two ways to override the defaults:
  1. Edit the defaults in this file (best for local development).
  2. Set the corresponding environment variable in CAi/.env (higher
     priority — recommended for deployment).

Env vars read here:
  TOOL_SERVER_HOST / TOOL_SERVER_PORT
  WEB_BACKEND_HOST / WEB_BACKEND_PORT
  WEB_FRONTEND_PORT
  LLM_MODEL / LLM_SOURCE / LLM_BASE_URL / LLM_API_KEY / LLM_TEMPERATURE
  CURATOR_MODEL / CURATOR_SOURCE / CURATOR_BASE_URL / CURATOR_API_KEY
      (override the LLM used by UtilityManager — defaults to LLM_*)
  OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY
      (read directly by CAi.CAi_agent.llm when LLM_SOURCE selects
       the corresponding provider)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env next to this file (CAi/.env)
load_dotenv(Path(__file__).parent / ".env")

# Repo root — one level above the CAi/ package.
WORKSPACE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# Ports
# =============================================================================

# CAi/toolkit/server/app.py — tool execution service
TOOL_SERVER_HOST = os.getenv("TOOL_SERVER_HOST", "0.0.0.0")
TOOL_SERVER_PORT = int(os.getenv("TOOL_SERVER_PORT", "8001"))

# CAi/web_ui/backend/app.py — Web UI backend (Vite proxies here in dev)
WEB_BACKEND_HOST = os.getenv("WEB_BACKEND_HOST", "0.0.0.0")
WEB_BACKEND_PORT = int(os.getenv("WEB_BACKEND_PORT", "8000"))

# CAi/main.py — Web UI server (FastAPI + static frontend)
# Default 7000 to avoid conflict with platform Jupyter Lab (typically on 8888)
WEB_UI_PORT = int(os.getenv("WEB_UI_PORT", "9966"))

# CAi/web_ui/frontend — Vite dev server (not used in production)
WEB_FRONTEND_PORT = int(os.getenv("WEB_FRONTEND_PORT", "3000"))


# =============================================================================
# LLM — main agent
# =============================================================================

# Model identifier. Shape depends on LLM_SOURCE:
#   Anthropic → claude-*
#   OpenAI    → gpt-*, o1-*, o3-*
#   DeepSeek  → deepseek-*
#   Custom    → whatever your OpenAI-compatible endpoint exposes
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-5-20250929")

# None → CAi.CAi_agent.llm auto-detects from the model name.
# Only set this explicitly if auto-detection fails (e.g. to force Custom
# for a model whose name doesn't match any prefix).
LLM_SOURCE: str | None = os.getenv("LLM_SOURCE") or None

# Only used when LLM_SOURCE == "Custom". Must be an OpenAI-compatible
# /v1 endpoint (SGLang / vLLM / corporate proxy).
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None

# Per-provider API keys:
#   - For Custom, pass LLM_API_KEY ("EMPTY" for unauthenticated local servers).
#   - For OpenAI / Anthropic / DeepSeek, the factory reads
#     OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY directly
#     when LLM_API_KEY is empty. Setting LLM_API_KEY overrides that.
LLM_API_KEY = os.getenv("LLM_API_KEY") or None

# Sampling temperature. Keep conservative for reproducibility.
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))

# HTTP request timeout (seconds) for LLM API calls.
# Long reasoning prompts with tool chains can easily exceed the default
# 600s from httpx. Set to 0 to use SDK defaults.
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "0"))


# =============================================================================
# LLM — curator (UtilityManager)
# =============================================================================
#
# The UtilityManager performs a single classification-style LLM call to
# decide whether a session's code should be saved/updated/deleted. This
# is much cheaper work than the main agent's reasoning, so a smaller /
# faster model is usually a better fit (e.g. gpt-4o-mini, deepseek-flash).
#
# Each CURATOR_* var falls back to its LLM_* counterpart when unset, so
# the default behaviour is "use the same model as the main agent" — set
# any subset of these to specialise.

CURATOR_MODEL = os.getenv("CURATOR_MODEL") or LLM_MODEL
CURATOR_SOURCE: str | None = os.getenv("CURATOR_SOURCE") or LLM_SOURCE
CURATOR_BASE_URL = os.getenv("CURATOR_BASE_URL") or LLM_BASE_URL
CURATOR_API_KEY = os.getenv("CURATOR_API_KEY") or LLM_API_KEY
CURATOR_TEMPERATURE = float(os.getenv("CURATOR_TEMPERATURE", "0.2"))


# =============================================================================
# Memory subsystem
# =============================================================================

MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() in ("true", "1", "yes")
MEMORY_DIR = WORKSPACE_DIR / "agent_workspace" / "_memory"
MEMORY_MAX_ENTRIES = int(os.getenv("MEMORY_MAX_ENTRIES", "100"))
