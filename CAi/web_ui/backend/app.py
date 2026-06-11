"""
FastAPI application factory for CAi Web UI.

This module is intentionally thin — it only creates the FastAPI instance,
registers routers, and re-exports set_agent() so launch.py keeps its
existing import path.

Concurrency model:
    The agent is a stateless execution engine. Conversation history lives in
    ConversationStore. Each /api/chat request loads history → runs agent →
    appends results. A global lock serialises chat requests because code
    execution uses a shared REPL kernel (see deps._chat_lock).

Streaming model:
    The agent's run_with_history_streaming() yields token-level events from
    the LLM plus observation events after each code execution.  We forward
    each event as an SSE message so the browser can render incrementally.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .deps import set_agent  # re-exported for launch.py
from .routers import chat, conversations, files, memory, utilities, workspace

app = FastAPI(title="CAi Web UI API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7000", "http://127.0.0.1:7000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(workspace.router)
app.include_router(utilities.router)
app.include_router(memory.router)
