"""
Launch the CAi Web UI (FastAPI backend + static frontend).

Usage:
    python -m CAi.web_ui.launch
"""

import socket
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


# Paths the SPA catch-all must NOT intercept. Anything starting with
# one of these is owned by FastAPI itself or by us as an API route.
_API_RESERVED_PREFIXES = (
    "api/",          # Our /api/* endpoints
    "docs",          # FastAPI swagger UI (GET /docs)
    "redoc",         # FastAPI ReDoc UI
    "openapi.json",  # FastAPI OpenAPI schema
    "static/",       # StaticFiles mount
)


def launch(agent, host: str = "0.0.0.0", port: int = 7000) -> None:
    """
    Launch the Web UI with the given agent.

    Args:
        agent: A1pro agent instance.
        host:  Server host.
        port:  Server port.
    """
    from CAi.web_ui.backend.app import app, set_agent

    set_agent(agent)

    frontend_dir = Path(__file__).parent / "frontend"
    if not frontend_dir.exists():
        raise FileNotFoundError(f"Frontend dir missing: {frontend_dir}")

    # Serve styles.css / app.js / images / etc. under /static/*
    app.mount(
        "/static",
        StaticFiles(directory=str(frontend_dir)),
        name="static",
    )

    index_file = frontend_dir / "index.html"

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(index_file))

    # Favicon: the browser asks for this on every page load. Without an
    # explicit handler the SPA catch-all would return index.html with
    # content-type text/html, polluting the Network panel with noise.
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        ico = frontend_dir / "favicon.ico"
        if ico.exists():
            return FileResponse(str(ico))
        # 204 — no icon, don't keep trying.
        from fastapi.responses import Response
        return Response(status_code=204)

    # SPA fallback — must be registered LAST and must explicitly skip
    # paths owned by FastAPI's own routes (/docs, /openapi.json, /api/*).
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Don't shadow API / docs / static — let FastAPI's 404 fire.
        if any(full_path.startswith(prefix) for prefix in _API_RESERVED_PREFIXES):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")

        # If it's a real file under frontend/, serve it verbatim.
        candidate = frontend_dir / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))

        # Otherwise assume it's a client-side route — hand back index.html.
        return FileResponse(str(index_file))

    _print_banner(host, port)
    uvicorn.run(app, host=host, port=port)


def _print_banner(host: str, port: int) -> None:
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    bar = "=" * 50
    print(f"\n{bar}")
    print("🚀 CAi Web UI")
    print(bar)
    print(f"   Frontend: http://{display_host}:{port}")
    print(f"   API docs: http://{display_host}:{port}/docs")
    print(f"   Health:   http://{display_host}:{port}/api/health")
    # Show LAN IPs when listening on all interfaces
    if host in ("0.0.0.0", "::"):
        _lan_ips = _get_lan_ips()
        if _lan_ips:
            print(f"   LAN:      {'  '.join(f'http://{ip}:{port}' for ip in _lan_ips)}")
    print(f"{bar}\n")


def _get_lan_ips() -> list[str]:
    """Return non-loopback IPv4 addresses for LAN sharing hints."""
    ips: list[str] = []
    try:
        # Get all interfaces via socket, filter non-loopback.
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith("127."):
                ips.append(addr)
    except Exception:
        pass
    # Deduplicate while preserving order.
    seen: set[str] = set()
    return [ip for ip in ips if not (ip in seen or seen.add(ip))]


if __name__ == "__main__":
    # Dev-mode quick launch. For production, use CAi/main.py or import
    # `launch` and pass a configured agent.
    from CAi.CAi_agent import A1pro
    from CAi.config import (
        LLM_API_KEY,
        LLM_BASE_URL,
        LLM_MODEL,
        LLM_SOURCE,
        LLM_TEMPERATURE,
    )

    agent = A1pro(
        llm=LLM_MODEL,
        source=LLM_SOURCE,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=LLM_TEMPERATURE,
        auto_load_tools=True,
        auto_load_skills=False,
    )
    launch(agent, port=7001)
