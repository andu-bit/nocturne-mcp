"""
Accept-Language header parser and per-request locale ContextVar for REST API.

Provides ``get_request_locale()`` for API handlers to read the locale set by the
incoming ``Accept-Language`` header.  Falls back to ``"en"`` when the header is
missing or contains an unrecognised locale.

This ContextVar is **request-scoped only** — it does NOT override
``config.get_locale()``.  MCP/stdio paths (which have no HTTP headers) continue
to use config directly.
"""

import contextvars
from starlette.types import ASGIApp, Receive, Scope, Send

_UNSET = object()

_locale_ctx: contextvars.ContextVar = contextvars.ContextVar(
    "locale", default=_UNSET
)

KNOWN_LOCALES = frozenset({"en", "zh"})


def get_request_locale() -> str | None:
    """Return the locale set by LocaleMiddleware, or ``None`` outside HTTP."""
    val = _locale_ctx.get()
    return None if val is _UNSET else val


class LocaleMiddleware:
    """ASGI middleware that parses ``Accept-Language`` and sets the locale
    ContextVar for the duration of the request.

    Only applies to ``http`` scopes; ``websocket`` and other scope types pass
    through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            locale = self._parse_accept_language(scope)
            token = _locale_ctx.set(locale)
            try:
                await self.app(scope, receive, send)
            finally:
                _locale_ctx.reset(token)
        else:
            await self.app(scope, receive, send)

    @staticmethod
    def _parse_accept_language(scope: Scope) -> str:
        """Extract the primary language subtag from ``Accept-Language``.

        Takes the first language tag, strips region subtags, and validates
        against ``KNOWN_LOCALES``.
        """
        headers = dict(scope.get("headers", []))
        accept_lang = headers.get(b"accept-language", b"").decode(
            "latin-1", errors="ignore"
        )
        if not accept_lang:
            return "en"
        # Take first tag, extract primary subtag (e.g. "zh" from "zh-CN").
        primary = accept_lang.split(",")[0].strip().split("-")[0].lower()
        return primary if primary in KNOWN_LOCALES else "en"
