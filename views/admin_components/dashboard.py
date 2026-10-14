from __future__ import annotations

import streamlit as st
from sqlalchemy import func, select

from config import APP_ENV, JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT, OLLAMA_BASE
from database import AuditLog, Category, Project, Response, SessionLocal, User
from views.admin_components.common import metric_card, section_title, status_badge


def render(user) -> None:
    with SessionLocal() as db:
        users = db.scalar(select(func.count(User.id))) or 0
        active_users = db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
        projects = db.scalar(select(func.count(Project.id)).where(Project.is_deleted.is_(False))) or 0
        categories = db.scalar(select(func.count(Category.id))) or 0
        responses = db.scalar(select(func.count(Response.id))) or 0
        events = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(8)).all()

    cols = st.columns(5)
    for col, label, value in zip(
        cols,
        ["Users", "Active users", "Projects", "Categories", "Responses"],
        [users, active_users, projects, categories, responses],
    ):
        with col:
            metric_card(label, value)

    st.markdown("---")
    left, right = st.columns([1.35, 1], gap="large")

    with left:
        section_title("System health", "A quick view of configuration readiness", "🛡️")
        checks = [
            ("Environment", APP_ENV != "production" or True, APP_ENV),
            ("Jira integration", not JIRA_ENABLED or bool(JIRA_BASE_URL), "Configured" if not JIRA_ENABLED or JIRA_BASE_URL else "Missing base URL"),
            ("Local AI", bool(OLLAMA_BASE), "Configured" if OLLAMA_BASE else "Not configured"),
        ]
        for label, ok, detail in checks:
            c1, c2 = st.columns([2, 1])
            c1.write(f"**{label}**")
            with c2:
                status_badge(ok, detail if ok else detail)

        if JIRA_ENABLED:
            st.caption(f"Jira: {JIRA_PRODUCT} · {JIRA_BASE_URL or 'base URL not configured'}")

    with right:
        section_title("Recent activity", "Latest administrative events", "🕘")
        if not events:
            st.info("No administrative activity has been recorded yet.")
        for event in events:
            st.markdown(
                f"**{event.action}** · {event.entity_type}  \n"
                f"<small>{event.created_at} · user #{event.user_id or 'system'}</small>",
                unsafe_allow_html=True,
            )
