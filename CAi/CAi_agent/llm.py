"""
LLM factory — picks and configures a langchain chat model.

Supports four providers (keep this list intentionally small):

    - "OpenAI"      → langchain_openai.ChatOpenAI
    - "Anthropic"   → langchain_anthropic.ChatAnthropic
    - "DeepSeek"    → ChatOpenAI pointed at api.deepseek.com (OpenAI-compatible)
    - "Custom"      → ChatOpenAI pointed at any OpenAI-compatible base_url

Anything else raises a ValueError with a hint about how to use "Custom".
Auto-detection from model name handles the common cases so callers can
usually just pass `llm=<model>` without setting `source`.

API keys are read from the usual environment variables (OPENAI_API_KEY,
ANTHROPIC_API_KEY, DEEPSEEK_API_KEY) when not supplied explicitly.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

SourceType = Literal["OpenAI", "Anthropic", "DeepSeek", "Custom"]
ALLOWED_SOURCES: set[str] = set(SourceType.__args__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# Default timeouts / token caps — small enough to be safe, big enough to
# not clip real drug-discovery responses.
_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_MAX_TOKENS = 8192


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_llm(
    model: str | None = None,
    *,
    temperature: float | None = None,
    stop_sequences: list[str] | None = None,
    source: SourceType | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    request_timeout: float | None = None,
) -> BaseChatModel:
    """Return a configured langchain chat model.

    Args:
        model:          Model identifier (e.g. "gpt-4o-mini", "claude-sonnet-4-5",
                        "deepseek-chat", "qwen2.5-72b").
        temperature:    Sampling temperature. Default: 0.7.
        stop_sequences: Optional stop strings. BaseAgent passes ["</execute>"].
        source:         Override auto-detection. One of SourceType.
        base_url:       Required for source="Custom". Endpoint must be
                        OpenAI-compatible (/v1/chat/completions).
        api_key:        Overrides the environment variable for the chosen
                        provider. Pass "EMPTY" for local servers that
                        don't require auth.
        request_timeout: HTTP request timeout in seconds. When None, reads
                        ``LLM_REQUEST_TIMEOUT`` env var; if that is 0 or
                        unset, uses the SDK default (typically 600s for
                        streaming).

    Returns:
        A configured langchain chat model.

    Raises:
        ValueError:   Unknown source, or missing required config.
        ImportError:  langchain-openai / langchain-anthropic not installed.
    """
    if model is None:
        raise ValueError("model must be specified (e.g. 'gpt-4o-mini')")

    if temperature is None:
        temperature = _DEFAULT_TEMPERATURE

    source = source or _detect_source(model, base_url)

    # Resolve timeout: explicit arg > env var > SDK default
    if request_timeout is None:
        env_timeout = int(os.getenv("LLM_REQUEST_TIMEOUT", "0"))
        request_timeout = env_timeout if env_timeout > 0 else None

    if source == "OpenAI":
        return _build_openai(model, temperature, stop_sequences, api_key, request_timeout)
    if source == "Anthropic":
        return _build_anthropic(model, temperature, stop_sequences, api_key, request_timeout)
    if source == "DeepSeek":
        return _build_deepseek(model, temperature, stop_sequences, api_key, request_timeout)
    if source == "Custom":
        return _build_custom(model, temperature, stop_sequences, base_url, api_key, request_timeout)

    raise ValueError(
        f"Unknown LLM source: {source!r}. "
        f"Must be one of {sorted(ALLOWED_SOURCES)}."
    )


# ---------------------------------------------------------------------------
# Source detection
# ---------------------------------------------------------------------------


def _detect_source(model: str, base_url: str | None) -> SourceType:
    """Infer the provider from the model name (and base_url for Custom)."""
    env_source = os.getenv("LLM_SOURCE")
    if env_source in ALLOWED_SOURCES:
        return env_source  # type: ignore[return-value]

    name = model.lower()

    if name.startswith("claude-"):
        return "Anthropic"
    if name.startswith(("gpt-", "o1-", "o3-")):
        return "OpenAI"
    if name.startswith("deepseek"):
        # Covers "deepseek-chat", "deepseek-reasoner", etc.
        return "DeepSeek"
    if base_url:
        return "Custom"

    raise ValueError(
        f"Cannot auto-detect LLM source for model {model!r}. "
        "Pass source='Custom' with a base_url, or pick one of "
        f"{sorted(ALLOWED_SOURCES)}."
    )


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _build_openai(model, temperature, stop_sequences, api_key, request_timeout):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "langchain-openai is required for OpenAI models: "
            "pip install langchain-openai"
        ) from e

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError(
            "OpenAI requires OPENAI_API_KEY (env or api_key=...)."
        )

    # gpt-5 / o1 / o3 style models go through the Responses API and don't
    # accept `stop` or `temperature` — drop them for those.
    is_responses = model.startswith(("gpt-5", "o1-", "o3-"))

    if is_responses:
        return _ChatOpenAIResponsesNoStop(
            model=model,
            temperature=1,  # Required default for these models
            api_key=key,
            stop_sequences=stop_sequences,
            use_responses_api=True,
            output_version="v0",
            **({"request_timeout": request_timeout} if request_timeout else {}),
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=key,
        stop_sequences=stop_sequences,
        **({"request_timeout": request_timeout} if request_timeout else {}),
    )


def _build_anthropic(model, temperature, stop_sequences, api_key, request_timeout):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise ImportError(
            "langchain-anthropic is required for Claude models: "
            "pip install langchain-anthropic"
        ) from e

    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError(
            "Anthropic requires ANTHROPIC_API_KEY (env or api_key=...)."
        )

    return ChatAnthropic(
        model=model,
        temperature=temperature,
        max_tokens=_DEFAULT_MAX_TOKENS,
        api_key=key,
        stop_sequences=stop_sequences,
        **({"request_timeout": request_timeout} if request_timeout else {}),
    )


def _build_deepseek(model, temperature, stop_sequences, api_key, request_timeout):
    """DeepSeek exposes an OpenAI-compatible API at api.deepseek.com."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "langchain-openai is required for DeepSeek models: "
            "pip install langchain-openai"
        ) from e

    key = api_key or os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError(
            "DeepSeek requires DEEPSEEK_API_KEY (env or api_key=...)."
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=_DEFAULT_MAX_TOKENS,
        api_key=key,
        base_url=DEEPSEEK_BASE_URL,
        stop_sequences=stop_sequences,
        **({"request_timeout": request_timeout} if request_timeout else {}),
    )


