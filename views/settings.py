"""Unified Personal Settings — appearance, layout, account, Jira connection."""
from __future__ import annotations

import streamlit as st

from components.cards import page_header
from services.preference_service import (
    ALLOWED_FONTS,
    get_preferences,
    preference_css,
    reset_preferences,
    save_preferences,
)
from views.jira_settings import render_jira_settings
from views.profile import render_linked_identities, render_profile_form


def render(user) -> None:
    page_header(
        "Personal Settings",
        "Appearance, account, and integrations in one place.",
        icon="🎨",
    )

    tab_appearance, tab_account, tab_jira = st.tabs(
        ["🎨 Appearance & layout", "👤 Account & profile", "🎫 Jira connection"]
    )

    with tab_appearance:
        prefs = get_preferences(user.id)
        with st.form("personal_settings"):
            st.markdown("##### Theme & colour")
            theme = st.radio(
                "Theme",
                ["system", "light", "dark"],
                index=["system", "light", "dark"].index(prefs["theme"]),
                horizontal=True,
                format_func=lambda x: x.title(),
            )
            c1, c2 = st.columns(2)
            accent_color = c1.color_picker("Accent color", prefs["accent_color"])
            border_radius = c2.slider(
                "Corner radius", 0, 24, prefs["border_radius"], 1, format="%d px"
            )

            st.markdown("##### Typography")
            font_family = st.selectbox(
                "Application font",
                ALLOWED_FONTS,
                index=ALLOWED_FONTS.index(prefs["font_family"]),
            )
            f1, f2, f3 = st.columns(3)
            font_scale = f1.slider(
                "Interface font size", 85, 130, prefs["font_scale"], 5, format="%d%%"
            )
            code_font_size = f2.slider(
                "Response text size", 10, 18, prefs["code_font_size"], 1, format="%d px"
            )
            line_height = f3.slider(
                "Line spacing", 120, 200, prefs["line_height"], 5, format="%d%%"
            )

            st.markdown("##### Layout")
            density = st.radio(
                "Control spacing",
                ["compact", "comfortable", "spacious"],
                index=["compact", "comfortable", "spacious"].index(prefs["density"]),
                horizontal=True,
                format_func=lambda x: x.title(),
            )
            card_columns = st.slider(
                "Response cards per row", 2, 4, prefs["card_columns"]
            )
            compact_sidebar = st.checkbox("Compact sidebar", prefs["compact_sidebar"])

            st.markdown("##### Accessibility")
            high_contrast = st.checkbox("Increase contrast", prefs["high_contrast"])
            reduce_motion = st.checkbox(
                "Reduce animations and transitions", prefs["reduce_motion"]
            )

            b1, b2 = st.columns(2)
            save = b1.form_submit_button(
                "Save personal settings", type="primary", width="stretch"
            )
            reset = b2.form_submit_button("Reset to defaults", width="stretch")

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
        if save:
            st.session_state.user_preferences = save_preferences(user.id, values)
            st.toast("Personal settings saved.", icon="✅")
            st.rerun()
        if reset:
            st.session_state.user_preferences = reset_preferences(user.id)
            st.toast("Personal settings reset.", icon="↩️")
            st.rerun()

        st.subheader("Live preview")
        _pcss = preference_css(values)
        if hasattr(st, "html"):
            st.html(_pcss)
        elif "<style" in _pcss.lower():
            st.markdown(_pcss, unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("**Preview response card**")
            st.code(
                "Hello Customer,\n\nYour request has been completed.\n\n"
                "Best regards,\nSupport Engineer",
                language=None,
                wrap_lines=True,
            )

    with tab_account:
        st.markdown("##### Profile")
        st.caption("Name, designation, password, and per-project designations.")
        render_profile_form(user)
        st.divider()
        st.markdown("##### Linked sign-in")
        render_linked_identities(user)

    with tab_jira:
        render_jira_settings(user)
