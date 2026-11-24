"""Admin Settings: one page whose sections are filtered by the signed-in user's role."""

from __future__ import annotations

import logging
from typing import Callable

import streamlit as st

from auth import allowed
from components.cards import page_header

logger = logging.getLogger(__name__)


# Imports are inside the functions so only the selected section is loaded.
def _content(user) -> None:
    from views import admin_panel

    admin_panel.render(user, embedded=True)


def _security(user) -> None:
    from views import security_admin

    security_admin.render(user, embedded=True)


def _audit(user) -> None:
    from views.admin_panel import render_audit_section
    from views.bulk_jira import render_bulk_log

    render_audit_section(user)
    st.markdown("#### Bulk Jira comments")
    st.caption(
        "Every bulk run by every user: who posted, to which tickets, and what failed."
    )
    render_bulk_log(user, everyone=True, limit=50)


def _jira(user) -> None:
    from views.jira_admin import render_jira_admin

    render_jira_admin(user)


def _health(user) -> None:
    from views import health

    health.render(user)


# (label, role check, renderer). Order here is the order on screen.
# (label, permission in auth.PERMISSIONS, renderer)
SECTIONS: tuple[tuple[str, str, Callable], ...] = (
    ("Content & users", "manage_content", _content),
    ("Security & SMTP", "manage_security", _security),
    ("Audit & logs", "view_audit", _audit),
    ("Jira", "manage_jira", _jira),
    ("Health", "view_health", _health),
)

_STATE_KEY = "admin_settings_section"


def render(user) -> None:
    page_header("Admin Settings")

    visible = {
        label: render_fn
        for label, permission, render_fn in SECTIONS
        if allowed(user.role, permission)
    }
    if not visible:
        st.warning("You do not have access to admin settings.")
        return

    if (
        st.session_state.get(_STATE_KEY) not in visible
    ):  # e.g. the role changed since last visit
        st.session_state.pop(_STATE_KEY, None)
    section = st.radio(
        "Section",
        list(visible),
        horizontal=True,
        key=_STATE_KEY,
        label_visibility="collapsed",
    )
    st.divider()

    try:
        visible[section](user)
    except Exception:  # noqa: BLE001
        logger.exception("Admin section %s failed", section)
        st.error(f"This admin section failed to load ({section}).")
        st.caption(f"Reference: {st.session_state.get('correlation_id', 'n/a')}")
        st.button("Retry", key="admin_section_retry")  # any click reruns the section