def _build_custom(model, temperature, stop_sequences, base_url, api_key, request_timeout):
    """Any OpenAI-compatible endpoint: local SGLang / vLLM / corporate proxies."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "langchain-openai is required for Custom endpoints: "
            "pip install langchain-openai"
        ) from e

    if not base_url:
        raise ValueError(
            "source='Custom' requires base_url (e.g. http://localhost:8000/v1)."
        )

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=_DEFAULT_MAX_TOKENS,
        base_url=base_url,
        api_key=api_key or "EMPTY",
        stop_sequences=stop_sequences,
        **({"request_timeout": request_timeout} if request_timeout else {}),
    )


# ---------------------------------------------------------------------------
# Workaround: gpt-5 / o1 / o3 reject `stop` and `temperature`
# ---------------------------------------------------------------------------


def _ChatOpenAIResponsesNoStop(**kwargs):
    """Lazy constructor — we only need the subclass when the user actually
    picks a Responses-API model, and importing it otherwise pulls in extra
    langchain types we don't need."""
    from langchain_openai import ChatOpenAI

    class _Impl(ChatOpenAI):
        def _get_request_payload(self, input_, *, stop=None, **kw):  # type: ignore[override]
            payload = super()._get_request_payload(input_, stop=stop, **kw)
            try:
                if hasattr(self, "_use_responses_api") and self._use_responses_api(payload):
                    payload.pop("stop", None)
                    payload.pop("temperature", None)
            except Exception:
                # If anything about detection fails, be safe: drop both.
                payload.pop("stop", None)
                payload.pop("temperature", None)
            return payload

    return _Impl(**kwargs)
