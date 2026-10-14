"""User preference service.

Persists per-user appearance settings and turns them into a small block of CSS
*design tokens*. All component styling lives in ``assets/styles.css`` and reads
those tokens, so a theme change never needs per-widget ``!important`` rules.

The palette is taken verbatim from the Jira Command Library prototype
(``Jira_Command_Library.html``): same surfaces, same sidebar blue, same
Syne / DM Sans / IBM Plex Mono type system.

Public API:
    get_preferences(user_id)             -> dict
    save_preferences(user_id, values)    -> dict
    reset_preferences(user_id)           -> dict
    preference_css(prefs, *, sidebar_collapsed=False) -> str   (a <style> block)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from sqlalchemy import select

from database import SessionLocal, UserPreference

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULTS: dict[str, Any] = {
    "theme": "light",            # prototype default
    "accent_color": "#0c46ce",   # prototype --accent
    "font_family": "DM Sans",    # prototype --sans
    "font_scale": 100,
    "code_font_size": 12,
    "line_height": 160,
    "density": "comfortable",
    "card_columns": 3,
    "border_radius": 8,
    "reduce_motion": False,
    "high_contrast": False,
    "compact_sidebar": False,
}

# Body font only. Headings (Syne) and code (IBM Plex Mono) always stay on-brand.
ALLOWED_FONTS: tuple[str, ...] = (
    "DM Sans",
    "Segoe UI",
    "Arial",
    "Verdana",
    "Tahoma",
    "Georgia",
)
ALLOWED_THEMES: tuple[str, ...] = ("light", "dark", "system")
ALLOWED_DENSITIES: tuple[str, ...] = ("compact", "comfortable", "spacious")

SIDEBAR_WIDTH = "252px"            # prototype --sb-w
SIDEBAR_WIDTH_COMPACT = "220px"
SIDEBAR_WIDTH_COLLAPSED = "64px"

_DENSITY_PADDING = {"compact": ".32rem", "comfortable": ".45rem", "spacious": ".65rem"}
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Exact prototype values (":root" and '[data-theme="dark"]').
LIGHT_TOKENS: dict[str, str] = {
    "bg": "#f0f4fb", "bg2": "#ffffff", "bg3": "#e8edf8",
    "sb": "#0c1f6e", "sb2": "#0a1a5c",
    "border": "#dde3f0", "border2": "#c5d0e8",
    "text": "#111827", "text2": "#4b5675", "text3": "#8898b8",
    "sh": "0 2px 12px rgba(12, 31, 110, .07)",
    "sh2": "0 6px 28px rgba(12, 31, 110, .13)",
    "foot": "#e8edf8",           # card / project footer band
    "chip-bg": "rgba(12, 70, 206, .08)",
    "chip-border": "rgba(12, 70, 206, .15)",
    "chip-fg": "var(--accent)",
    "scheme": "light",
}
DARK_TOKENS: dict[str, str] = {
    "bg": "#0b0f1c", "bg2": "#111827", "bg3": "#1a2236",
    "sb": "#060d1f", "sb2": "#050b18",
    "border": "#1e2d48", "border2": "#2a3f60",
    "text": "#e2e8f4", "text2": "#8898b8", "text3": "#3d5070",
    "sh": "0 2px 12px rgba(0, 0, 0, .35)",
    "sh2": "0 6px 28px rgba(0, 0, 0, .5)",
    "foot": "rgba(255, 255, 255, .02)",
    "chip-bg": "rgba(96, 165, 250, .1)",
    "chip-border": "rgba(96, 165, 250, .25)",
    "chip-fg": "#60a5fa",
    "scheme": "dark",
}
# text3 in the prototype's dark palette (#3d5070) is below WCAG AA on dark
# surfaces; high-contrast mode lifts the muted tones.
_HC_LIGHT = {"text2": "#2b3550", "text3": "#4b5675", "border": "#9aa6c4", "border2": "#7a88ad"}
_HC_DARK = {"text2": "#c3cde2", "text3": "#94a3c4", "border": "#3d5273", "border2": "#566d93"}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _as_int(value: Any, fallback: int, *, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _validated(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fully-populated, validated preferences dict."""
    raw = {**DEFAULTS, **{k: v for k, v in values.items() if k in DEFAULTS}}

    theme = str(raw["theme"]).strip().lower()
    font = str(raw["font_family"]).strip()
    accent = str(raw["accent_color"]).strip()
    density = str(raw["density"]).strip().lower()

    return {
        "theme": theme if theme in ALLOWED_THEMES else DEFAULTS["theme"],
        "accent_color": accent if _HEX_COLOR_RE.match(accent) else DEFAULTS["accent_color"],
        "font_family": font if font in ALLOWED_FONTS else DEFAULTS["font_family"],
        "font_scale": _as_int(raw["font_scale"], DEFAULTS["font_scale"], low=85, high=130),
        "code_font_size": _as_int(raw["code_font_size"], DEFAULTS["code_font_size"], low=10, high=18),
        "line_height": _as_int(raw["line_height"], DEFAULTS["line_height"], low=120, high=200),
        "density": density if density in ALLOWED_DENSITIES else DEFAULTS["density"],
        "card_columns": _as_int(raw["card_columns"], DEFAULTS["card_columns"], low=2, high=4),
        "border_radius": _as_int(raw["border_radius"], DEFAULTS["border_radius"], low=0, high=24),
        "reduce_motion": _as_bool(raw["reduce_motion"], DEFAULTS["reduce_motion"]),
        "high_contrast": _as_bool(raw["high_contrast"], DEFAULTS["high_contrast"]),
        "compact_sidebar": _as_bool(raw["compact_sidebar"], DEFAULTS["compact_sidebar"]),
    }


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def get_preferences(user_id: int) -> dict[str, Any]:
    """Return validated preferences (defaults when the user has no row yet)."""
    try:
        with SessionLocal() as db:
            row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
            if row is None:
                return dict(DEFAULTS)
            return _validated({key: getattr(row, key, DEFAULTS[key]) for key in DEFAULTS})
    except Exception:
        logger.exception("get_preferences failed for user %s", user_id)
        return dict(DEFAULTS)


