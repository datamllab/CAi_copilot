"""
Persistent Python REPL backed by a Jupyter kernel subprocess.

Replaces the previous exec()-based implementation. Key improvements:

  - True process isolation: the kernel runs in a separate process and can
    be interrupted via SIGINT or killed via SIGKILL on timeout — Python
    threads cannot be forcibly terminated, processes can.

  - Thread-safe output capture: stdout/stderr come back as ZeroMQ messages
    over the Jupyter wire protocol, not via sys.stdout replacement.

  - Real timeout enforcement: run_python_repl() sends an interrupt to the
    kernel when the deadline elapses, then restarts if unresponsive.

Multi-user support:
  Each ``KernelSession`` owns an independent Jupyter kernel subprocess.
  The module-level functions delegate to a default session for backward
  compatibility (CLI, single-user web UI). For multi-user scenarios,
  create a ``KernelSession`` per conversation and pass it to
  ``BaseAgent(kernel_session=...)``.
"""

from __future__ import annotations

import atexit
import builtins
import logging
import os
import queue
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime

logger = logging.getLogger("CAi.execution.repl")

# Name of the builtins attribute used as a cross-module registry of agent
# tools. Must match ReplBridge / tools.repl_bridge.
_CUSTOM_FNS_ATTR = "_base_CAi_custom_functions"

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".svg", ".gif", ".bmp", ".webp", ".tiff"})

# ---------------------------------------------------------------------------
# KernelSession — independent Jupyter kernel per conversation
# ---------------------------------------------------------------------------


