"""Unified Admin Settings — Content & users, Security, Audit, Jira."""
from __future__ import annotations

import logging

import streamlit as st

from components.cards import page_header

from auth import allowed

logger = logging.getLogger(__name__)


def render(user) -> None:
    page_header("⚙️ Admin Settings")
    st.caption("Content, users, security, audit, and Jira.")

    can_content = allowed(user.role, "manage_content") or user.role in ("admin", "superadmin")
    can_security = user.role in ("admin", "superadmin")

    if not can_content and not can_security:
        st.warning("You do not have access to admin settings.")
        return

    options: list[str] = []
    if can_content:
        options.append("Content & users")
    if can_security:
        options.append("Security & SMTP")
        options.append("Audit & logs")
    options.append("Jira")
    if user.role == "superadmin":
        options.append("Health")

    section = st.radio(
        "Section",
        options,
        horizontal=True,
        key="admin_settings_section",
        label_visibility="collapsed",
    )
    st.divider()

    try:
        if section == "Content & users":
            from views import admin_panel

            admin_panel.render(user, embedded=True)

        elif section == "Security & SMTP":
            from views import security_admin

            security_admin.render(user, embedded=True)

        elif section == "Audit & logs":
            from views.admin_panel import render_audit_section

            render_audit_section(user)

            from views.bulk_jira import render_bulk_log

            st.markdown("#### 📣 Bulk Jira comments")
            st.caption("Every bulk run by every user: who posted, to which tickets, and what failed.")
            render_bulk_log(user, everyone=True, limit=50)

        elif section == "Jira":
            from views.jira_admin import render_jira_admin

            render_jira_admin(user)

        elif section == "Health":
            from views import health

            health.render(user)

    except Exception:
        logger.exception("Admin section %s failed", section)
        st.error(f"This admin section failed to load ({section}).")
        if st.button("Retry", key="admin_section_retry"):
            st.rerun()
