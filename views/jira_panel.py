"""Jira status line for the project page (the 🎫 button on each card does the work)."""
from __future__ import annotations

import streamlit as st

from config import JIRA_BASE_URL, JIRA_ENABLED
from services import jira_service


def render_jira_panel(user, project) -> None:
    if not JIRA_ENABLED or not JIRA_BASE_URL:
        return
    status = jira_service.credential_status(user.id)
    if status.get("connected"):
        st.caption(f"🎫 Jira connected as **{status.get('display_name')}** — use 🎫 on a response to comment, log time or transition.")
    else:
        st.caption("🎫 Jira not connected — connect it under **Personal settings → Jira connection**.")