class KernelSession:
    """An independent Jupyter kernel subprocess with its own namespace,
    workspace directory, and utility monitoring state.

    Used by ``BaseAgent`` for code execution. The default single-user
    path uses the module-level default session; multi-user callers
    create one ``KernelSession`` per conversation.
    """

    def __init__(self, workspace_dir: str | None = None, timeout: int = 600) -> None:
        self._workspace_dir: str | None = workspace_dir
        self._default_timeout: int = timeout

        # Kernel manager + client — lazily initialised.
        self._km = None   # jupyter_client.KernelManager
        self._kc = None   # jupyter_client.BlockingKernelClient
        self._kernel_lock = threading.Lock()
        self._atexit_registered = False

        # Utility monitoring state (per-session).
        self._session_usage: dict[str, dict] = {}
        self._utilities_injected: bool = False
        self._injected_utility_names: list[str] = []
        self._injected_utilities: dict[str, Callable] = {}

        # Register atexit handler for this session.
        atexit.register(self.shutdown)

    # ------------------------------------------------------------------
    # Public API — mirrors the module-level functions
    # ------------------------------------------------------------------

    def run_python(self, code: str, timeout: float | None = None) -> str:
        """Execute ``code`` in the persistent kernel; return captured output.

        On timeout: interrupts the kernel (SIGINT), drains remaining messages,
        and returns a "TIMEOUT: ..." string.  If the kernel becomes unresponsive
        after the interrupt, it is restarted automatically.

        After execution any new image files created in the workspace are detected
        and reported, and open matplotlib figures are auto-saved.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        code = (code or "").strip("`").strip()
        if not code:
            return ""

        # Sync any tools registered on builtins since last call.
        self._sync_builtins_to_kernel()

        # Snapshot existing images before execution.
        images_before = self._snapshot_workspace_images()

        kc = self._get_or_start_kernel()
        output, error = self._execute_in_kernel(kc, code, timeout=effective_timeout)

        # Auto-capture matplotlib figures and detect new workspace images.
        saved_plots = self._capture_plots(kc)
        new_images = self._detect_new_images(images_before)
        all_images = list(dict.fromkeys(saved_plots + new_images))

        result = output
        if error:
            result = result + error if result else error
        if all_images:
            result += "\n" + "\n".join(f"[Image saved]: {p}" for p in all_images) + "\n"

        # Collect utility usage stats from kernel (non-blocking, never affects result).
        if self._utilities_injected:
            try:
                import json as _json_mod  # noqa: PLC0415
                collect_code = (
                    "import json as _json; "
                    "print('__UTIL_USAGE__:' + _json.dumps(dict(_utility_usage))); "
                    "_utility_usage.clear()"
                )
                usage_out, _ = self._execute_in_kernel(kc, collect_code, timeout=5)
                if usage_out:
                    for line in usage_out.splitlines():
                        if line.startswith("__UTIL_USAGE__:"):
                            data = _json_mod.loads(line[len("__UTIL_USAGE__:"):])
                            self._accumulate_utility_usage(data)
                            break
            except Exception:
                pass  # Monitoring failure must never affect normal execution

        return result

    def set_workspace(self, path: str) -> None:
        """Configure where auto-captured plots are saved and set the kernel cwd."""
        self._workspace_dir = path
        os.makedirs(path, exist_ok=True)
        try:
            kc = self._get_or_start_kernel()
            self._execute_in_kernel(kc, f"import os as _os; _os.chdir({path!r}); del _os", timeout=10)
        except Exception:
            pass  # Best-effort; will be applied at next kernel init

    def inject_tools(self, custom_functions: dict[str, Callable] | None) -> None:
        """Inject tool functions into the kernel namespace and the builtins registry.

        Uses cloudpickle so closures and locally-defined callables work.
        """
        if not custom_functions:
            return

        # Always update the process-side builtins registry.
        registry = getattr(builtins, _CUSTOM_FNS_ATTR, None)
        if registry is None:
            registry = {}
            setattr(builtins, _CUSTOM_FNS_ATTR, registry)
        registry.update(custom_functions)

        # Inject into this session's kernel via cloudpickle.
        self._inject_into_kernel(custom_functions)

    def sync_builtins(self) -> None:
        """Inject any tools registered on builtins since the last call."""
        registry = getattr(builtins, _CUSTOM_FNS_ATTR, None)
        if registry:
            self._inject_into_kernel(registry)

    def inject_utilities(self, utilities: dict[str, Callable]) -> None:
        """Inject utilities into kernel with monitoring wrappers."""
        if not utilities:
            return

        self._injected_utilities = dict(utilities)

        # Step 1: inject raw functions directly into kernel.
        self._inject_into_kernel(utilities)

        # Step 2: inject monitoring bootstrap.
        kc = self._get_or_start_kernel()
        bootstrap = (
            "import functools as _functools\n"
            "_utility_usage = {}\n"
            "def _monitor_utility(func, name):\n"
            "    @_functools.wraps(func)\n"
            "    def wrapper(*args, **kwargs):\n"
            "        entry = _utility_usage.setdefault(name, {'calls': 0, 'errors': 0})\n"
            "        entry['calls'] += 1\n"
            "        try:\n"
            "            return func(*args, **kwargs)\n"
            "        except Exception:\n"
            "            entry['errors'] += 1\n"
            "            raise\n"
            "    return wrapper\n"
        )
        self._execute_in_kernel(kc, bootstrap, timeout=10)

        # Step 3: wrap each utility with the monitor.
        names = list(utilities.keys())
        for name in names:
            self._execute_in_kernel(kc, f"{name} = _monitor_utility({name}, {name!r})", timeout=5)

        self._utilities_injected = True
        self._injected_utility_names = names

    def reset_namespace(self) -> None:
        """Clear the persistent REPL namespace."""
        try:
            kc = self._get_or_start_kernel()
            self._execute_in_kernel(kc, "%reset -f", timeout=15)
        except Exception as exc:
            logger.warning("reset_namespace: %s", exc)

    def flush_utility_usage(self) -> dict[str, dict]:
        """Return accumulated utility usage and reset."""
        result = self._session_usage
        self._session_usage = {}
        return result

    def shutdown(self) -> None:
        """Gracefully shut down the kernel."""
        km, kc = self._km, self._kc
        self._km = self._kc = None
        if kc is not None:
            try:
                kc.stop_channels()
            except Exception:
                pass
        if km is not None:
            try:
                km.shutdown_kernel(now=True)
            except Exception:
                pass

    @property
    def workspace_dir(self) -> str | None:
        return self._workspace_dir

    # ------------------------------------------------------------------
    # Kernel lifecycle (internal)
    # ------------------------------------------------------------------

    def _get_or_start_kernel(self):
        """Return the live kernel client, starting the kernel if needed."""
        with self._kernel_lock:
            if self._km is None or not self._km.is_alive():
                self._start_kernel()
        return self._kc

    def _start_kernel(self) -> None:
        """Start a fresh IPython kernel and prime its environment."""
        from jupyter_client import KernelManager  # noqa: PLC0415

        logger.debug("Starting Jupyter kernel...")
        km = KernelManager(kernel_name="python3")
        km.start_kernel()
        kc = km.blocking_client()
        kc.start_channels()
        try:
            kc.wait_for_ready(timeout=30)
        except RuntimeError as exc:
            km.shutdown_kernel(now=True)
            raise RuntimeError(f"Jupyter kernel failed to start: {exc}") from exc

        self._km = km
        self._kc = kc
        logger.debug("Kernel started")
        self._init_kernel_env(kc)

    def _init_kernel_env(self, kc) -> None:
        """Run one-time setup code in a freshly started kernel."""
        setup_lines = [
            "import os, sys, warnings",
            "warnings.filterwarnings('ignore', message='Glyph .* missing from font', category=UserWarning)",
            "try:\n    import matplotlib\n    matplotlib.use('Agg')\nexcept ImportError:\n    pass",
        ]

        setup_lines.append(
            "\n".join([
                "try:",
                "    import matplotlib",
                "    from matplotlib import font_manager as _fm",
                "    _candidates = ['Microsoft YaHei','SimHei','PingFang SC','Heiti SC',",
                "        'Noto Sans CJK SC','Noto Sans CJK JP','Source Han Sans SC',",
                "        'WenQuanYi Micro Hei','Arial Unicode MS']",
                "    _installed = {f.name for f in _fm.fontManager.ttflist}",
                "    _pick = next((c for c in _candidates if c in _installed), None)",
                "    _existing = list(matplotlib.rcParams.get('font.sans-serif', []))",
                "    if _pick and _pick not in _existing:",
                "        matplotlib.rcParams['font.sans-serif'] = [_pick] + _existing",
                "    matplotlib.rcParams['axes.unicode_minus'] = False",
                "    del _fm, _candidates, _installed, _pick, _existing",
                "except Exception:",
                "    pass",
            ])
        )

        if self._workspace_dir:
            setup_lines.append(f"os.chdir({self._workspace_dir!r})")

        self._execute_in_kernel(kc, "\n".join(setup_lines), timeout=30)
        self._reinject_monitoring_bootstrap()

    def _reinject_monitoring_bootstrap(self) -> None:
        """Re-inject monitoring bootstrap and utilities after kernel restart."""
        if not self._utilities_injected or not self._injected_utility_names:
            return

        kc = self._get_or_start_kernel()

        if self._injected_utilities:
            self._inject_into_kernel(self._injected_utilities)

        bootstrap = (
            "import functools as _functools\n"
            "_utility_usage = {}\n"
            "def _monitor_utility(func, name):\n"
            "    @_functools.wraps(func)\n"
            "    def wrapper(*args, **kwargs):\n"
            "        entry = _utility_usage.setdefault(name, {'calls': 0, 'errors': 0})\n"
            "        entry['calls'] += 1\n"
            "        try:\n"
            "            return func(*args, **kwargs)\n"
            "        except Exception:\n"
            "            entry['errors'] += 1\n"
            "            raise\n"
            "    return wrapper\n"
        )
        self._execute_in_kernel(kc, bootstrap, timeout=10)

        for name in self._injected_utility_names:
            self._execute_in_kernel(
                kc,
                f"{name} = _monitor_utility({name}, {name!r})",
                timeout=5,
            )

    def _restart_kernel(self) -> None:
        """Restart the kernel and re-initialise its environment."""
        km, old_kc = self._km, self._kc
        if old_kc is not None:
            try:
                old_kc.stop_channels()
            except Exception:
                pass
        if km is not None:
            try:
                km.restart_kernel(now=True)
                new_kc = km.blocking_client()
                new_kc.start_channels()
                new_kc.wait_for_ready(timeout=30)
                self._kc = new_kc
                self._init_kernel_env(new_kc)
                logger.info("Kernel restarted successfully")
            except Exception as exc:
                logger.error("Kernel restart failed: %s — starting fresh", exc)
                self._km = self._kc = None
                self._start_kernel()

    # ------------------------------------------------------------------
    # Core kernel execution (internal)
    # ------------------------------------------------------------------

    def _execute_in_kernel(self, kc, code: str, timeout: float) -> tuple[str, str]:
        """Send ``code`` to the kernel; collect and return (stdout_text, error_text).

        On timeout: sends SIGINT, drains remaining output, restarts if needed.
        Never raises — errors and timeouts are returned as strings.
        """
        try:
            msg_id = kc.execute(code)
        except Exception as exc:
            return "", f"Error: failed to send code to kernel: {exc}"

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        error_text: str = ""
        deadline = time.monotonic() + timeout
        timed_out = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not timed_out:
                timed_out = True
                self._handle_timeout(kc, timeout)
                remaining = 3.0

            try:
                msg = kc.get_iopub_msg(timeout=min(max(remaining, 0.05), 1.0))
            except queue.Empty:
                if timed_out:
                    break
                continue
            except Exception:
                break

            msg_type = msg.get("msg_type", "")
            content = msg.get("content", {})

            if msg_type == "stream":
                if content.get("name") == "stdout":
                    stdout_parts.append(content.get("text", ""))
                else:
                    stderr_parts.append(content.get("text", ""))
            elif msg_type == "execute_result":
                text = content.get("data", {}).get("text/plain", "")
                if text:
                    stdout_parts.append(text + "\n")
            elif msg_type == "error":
                tb_lines = content.get("traceback", [])
                clean_tb = "\n".join(_ANSI_ESCAPE.sub("", line) for line in tb_lines)
                ename = content.get("ename", "Error")
                evalue = content.get("evalue", "")
                error_text = f"Error: {ename}: {evalue}\n{clean_tb}".rstrip()
            elif msg_type == "status":
                if content.get("execution_state") == "idle":
                    break

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts).strip()
        if stderr:
            stdout = stdout + ("\n" if stdout else "") + stderr + "\n"
        if timed_out and not error_text:
            error_text = f"TIMEOUT: Code execution timed out after {timeout} seconds"

        return stdout, error_text

    def _handle_timeout(self, kc, timeout: float) -> None:
        """Interrupt the kernel; restart it if it stays unresponsive."""
        km = self._km
        if km is None:
            return
        logger.warning("Execution timed out after %ss — interrupting kernel", timeout)
        try:
            km.interrupt_kernel()
        except Exception as exc:
            logger.warning("interrupt_kernel failed: %s", exc)

        try:
            kc.kernel_info(reply=True, timeout=5)
        except Exception:
            logger.warning("Kernel unresponsive after interrupt — restarting")
            self._restart_kernel()

    # ------------------------------------------------------------------
    # Tool injection (internal)
    # ------------------------------------------------------------------

    def _inject_into_kernel(self, funcs: dict[str, Callable]) -> None:
        """Serialize ``funcs`` with cloudpickle and inject them into the kernel."""
        try:
            import base64  # noqa: PLC0415
            import cloudpickle  # noqa: PLC0415
        except ImportError:
            logger.warning("cloudpickle not installed — skipping tool injection into kernel")
            return

        try:
            payload = base64.b64encode(cloudpickle.dumps(funcs)).decode()
        except Exception as exc:
            logger.warning("cloudpickle serialisation failed: %s", exc)
            return

        inject_code = (
            "import cloudpickle as _cp, base64 as _b64\n"
            f"globals().update(_cp.loads(_b64.b64decode({payload!r})))\n"
            "del _cp, _b64"
        )
        kc = self._get_or_start_kernel()
        self._execute_in_kernel(kc, inject_code, timeout=15)

    def _sync_builtins_to_kernel(self) -> None:
        """Inject any tools registered on builtins since the last call."""
        registry = getattr(builtins, _CUSTOM_FNS_ATTR, None)
        if registry:
            self._inject_into_kernel(registry)

    # ------------------------------------------------------------------
    # Matplotlib plot capture (internal)
    # ------------------------------------------------------------------

    def _capture_plots(self, kc) -> list[str]:
        """Save all open matplotlib figures in the kernel to workspace."""
        save_dir = self._workspace_dir or os.getcwd()
        os.makedirs(save_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        capture_code = "\n".join([
            "try:",
            "    import matplotlib.pyplot as _plt",
            "    _fignums = _plt.get_fignums()",
            "    _saved = []",
            "    for _i, _n in enumerate(_fignums):",
            f"        _fp = {save_dir!r} + '/' + f'plot_{timestamp}_{{_i}}.png'",
            "        try:",
            "            _plt.figure(_n).savefig(_fp, dpi=150, bbox_inches='tight', facecolor='white')",
            "            _saved.append(_fp)",
            "        except Exception:",
            "            pass",
            "    _plt.close('all')",
            "    print('\\n'.join(_saved))",
            "    del _plt, _fignums, _saved, _i, _n, _fp",
            "except ImportError:",
            "    pass",
        ])
        stdout, _ = self._execute_in_kernel(kc, capture_code, timeout=15)
        return [
            p.strip() for p in stdout.splitlines()
            if p.strip() and os.path.splitext(p.strip())[1].lower() in _IMAGE_EXTENSIONS
        ]

    def _snapshot_workspace_images(self) -> set[str]:
        save_dir = self._workspace_dir
        if not save_dir or not os.path.isdir(save_dir):
            return set()
        result: set[str] = set()
        try:
            for f in os.listdir(save_dir):
                if os.path.splitext(f)[1].lower() in _IMAGE_EXTENSIONS:
                    result.add(os.path.join(save_dir, f))
        except OSError:
            pass
        return result

    def _detect_new_images(self, before: set[str]) -> list[str]:
        save_dir = self._workspace_dir
        if not save_dir or not os.path.isdir(save_dir):
            return []
        after: set[str] = set()
        try:
            for f in os.listdir(save_dir):
                if os.path.splitext(f)[1].lower() in _IMAGE_EXTENSIONS:
                    after.add(os.path.join(save_dir, f))
        except OSError:
            return []
        return sorted(after - before)

    # ------------------------------------------------------------------
    # Utility monitoring (internal)
    # ------------------------------------------------------------------

    def _accumulate_utility_usage(self, kernel_usage: dict) -> None:
        """Merge kernel-reported usage into session accumulator."""
        for name, stats in kernel_usage.items():
            entry = self._session_usage.setdefault(name, {"calls": 0, "errors": 0})
            entry["calls"] += stats.get("calls", 0)
            entry["errors"] += stats.get("errors", 0)


# ---------------------------------------------------------------------------
# Default session — backward compatibility for CLI & single-user
# ---------------------------------------------------------------------------

_default_session = KernelSession()


def run_python_repl(code: str, timeout: float = 600) -> str:
    """Execute code in the default kernel session. Backward-compatible."""
    return _default_session.run_python(code, timeout=timeout)


def set_workspace_dir(path: str) -> None:
    """Configure workspace for the default session. Backward-compatible."""
    _default_session.set_workspace(path)


def inject_custom_functions(custom_functions: dict[str, Callable] | None) -> None:
    """Inject tools into the default session. Backward-compatible."""
    _default_session.inject_tools(custom_functions)


def inject_utilities_with_monitoring(utilities: dict[str, Callable]) -> None:
    """Inject utilities into the default session with monitoring. Backward-compatible."""
    _default_session.inject_utilities(utilities)


def flush_utility_usage() -> dict[str, dict]:
    """Flush utility usage from the default session. Backward-compatible."""
    return _default_session.flush_utility_usage()


def reset_namespace() -> None:
    """Reset the default session namespace. Backward-compatible."""
    _default_session.reset_namespace()
