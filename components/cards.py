"""Shared UI building blocks that mirror the Jira Command Library prototype.

Every element is built from CSS classes defined in ``assets/styles.css`` and
styled only through design tokens, so light/dark themes need no extra code.
All dynamic text is HTML-escaped.

Per-project accent colour is exposed to CSS as the custom property ``--pc`` on
the keyed Streamlit container (``st.container(key=...)`` adds the class
``st-key-<key>``), which lets icon tiles, badges and buttons pick up the
project colour exactly like the prototype's ``.p0 … .pN`` themes.
"""

from __future__ import annotations

import html
import re
from typing import Any

import streamlit as st

DEFAULT_PROJECT_COLOR = "#0c46ce"
_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_KEY_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def safe_color(value: Any, fallback: str = DEFAULT_PROJECT_COLOR) -> str:
    """Return ``value`` if it is a #RRGGBB colour, else ``fallback``."""
    text = str(value or "").strip()
    return text if _HEX6.match(text) else fallback


def safe_key(value: Any) -> str:
    """Make an arbitrary id safe for use inside a Streamlit widget key."""
    return _KEY_SAFE.sub("-", str(value))


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def initials(name: Any) -> str:
    """Up to two capital letters for avatar / tile fallbacks ("Jira Support" -> "JS")."""
    parts = [p for p in re.split(r"[\s._@-]+", str(name or "")) if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (parts[0][:2] if parts else "?").upper()


def format_card_index(index: int) -> str:
    """Format a card index consistently with the project prototype."""
    return f"{int(index):02d}"


def accent_scope(container_key: str, color: Any) -> str:
    """Return a <style> block that sets ``--pc`` for one keyed container."""
    return (
        f"<style>.st-key-{safe_key(container_key)}{{--pc:{safe_color(color)};}}</style>"
    )


# --------------------------------------------------------------------------- #
# Page chrome
# --------------------------------------------------------------------------- #
def page_header(
    title: str, subtitle: str | None = None, icon: str | None = None
) -> None:
    """Standard page title (Syne display face) with optional subtitle."""
    icon_html = f'<span class="jsl-page-icon">{_e(icon)}</span>' if icon else ""
    sub_html = f'<p class="jsl-page-sub">{_e(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<div class="jsl-page-head"><h1 class="jsl-page-title">{icon_html}{_e(title)}</h1>'
        f"{sub_html}</div>",
        unsafe_allow_html=True,
    )


def hero_banner(
    title: str,
    subtitle: str,
    *,
    tag: str | None = "Live library",
    stats: list[tuple[str, str]] | None = None,
) -> None:
    """Blue gradient hero (prototype ``.home-hero``)."""
    tag_html = f'<div class="jsl-hero-tag">{_e(tag)}</div>' if tag else ""
    stats_html = ""
    if stats:
        cells = "".join(
            f'<div class="jsl-hero-stat"><div class="jsl-hero-stat-num">{_e(num)}</div>'
            f'<div class="jsl-hero-stat-label">{_e(label)}</div></div>'
            for num, label in stats
        )
        stats_html = f'<div class="jsl-hero-stats">{cells}</div>'
    st.markdown(
        f'<div class="jsl-hero">{tag_html}<h1>{_e(title)}</h1><p>{_e(subtitle)}</p>{stats_html}</div>',
        unsafe_allow_html=True,
    )


def section_header(
    title: str, count: int | None = None, color: str | None = None
) -> None:
    """Category heading with accent bar and count pill."""
    count_html = (
        f'<span class="jsl-sec-count">{int(count)}</span>' if count is not None else ""
    )
    bar = f' style="background:{safe_color(color)}"' if color else ""
    st.markdown(
        f'<div class="jsl-sec-head"><span class="jsl-sec-bar"{bar}></span>'
        f'<span class="jsl-sec-title">{_e(title)}</span>{count_html}</div>',
        unsafe_allow_html=True,
    )


