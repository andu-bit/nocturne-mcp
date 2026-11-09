"""
Locale loader — lightweight i18n for Nocturne Memory.
 
Provides ``t(key, locale=None)`` as the single entry point for translation:
 
- ``locale="en"`` returns the key as-is (English is canonical, no mapping file).
- ``locale=None`` resolves via ``config.get_locale()``.
- Nested keys via dot notation: ``t("api.browse.path_not_found")``.
- Unsupported locales fall back to ``"en"`` behavior (key as-is).
- Missing keys fall back to the key itself (no crash).
- Zero third-party dependencies (no gettext, no Babel).
"""
 
import json
from pathlib import Path
from typing import Optional

_LOCALES_DIR = Path(__file__).resolve().parent
_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json(locale: str) -> dict:
    """Load a locale JSON file, caching it indefinitely.

    Returns ``{}`` if the file does not exist or is malformed.
    """
    if locale not in _cache:
        path = _LOCALES_DIR / f"{locale}.json"
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    _cache[locale] = json.load(f)
            except (json.JSONDecodeError, OSError):
                _cache[locale] = {}
        else:
            _cache[locale] = {}
    return _cache[locale]


def _deep_get(d: dict, key: str) -> Optional[str]:
    """Resolve a dotted key into a nested dict.

    Returns ``None`` if any path segment is missing, or if the resolved value
    is not a string (e.g. intermediate dicts).
    """
    parts = key.split(".")
    current: object = d
    for part in parts:
        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]
    return current if isinstance(current, str) else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def t(key: str, locale: Optional[str] = None) -> str:
    """Translate *key* into the requested *locale*.

    Parameters
    ----------
    key:
        Dot-separated lookup path, e.g. ``"api.browse.path_not_found"``.
    locale:
        ISO language code.  ``None`` → use ``config.get_locale()``.

    Returns
    -------
    str:
        Translated string, or *key* itself if no translation is found.
    """
    resolved = locale
    if resolved is None:
        try:
            from locales.middleware import get_request_locale  # noqa: PLC0415
            resolved = get_request_locale()  # None when outside HTTP request
        except Exception:
            pass
        if resolved is None:
            # Outside HTTP (MCP/stdio): always English.
            # MCP output is consumed by AI models — English is more
            # reliable as system-message language and avoids forcing
            # maintainers to keep translations in sync for machine-facing text.
            resolved = "en"

    # English: check en.json first so that human-readable messages are
    # returned instead of raw dot-separated keys.
    if resolved == "en":
        en_data = _load_json("en")
        result = _deep_get(en_data, key)
        if result is not None:
            return result
        return key

    # 1) Try the requested locale.
    data = _load_json(resolved)
    result = _deep_get(data, key)
    if result is not None:
        return result

    # 2) Fall back to English.
    en_data = _load_json("en")
    result = _deep_get(en_data, key)
    if result is not None:
        return result

    # 3) Graceful fallback — return the key itself.
    return key
