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


def accent_scope(container_key: str, color: Any) -> str:
    """Return a <style> block that sets ``--pc`` for one keyed container."""
    return f"<style>.st-key-{safe_key(container_key)}{{--pc:{safe_color(color)};}}</style>"


# --------------------------------------------------------------------------- #
# Page chrome
# --------------------------------------------------------------------------- #
def page_header(title: str, subtitle: str | None = None, icon: str | None = None) -> None:
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


def section_header(title: str, count: int | None = None, color: str | None = None) -> None:
    """Category heading with accent bar and count pill."""
    count_html = f'<span class="jsl-sec-count">{int(count)}</span>' if count is not None else ""
    bar = f' style="background:{safe_color(color)}"' if color else ""
    st.markdown(
        f'<div class="jsl-sec-head"><span class="jsl-sec-bar"{bar}></span>'
        f'<span class="jsl-sec-title">{_e(title)}</span>{count_html}</div>',
        unsafe_allow_html=True,
    )


def empty_state(icon: str, title: str, hint: str | None = None) -> None:
    hint_html = f"<p>{_e(hint)}</p>" if hint else ""
    st.markdown(
        f'<div class="jsl-empty"><div class="jsl-empty-icon">{_e(icon)}</div>'
        f"<h3>{_e(title)}</h3>{hint_html}</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Project card (home)
# --------------------------------------------------------------------------- #
def project_card(
    project: Any,
    category_count: int,
    response_count: int,
    *,
    pinned: bool = False,
) -> tuple[bool, bool]:
    """Render one project tile and return ``(open_clicked, pin_clicked)``.

    The whole tile is one keyed container so CSS can draw the card shell, the
    tinted icon, the footer band and the coloured "Open" button as one unit.
    """
    pid = int(project.id)
    key = f"pcard_{pid}"
    with st.container(key=key):
        st.markdown(
            accent_scope(key, getattr(project, "color", None))
            + '<div class="jsl-proj-top">'
            f'<div class="jsl-proj-icon">{_e(getattr(project, "icon", None) or "📁")}</div>'
            f'<div class="jsl-proj-name">{_e(project.name)}</div>'
            f'<div class="jsl-proj-desc">{_e(getattr(project, "description", ""))}</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        with st.container(key=f"pfoot_{pid}"):
            stats_col, open_col, pin_col = st.columns([3, 3.2, 1.2], vertical_alignment="center", gap="small")
            stats_col.markdown(
                '<div class="jsl-proj-stats">'
                f'<div class="jsl-proj-stat"><span class="jsl-proj-stat-num">{int(response_count)}</span>'
                '<span class="jsl-proj-stat-label">Responses</span></div>'
                '<span class="jsl-proj-stat-divider"></span>'
                f'<div class="jsl-proj-stat"><span class="jsl-proj-stat-num">{int(category_count)}</span>'
                '<span class="jsl-proj-stat-label">Categories</span></div>'
                "</div>",
                unsafe_allow_html=True,
            )
            opened = open_col.button(
                "Open library →", key=f"open_{pid}", type="primary", width="stretch"
            )
            pin_clicked = pin_col.button(
                "📌" if pinned else "＋",
                key=f"pin_{pid}",
                help="Unpin project" if pinned else "Pin project to the top",
                width="stretch",
            )
    return opened, pin_clicked


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
        accent_scope(container_key, color)
        + '<div class="jsl-card-top">'
        f'<span class="jsl-card-num">{int(index)}</span>'
        f'<div class="jsl-card-titlebox"><div class="jsl-card-title">{_e(title)}</div>{sub_html}</div>'
        f"{badge_html}</div>",
        unsafe_allow_html=True,
    )


def preview_text(text: str | None) -> None:
    if text:
        st.markdown(f'<div class="jsl-card-preview">{_e(text)}</div>', unsafe_allow_html=True)
