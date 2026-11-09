"""
ASGI middleware for namespace extraction.

Shared by both the SSE/Streamable HTTP entry point (run_sse.py)
and the REST API entry point (main.py).

For legacy SSE transport (GET /sse → POST /messages/), namespace cannot be
re-read from each request because FastMCP's POST /messages/ carries only a
session_id and no namespace information.  We solve this by:

  1. On GET /sse?namespace=X  — wrapping ``send`` to intercept the outgoing
     ``endpoint`` SSE event emitted by FastMCP.  That event's data contains
     the session_id assigned to this connection (e.g.
     ``/messages/?session_id=<hex>``).  We parse the hex UUID and store
     ``_sse_sessions[session_id] = namespace`` before forwarding the event.

  2. On POST /messages/?session_id=<hex> — looking the hex key up in
     ``_sse_sessions`` to restore the namespace that was set at connect time.

All other requests use the original header / query-param logic.
"""

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

import os
import tempfile

from db.namespace import set_namespace

_RESERVED_NAMESPACES = frozenset({"_ns_default_0x7f3a9e"})


def _validate_namespace(ns: str) -> str | None:
    """Return an error message if *ns* is reserved, else None."""
    if ns in _RESERVED_NAMESPACES:
        return f"Namespace '{ns}' is reserved and cannot be used."
    return None


async def _send_400(send: Send, detail: str) -> None:
    import json
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": 400, "headers": [
        [b"content-type", b"application/json"],
        [b"content-length", str(len(body)).encode()],
    ]})
    await send({"type": "http.response.body", "body": body})

class FileSSESessionStore:
    """A multi-process safe file-based store for SSE session namespaces.
    Replaces the in-memory dict to allow multiple workers to share the mapping.
    """
    def __init__(self) -> None:
        self.store_dir = os.path.join(tempfile.gettempdir(), "nocturne_sse_sessions")
        os.makedirs(self.store_dir, exist_ok=True)

    def _path(self, session_id: str) -> str:
        # session_id is typically a hex string from FastMCP
        return os.path.join(self.store_dir, str(session_id))

    def __setitem__(self, session_id: str, namespace: str) -> None:
        try:
            with open(self._path(session_id), "w", encoding="utf-8") as f:
                f.write(namespace)
        except OSError:
            pass

    def get(self, session_id: str, default: str = "") -> str:
        if not session_id:
            return default
        path = self._path(session_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
        return default

    def pop(self, session_id: str, default: str = "") -> str:
        val = self.get(session_id, default)
        if session_id:
            path = self._path(session_id)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return val

# Populated when the FastMCP "endpoint" SSE event is intercepted on /sse.
_sse_sessions = FileSSESessionStore()


class NamespaceMiddleware:
    """ASGI middleware that extracts the namespace from request headers/query.

    Priority: ``X-Namespace`` header > ``namespace`` query parameter > default "".
    The value is written into the contextvars-based namespace context so that
    all downstream Path / SearchDocument queries are automatically scoped.

    For SSE transport the namespace is additionally persisted per session_id so
    that follow-up POST /messages/ requests inherit the namespace from the
    original GET /sse connection.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = scope.get("path", "")

        if path.rstrip("/").endswith("/sse"):
            # ── SSE connect ────────────────────────────────────────────────
            # Read namespace from this request as usual.
            ns = request.headers.get("x-namespace", "")
            if not ns:
                ns = request.query_params.get("namespace", "")
            if err := _validate_namespace(ns):
                await _send_400(send, err)
                return
            set_namespace(ns)

            # Wrap send so we can intercept FastMCP's outgoing "endpoint"
            # SSE event and record session_id → namespace.  The entry is
            # removed when the SSE stream closes (more_body=False) to prevent
            # the map from growing without bound on long-running servers.
            captured_ns = ns
            captured_session_id: list[str] = []  # mutable cell for the closure

            async def send_wrapper(message: dict) -> None:
                if message.get("type") == "http.response.body":
                    body: bytes = message.get("body", b"")
                    if body and b"event: endpoint" in body:
                        text = body.decode("utf-8", errors="ignore")
                        for line in text.splitlines():
                            line = line.strip()
                            if line.startswith("data:") and "session_id=" in line:
                                data = line[len("data:"):].strip()
                                session_id = data.split("session_id=")[-1].strip()
                                if session_id:
                                    _sse_sessions[session_id] = captured_ns
                                    captured_session_id.append(session_id)
                    if not message.get("more_body", False) and captured_session_id:
                        _sse_sessions.pop(captured_session_id[0], None)
                await send(message)

            await self.app(scope, receive, send_wrapper)

        elif "messages" in path:
            # ── SSE follow-up message ───────────────────────────────────────
            # Restore namespace from the session established at connect time.
            session_id = request.query_params.get("session_id", "")
            ns = _sse_sessions.get(session_id, "")
            # Fall back to per-request header/param if no session entry.
            if not ns:
                ns = request.headers.get("x-namespace", "")
            if not ns:
                ns = request.query_params.get("namespace", "")
            if err := _validate_namespace(ns):
                await _send_400(send, err)
                return
            set_namespace(ns)
            await self.app(scope, receive, send)

        else:
            # ── All other requests (REST API, Streamable HTTP, etc.) ────────
            ns = request.headers.get("x-namespace", "")
            if not ns:
                ns = request.query_params.get("namespace", "")
            if err := _validate_namespace(ns):
                await _send_400(send, err)
                return
            set_namespace(ns)
            await self.app(scope, receive, send)
