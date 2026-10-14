from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from config import APP_ENV, APP_NAME, APP_URL, DATABASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from database import SMTPConfig, SessionLocal


def render(user) -> None:
    if user.role not in {"admin", "superadmin"}:
        st.error("Administrator access required.")
        return

    st.subheader("System settings")
    st.caption("Application configuration relevant to administrators. Host OS and Python runtime details are intentionally not exposed here.")

    with SessionLocal() as db:
        smtp = db.scalar(select(SMTPConfig).where(SMTPConfig.is_active.is_(True)).order_by(SMTPConfig.id.desc()))

    rows = [
        ("Application", APP_NAME),
        ("Environment", APP_ENV),
        ("Application URL", APP_URL or "Not configured"),
        ("Database backend", DATABASE_URL.split("://", 1)[0]),
        ("Jira", f"{JIRA_PRODUCT} / {'enabled' if JIRA_ENABLED else 'disabled'}"),
        ("SMTP", "Configured" if smtp else "Not configured"),
    ]
    st.dataframe([{"Setting": k, "Value": v} for k, v in rows], width="stretch", hide_index=True)

    if not APP_URL:
        st.warning("APP_URL is not configured. Password-reset and invitation emails cannot contain a valid application link until APP_URL is set.")