def save_preferences(user_id: int, values: Mapping[str, Any]) -> dict[str, Any]:
    clean = _validated(values)
    try:
        with SessionLocal() as db:
            row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
            if row is None:
                row = UserPreference(user_id=user_id)
                db.add(row)
            for key, value in clean.items():
                setattr(row, key, value)
            db.commit()
    except Exception:
        logger.exception("save_preferences failed for user %s", user_id)
        raise
    return clean


def reset_preferences(user_id: int) -> dict[str, Any]:
    try:
        with SessionLocal() as db:
            row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
            if row is not None:
                db.delete(row)
                db.commit()
    except Exception:
        logger.exception("reset_preferences failed for user %s", user_id)
        raise
    return dict(DEFAULTS)


# --------------------------------------------------------------------------- #
# CSS tokens
# --------------------------------------------------------------------------- #
def _token_block(tokens: Mapping[str, str], *, high_contrast: bool) -> str:
    merged = dict(tokens)
    if high_contrast:
        merged.update(_HC_DARK if tokens["scheme"] == "dark" else _HC_LIGHT)
    lines = [f"--{name}:{value};" for name, value in merged.items() if name != "scheme"]
    lines.append(f"color-scheme:{merged['scheme']};")
    return "".join(lines)


def preference_css(
    preferences: Mapping[str, Any] | None,
    *,
    sidebar_collapsed: bool = False,
) -> str:
    """Return a ``<style>`` block that sets every design token for the user.

    ``theme == "system"`` follows the OS via ``prefers-color-scheme`` in pure
    CSS, so no server-side (and unreliable) colour-scheme detection is needed.
    """
    prefs = _validated(preferences or {})
    hc = prefs["high_contrast"]
    radius = prefs["border_radius"]

    if sidebar_collapsed:
        sidebar_width = SIDEBAR_WIDTH_COLLAPSED
    elif prefs["compact_sidebar"]:
        sidebar_width = SIDEBAR_WIDTH_COMPACT
    else:
        sidebar_width = SIDEBAR_WIDTH

    shared = (
        f"--accent:{prefs['accent_color']};"
        f"--sans:'{prefs['font_family']}','DM Sans','Segoe UI',system-ui,sans-serif;"
        f"--rc:{radius}px;--r:{radius + 2}px;--r2:{radius * 2}px;"
        f"--density-pad:{_DENSITY_PADDING[prefs['density']]};"
        f"--code-size:{prefs['code_font_size']}px;"
        f"--code-lh:{prefs['line_height'] / 100:.2f};"
        f"--sb-w:{sidebar_width};"
    )

    light = _token_block(LIGHT_TOKENS, high_contrast=hc)
    dark = _token_block(DARK_TOKENS, high_contrast=hc)

    if prefs["theme"] == "dark":
        palette = f":root{{{dark}}}"
    elif prefs["theme"] == "system":
        palette = f":root{{{light}}}@media (prefers-color-scheme: dark){{:root{{{dark}}}}}"
    else:
        palette = f":root{{{light}}}"

    extras = f"html{{font-size:{prefs['font_scale']}%;}}"
    if prefs["reduce_motion"]:
        extras += (
            "*,*::before,*::after{animation:none!important;"
            "transition:none!important;scroll-behavior:auto!important;}"
        )

    return f'<style id="jsl-user-tokens">:root{{{shared}}}{palette}{extras}</style>'
