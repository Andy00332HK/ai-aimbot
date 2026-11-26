"""System-wide i18n: EN + ZH (Traditional). stdlib json only, thread-safe.

Usage: from aimbot.i18n import t, set_language, get_language, label_map
t("panel.start_button.start") -> translated string, with optional .format(**kwargs).
Missing key/file never raises: falls back en -> zh -> key itself.
"""
from __future__ import annotations

import json
import os
import threading

SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANG = "zh"

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")

_lock = threading.Lock()
_tables: dict[str, dict[str, str]] = {}
_current: str = DEFAULT_LANG


def _load_table(lang: str) -> dict[str, str]:
    with _lock:
        if lang in _tables:
            return _tables[lang]
    data: dict[str, str] = {}
    try:
        path = os.path.join(_LOCALES_DIR, f"{lang}.json")
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data = {str(k): str(v) for k, v in raw.items()}
    except Exception:
        data = {}
    with _lock:
        _tables[lang] = data
    return data


def set_language(lang: str) -> str:
    """Sanitize + switch current language. Returns effective lang."""
    eff = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANG
    _load_table(eff)
    global _current
    with _lock:
        _current = eff
    return eff


def get_language(lang: str | None = None) -> str:
    if lang in SUPPORTED_LANGUAGES:
        return lang
    with _lock:
        return _current


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Translate key. Falls back: requested -> en -> zh -> key. Formats with kwargs."""
    use = get_language(lang)
    template = None
    for cand in (use, "en", "zh"):
        tbl = _load_table(cand)
        if key in tbl:
            template = tbl[key]
            break
    if template is None:
        template = key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template


def label_map(prefix: str, keys: tuple[str, ...], lang: str | None = None) -> dict[str, str]:
    """Build {key: translated label} for dropdown values, e.g. prefix='config.enum.mouse_backend'."""
    return {k: t(f"{prefix}.{k}", lang=lang) for k in keys}
