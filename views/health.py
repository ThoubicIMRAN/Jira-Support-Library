"""Health dashboard."""
from __future__ import annotations

import streamlit as st

from components.cards import page_header

from services.health_service import health


def render(user=None) -> None:
    if user is not None and getattr(user, "role", None) not in ("superadmin", "admin"):
        st.warning("Health dashboard is limited to admins.")
        return

    result = health()
    page_header("🩺 Application Health")
    st.caption("Database, AI, mail, Jira, and Confluence.")

    if result.get("status") == "ok":
        st.success("Core checks look healthy.")
    else:
        st.warning("One or more components need attention.")

    items = [
        ("Database", result.get("database")),
        ("Ollama (AI)", result.get("ollama")),
        ("SMTP", result.get("smtp")),
        ("Jira", result.get("jira_config")),
        ("Confluence", result.get("confluence_config")),
    ]
    cols = st.columns(len(items))
    for col, (name, val) in zip(cols, items):
        with col:
            st.metric(name, val or "—")
            if val in {"error", "unreachable"} or (isinstance(val, str) and val.startswith("http_")):
                st.caption("Needs attention")

    with st.expander("Details"):
        st.json(result)
