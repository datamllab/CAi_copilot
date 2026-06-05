"""CAi — entry point.

Reads configuration from CAi/config.py (which loads CAi/.env), builds
an A1pro agent, and launches the Web UI or CLI REPL. Provider
auto-detection happens inside A1pro based on LLM_MODEL; override it
by setting LLM_SOURCE in the .env file.

CLI usage examples:
  python -m CAi.main                          # Web UI (default)
  python -m CAi.main --port 9000
  python -m CAi.main --cli                    # Interactive CLI REPL
  python -m CAi.main --cli --resume abc123    # Resume a conversation
"""

# Silence a benign langgraph 0.6 deprecation notice about `allowed_objects`.
# Must run before importing langgraph (indirectly via CAi.CAi_agent).
import warnings

warnings.filterwarnings(
    "ignore",
    message=".*allowed_objects.*",
    category=Warning,
)

import argparse
import socket
import sys

from CAi.CAi_agent import A1pro
from CAi.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_SOURCE,
    LLM_TEMPERATURE,
    WEB_UI_PORT,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m CAi.main",
        description="Launch the CAi Web UI or CLI REPL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port", type=int, default=WEB_UI_PORT,
        help="Port to serve the Web UI on.",
    )
    parser.add_argument(
        "--model", default=LLM_MODEL,
        help="LLM model identifier (overrides LLM_MODEL in .env).",
    )
    parser.add_argument(
        "--source", default=LLM_SOURCE,
        help="LLM provider (Anthropic/OpenAI/DeepSeek/Custom). None = auto-detect.",
    )
    parser.add_argument(
        "--base-url", default=LLM_BASE_URL, dest="base_url",
        help="OpenAI-compatible base URL for Custom provider.",
    )
    parser.add_argument(
        "--api-key", default=LLM_API_KEY, dest="api_key",
        help="API key (overrides LLM_API_KEY in .env).",
    )
    parser.add_argument(
        "--temperature", type=float, default=LLM_TEMPERATURE,
        help="Sampling temperature.",
    )
    parser.add_argument(
        "--cli", action="store_true", default=False,
        help="Start interactive CLI REPL instead of Web UI.",
    )
    parser.add_argument(
        "--resume", default=None,
        help="CLI mode: resume conversation by conv_id.",
    )
    return parser.parse_args()


def _startup_summary(args: argparse.Namespace) -> None:
    """Print effective LLM config before anything else, so if the agent
    fails to initialise the user can see which knobs were read."""
    print("=" * 50)
    print("CAi starting with:")
    print(f"  LLM_MODEL       = {args.model!r}")
    print(f"  LLM_SOURCE      = {args.source!r}  (None = auto-detect)")
    print(f"  LLM_BASE_URL    = {args.base_url!r}")
    print(f"  LLM_API_KEY     = {'<set>' if args.api_key else '<EMPTY — requests will 401>'}")
    print(f"  LLM_TEMPERATURE = {args.temperature}")
    if args.cli:
        print("  MODE            = CLI REPL")
        if args.resume:
            print(f"  RESUME          = {args.resume}")
    else:
        print(f"  PORT            = {args.port}")
    print("=" * 50)


def _check_port_free(port: int) -> None:
    """Fail fast with a clear message if the target port is already in use.

    Uvicorn will also fail, but its default message is easy to miss in a
    busy terminal. This check runs before agent initialisation so users
    don't wait for tool loading only to hit a port conflict afterwards.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        print(
            f"\n❌ Port {port} is already in use.\n\n"
            f"Likely a previous CAi run didn't shut down cleanly.\n"
            f"Find and stop the process, then retry:\n"
            f"  PowerShell:\n"
            f"    Get-NetTCPConnection -LocalPort {port} -State Listen |\n"
            f"      ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}\n"
            f"  Linux/macOS:\n"
            f"    lsof -ti tcp:{port} | xargs -r kill -9\n",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        s.close()


def main() -> None:
    args = _parse_args()
    _startup_summary(args)
    if not args.cli:
        _check_port_free(args.port)
    try:
        agent = A1pro(
            llm=args.model,
            source=args.source,
            base_url=args.base_url,
            api_key=args.api_key,
            temperature=args.temperature,
        )
    except Exception as e:
        print(f"\n❌ Agent initialisation failed: {type(e).__name__}: {e}", file=sys.stderr)
        print(
            "\nCheck CAi/.env — common causes:\n"
            "  - LLM_MODEL prefix doesn't match a known provider AND LLM_BASE_URL is empty.\n"
            "  - A real provider (claude-* / gpt-* / deepseek-*) was detected but the\n"
            "    matching API key env var (ANTHROPIC_API_KEY / OPENAI_API_KEY /\n"
            "    DEEPSEEK_API_KEY) is missing.\n"
            "  - Force provider by setting LLM_SOURCE=Custom and providing LLM_BASE_URL.",
            file=sys.stderr,
        )
        raise

    if args.cli:
        from CAi.cli import launch_cli
        launch_cli(agent, resume_conv_id=args.resume)
    else:
        # Launch the Web UI (FastAPI + static frontend). See CAi/web_ui/launch.py.
        agent.launch_web_ui(port=args.port)


if __name__ == "__main__":
    main()