def empty_state(icon: str | None, title: str, hint: str | None = None) -> None:
    """Dashed placeholder. Pass ``icon=None`` for a text-only state."""
    hint_html = f"<p>{_e(hint)}</p>" if hint else ""
    icon_html = f'<div class="jsl-empty-icon">{_e(icon)}</div>' if icon else ""
    st.markdown(
        f'<div class="jsl-empty">{icon_html}<h3>{_e(title)}</h3>{hint_html}</div>',
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Project card (home)
# --------------------------------------------------------------------------- #
def project_card(
    project: Any,
    *,
    pinned: bool = False,
    can_manage: bool = False,
    key_prefix: str,
) -> tuple[bool, bool, bool, bool]:
    """Render one project card and return open, pin, edit, and archive clicks."""
    pid = int(project.id)
    prefix = safe_key(key_prefix)
    key = f"pcard_{prefix}_{pid}"
    with st.container(key=key):
        st.markdown(
            accent_scope(key, getattr(project, "color", None)),
            unsafe_allow_html=True,
        )
        top_left, top_right = st.columns([5, 1], vertical_alignment="center")
        project_key = getattr(project, "key", None) or ""
        top_left.markdown(
            f'<span class="jsl-proj-key">{_e(project_key)}</span>',
            unsafe_allow_html=True,
        )
        pin_clicked = top_right.button(
            "",
            icon=":material/star:" if pinned else ":material/star_border:",
            key=f"pin_{prefix}_{pid}",
            help="Unpin project" if pinned else "Pin project to the top",
            width="stretch",
        )
        st.markdown(
            '<div class="jsl-proj-body">'
            f'<div class="jsl-proj-name">{_e(project.name)}</div>'
            f'<div class="jsl-proj-desc">{_e(getattr(project, "description", ""))}</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        with st.container(key=f"pfoot_{prefix}_{pid}"):
            open_col, menu_col = st.columns(
                [4, 1], vertical_alignment="center", gap="small"
            )
            opened = open_col.button(
                "Open library",
                key=f"open_{prefix}_{pid}",
                type="primary",
                width="stretch",
                icon=":material/arrow_forward:",
                icon_position="right",
            )
            edit_clicked = False
            archive_clicked = False
            if can_manage:
                with menu_col.popover(
                    "",
                    icon=":material/more_vert:",
                    key=f"menu_{prefix}_{pid}",
                    help="Project actions",
                ):
                    edit_clicked = st.button(
                        "Edit project",
                        icon=":material/edit:",
                        key=f"edit_{prefix}_{pid}",
                        width="stretch",
                    )
                    archive_clicked = st.button(
                        "Archive project",
                        icon=":material/archive:",
                        key=f"archive_{prefix}_{pid}",
                        width="stretch",
                        type="tertiary",
                    )
    return opened, pin_clicked, edit_clicked, archive_clicked


# --------------------------------------------------------------------------- #
# Response card
# --------------------------------------------------------------------------- #
def response_card_header(
    *,
    container_key: str,
    index: int,
    title: str,
    badge: str | None,
    color: Any,
    subtitle: str | None = None,
) -> None:
    """Numbered title row with a project-coloured badge (prototype ``.card-top``)."""
    badge_html = f'<span class="jsl-card-badge">{_e(badge)}</span>' if badge else ""
    sub_html = f'<div class="jsl-card-sub">{_e(subtitle)}</div>' if subtitle else ""
    st.markdown(
        accent_scope(container_key, color) + '<div class="jsl-card-top">'
        f'<span class="jsl-card-num">{int(index)}</span>'
        f'<div class="jsl-card-titlebox"><div class="jsl-card-title">{_e(title)}</div>{sub_html}</div>'
        f"{badge_html}</div>",
        unsafe_allow_html=True,
    )


def preview_text(text: str | None) -> None:
    if text:
        st.markdown(
            f'<div class="jsl-card-preview">{_e(text)}</div>', unsafe_allow_html=True
        )
