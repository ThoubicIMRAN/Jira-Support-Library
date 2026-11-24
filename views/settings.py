"""Unified Personal Settings — appearance, layout, account, Jira connection."""

from __future__ import annotations

import streamlit as st

from components.cards import page_header
from config import APP_BUILD_LABEL, APP_NAME, APP_VERSION
from services.preference_service import (
    ALLOWED_FONTS,
    get_preferences,
    preference_css,
    reset_preferences,
    save_preferences,
)
from views.jira_settings import render_jira_settings
from views.profile import render_linked_identities, render_profile_form

__all__ = ["render", "APP_NAME", "APP_VERSION", "APP_BUILD_LABEL"]

_THEMES = ("system", "light", "dark")
_DENSITIES = ("compact", "comfortable", "spacious")


def _safe_index(options: list | tuple, value, default: int = 0) -> int:
    """Return the index of ``value`` in ``options``, or ``default`` if missing."""
    try:
        return list(options).index(value)
    except (ValueError, TypeError):
        return default


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _render_css(css: str) -> None:
    """Inject a stylesheet regardless of whether it includes a <style> wrapper."""
    if not css:
        return
    if hasattr(st, "html"):
        st.html(css)
        return
    if "<style" not in css.lower():
        css = f"<style>{css}</style>"
    st.markdown(css, unsafe_allow_html=True)


def _render_appearance(user) -> None:
    prefs = get_preferences(user.id)

    # Use a form to batch writes, but wrap sections in tight custom markdown
    with st.form("personal_settings"):
        # --- Theme & Color ---
        st.markdown('<div class="jsl-form-section">', unsafe_allow_html=True)
        st.markdown("#### Theme & colour")
        theme = st.radio(
            "Theme",
            _THEMES,
            index=_safe_index(_THEMES, prefs.get("theme"), 0),
            horizontal=True,
            format_func=str.title,
        )
        c1, c2 = st.columns(2)
        accent_color = c1.color_picker(
            "Accent color", prefs.get("accent_color") or "#0c46ce"
        )
        border_radius = c2.slider(
            "Corner radius",
            0,
            24,
            _clamp(prefs.get("border_radius"), 0, 24, 8),
            1,
            format="%d px",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Typography ---
        st.markdown('<div class="jsl-form-section">', unsafe_allow_html=True)
        st.markdown("#### Typography")
        font_family = st.selectbox(
            "Application font",
            ALLOWED_FONTS,
            index=_safe_index(ALLOWED_FONTS, prefs.get("font_family"), 0),
        )
        f1, f2, f3 = st.columns(3)
        font_scale = f1.slider(
            "Interface size",
            85,
            130,
            _clamp(prefs.get("font_scale"), 85, 130, 100),
            5,
            format="%d%%",
        )
        code_font_size = f2.slider(
            "Response text",
            10,
            18,
            _clamp(prefs.get("code_font_size"), 10, 18, 13),
            1,
            format="%d px",
        )
        line_height = f3.slider(
            "Line spacing",
            120,
            200,
            _clamp(prefs.get("line_height"), 120, 200, 150),
            5,
            format="%d%%",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Layout ---
        st.markdown('<div class="jsl-form-section">', unsafe_allow_html=True)
        st.markdown("#### Layout")
        density = st.radio(
            "Control spacing",
            _DENSITIES,
            index=_safe_index(_DENSITIES, prefs.get("density"), 1),
            horizontal=True,
            format_func=str.title,
        )
        l1, l2 = st.columns([1, 1])
        card_columns = l1.slider(
            "Cards per row",
            2,
            4,
            _clamp(prefs.get("card_columns"), 2, 4, 3),
        )
        compact_sidebar = l2.checkbox(
            "Compact sidebar", bool(prefs.get("compact_sidebar"))
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Accessibility ---
        st.markdown('<div class="jsl-form-section">', unsafe_allow_html=True)
        st.markdown("#### Accessibility")
        a1, a2 = st.columns(2)
        high_contrast = a1.checkbox(
            "Increase contrast", bool(prefs.get("high_contrast"))
        )
        reduce_motion = a2.checkbox("Reduce motion", bool(prefs.get("reduce_motion")))
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Actions ---
        st.markdown("<br>", unsafe_allow_html=True)
        b1, b2 = st.columns([1, 1])
        save = b1.form_submit_button("Save settings", type="primary", width="stretch")
        reset = b2.form_submit_button("Reset to defaults", width="stretch")

    # Handle state logic
    values = {
        "theme": theme,
        "accent_color": accent_color,
        "font_family": font_family,
        "font_scale": font_scale,
        "code_font_size": code_font_size,
        "line_height": line_height,
        "density": density,
        "card_columns": card_columns,
        "border_radius": border_radius,
        "reduce_motion": reduce_motion,
        "high_contrast": high_contrast,
        "compact_sidebar": compact_sidebar,
    }

    if save and not reset:
        st.session_state.user_preferences = save_preferences(user.id, values)
        st.toast("Personal settings saved.", icon="✅")
        st.rerun()
        return
    if reset and not save:
        st.session_state.user_preferences = reset_preferences(user.id)
        st.toast("Personal settings reset.", icon="↩️")
        st.rerun()
        return

    # Live preview is kept below the form, stripped of the default container box
    st.markdown("### Live preview")
    _render_css(preference_css(values))

    # Using a standard container but removing the hard border for a cleaner look
    with st.container():
        st.markdown(
            '<div style="background:var(--background-color);padding:1rem;border-radius:var(--border-radius);border:1px solid var(--secondary-background-color);">'
            "<strong>Preview response card</strong>",
            unsafe_allow_html=True,
        )
        st.code(
            "Hello Customer,\n\nYour request has been completed.\n\n"
            "Best regards,\nSupport Engineer",
            language=None,
            wrap_lines=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)


def _render_account(user) -> None:
    # Removed the dividers and extra markdown headers that double up on the tab name
    render_profile_form(user)
    st.markdown("<hr style='margin: 1.5rem 0; opacity: 0.3;'>", unsafe_allow_html=True)
    render_linked_identities(user)


def render(user) -> None:
    # CSS override to fix the "AI slop" spacing
    st.markdown(
        """
        <style>
        /* Remove default massive padding inside tabs */
        [data-testid="stTabsContent"] {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
        }
        /* Tighten form section spacing */
        .jsl-form-section {
            margin-bottom: 0.5rem;
        }
        .jsl-form-section h4 {
            margin-top: 0.5rem;
            margin-bottom: 0.5rem;
            font-size: 1rem;
            font-weight: 600;
        }
        /* Remove the gap between the radio buttons and the slider */
        .stRadio {
            margin-bottom: -0.5rem;
        }
        /* Reduce the height of the color picker */
        .stColorPicker {
            margin-bottom: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    page_header(
        "Personal Settings",
        "Appearance, account, and integrations.",
        icon="🎨",
    )

    tab_appearance, tab_account, tab_jira = st.tabs(
        ["🎨 Appearance", "👤 Profile", "🎫 Integrations"]
    )

    with tab_appearance:
        _render_appearance(user)

    with tab_account:
        _render_account(user)

    with tab_jira:
        render_jira_settings(user)
