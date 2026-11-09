"""
Namespace context for multi-agent memory isolation.

Uses contextvars to pass the namespace implicitly through async call chains.
For stdio mode, falls back to the NAMESPACE environment variable.
For SSE/HTTP mode, the middleware sets it per-request from the X-Namespace header.
"""

import contextvars
import os

_namespace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "namespace", default=os.getenv("NAMESPACE", "")
)


def get_namespace() -> str:
    return _namespace.get()


def set_namespace(ns: str) -> contextvars.Token[str]:
    return _namespace.set(ns)
