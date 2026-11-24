"""Health dashboard."""

from __future__ import annotations

import streamlit as st

from components.cards import page_header
from services.health_service import health


def _status_indicator(val: str | None) -> tuple[str, str]:
    """Return (icon, color) based on the health check value."""
    if val is None or val == "":
        return "⚪", "gray"
    if val in {"ok", "healthy", "connected", "reachable"}:
        return "🟢", "green"
    if val in {"error", "unreachable", "failed"} or (
        isinstance(val, str) and val.startswith("http_")
    ):
        return "🔴", "red"
    return "🟡", "orange"


def render(user=None) -> None:
    if user is not None and getattr(user, "role", None) not in ("superadmin", "admin"):
        st.warning("Health dashboard is limited to admins.")
        return

    # Tighten layout & limit width so metrics don't stretch across 4K screens
    st.markdown(
        """
        <style>
        .block-container { max-width: 1200px; padding-top: 2rem !important; }
        [data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        [data-testid="stMetricLabel"] { font-weight: 500; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    result = health()
    page_header(
        "Application Health",
        "Database, AI, mail, Jira, and Confluence connectivity.",
        icon="🩺",
    )

    # Top-level status banner
    if result.get("status") == "ok":
        st.success("All core systems are operational.", icon="🟢")
    else:
        st.error(
            " One or more components need attention. Review the details below.",
            icon="🔴",
        )

    # Grid of components — wraps automatically on smaller screens
    items = [
        ("Database", result.get("database")),
        ("Ollama (AI)", result.get("ollama")),
        ("SMTP", result.get("smtp")),
        ("Jira", result.get("jira_config")),
        ("Confluence", result.get("confluence_config")),
    ]

    # 3 columns max makes it readable on standard monitors
    cols = st.columns(min(len(items), 3), gap="medium")
    for i, (name, val) in enumerate(items):
        icon, color = _status_indicator(val)
        with cols[i % len(cols)]:
            st.metric(
                label=name,
                value=f"{icon} {val.title() if isinstance(val, str) and val else '—'}",
                help=f"Raw value: {val}" if val else "No response from service",
            )

    # Raw diagnostic dump
    with st.expander("🛠️ Raw diagnostic details", expanded=False):
        st.json(result)
