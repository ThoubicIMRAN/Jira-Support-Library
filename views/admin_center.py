from __future__ import annotations

"""Consolidated Admin Center.

A single administrative surface replaces the previous collection of
Administration, Admin Settings, Security & Messaging and Jira admin views.
Individual sections are implemented as reusable components under
views/admin_components/.
"""

import streamlit as st

from auth import allowed
from views.admin_components import directory,  analytics, audit, content, dashboard, jira, messaging, security, settings, users
from views.admin_components.common import page_header

SECTIONS = {
    "Overview": ("📊", dashboard.render, "Application overview and health"),
    "Users": ("👥", users.render, "Accounts, roles and status"),
        "Directory": ("🗂️", directory.render, "Import accounts from Active Directory over LDAPS."),
    "Content": ("📚", content.render, "Projects, categories and responses"),
    "Jira": ("🎫", jira.render, "Project mappings and transitions"),
    "Security": ("🔐", security.render, "Sessions and security posture"),
    "Messaging": ("✉️", messaging.render, "SMTP and application email"),
    "Audit Logs": ("📋", audit.render, "Administrative activity"),
    "Analytics": ("📈", analytics.render, "Usage and response activity"),
    "System": ("⚙️", settings.render, "Runtime and system information"),
}


def _allowed_sections(user) -> dict[str, tuple[str, object, str]]:
    result = {}
    for name, definition in SECTIONS.items():
        if name in {"Users", "Security", "Messaging", "Audit Logs", "Analytics", "System", "Jira"}:
            if user.role in {"admin", "superadmin"} or (name == "Users" and user.role == "superadmin"):
                result[name] = definition
        elif name == "Content":
            if allowed(user.role, "manage_content"):
                result[name] = definition
        else:
            if allowed(user.role, "manage_content") or user.role in {"admin", "superadmin"}:
                result[name] = definition
    return result


def render(user) -> None:
    sections = _allowed_sections(user)
    if not sections:
        st.error("You do not have access to the Admin Center.")
        return

    page_header(
        "Admin Center",
        "Manage users, content, Jira, security and system operations from one place.",
        "⚙️",
    )

    labels = list(sections.keys())
    icons = [sections[label][0] for label in labels]
    descriptions = [sections[label][2] for label in labels]

    if "admin_center_section" not in st.session_state or st.session_state.admin_center_section not in labels:
        st.session_state.admin_center_section = labels[0]

    # Compact navigation cards
    cols = st.columns(min(4, len(labels)))
    for index, label in enumerate(labels):
        col = cols[index % len(cols)]
        active = st.session_state.admin_center_section == label
        if col.button(
            f"{icons[index]}  {label}",
            key=f"admin_nav_{label}",
            type="primary" if active else "secondary",
            use_container_width=True,
            help=descriptions[index],
        ):
            st.session_state.admin_center_section = label
            st.rerun()

    st.markdown("---")
    sections[st.session_state.admin_center_section][1](user)
