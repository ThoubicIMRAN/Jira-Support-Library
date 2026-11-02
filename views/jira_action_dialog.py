"""Jira action dialog — Package 2 single-screen layout + people pickers + safety.

This file is restored after an accidental PLACEHOLDER push.
Apply the full Package 2 body from DIALOG_PKG2.zip if this stub is still present.
"""
from __future__ import annotations

import base64
import logging
import re

import streamlit as st

from config import JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from services import jira_service
from services.confluence_client import ConfluenceError
from services.jira_client import JiraError
from services.jira_text import build_comment_preview
from services.jira_dialog_safety import action_plan_lines, unresolved_placeholders

logger = logging.getLogger(__name__)


def _msg(exc: Exception) -> str:
    if isinstance(exc, (JiraError, ValueError, ConfluenceError)):
        return str(exc)
    logger.exception("jira dialog error")
    return f"{type(exc).__name__}: {exc}"


def _sk(response_id: str, name: str) -> str:
    return f"jira_dlg_{response_id}_{name}"


def _linked_prefix(project) -> str | None:
    pid = getattr(project, "id", None)
    if pid is not None:
        try:
            key = jira_service.get_jira_project_key(int(pid))
            if key and str(key).strip():
                return str(key).strip().upper()
        except Exception:
            pass
    return (getattr(project, "key", None) or "").strip().upper() or None


def _ticket_prefix(key_or_url: str) -> str:
    try:
        from services.bulk_comment import parse_keys
        keys = parse_keys(key_or_url or "")
        if keys:
            return keys[0].split("-", 1)[0].upper()
    except Exception:
        pass
    text = (key_or_url or "").strip().upper()
    return text.split("-", 1)[0] if "-" in text else ""


def _assert_allowed(issue_key: str, project) -> None:
    required = _linked_prefix(project)
    if not required:
        raise JiraError("Link this library project to a Jira key (Admin → Jira).")
    prefix = (issue_key or "").split("-", 1)[0].upper()
    if prefix != required:
        raise JiraError(f"Only **{required}-*** tickets allowed. Got **{issue_key}**.")


def _clear(response_id: str, project_id) -> None:
    prefix = f"jira_dlg_{response_id}_"
    for name in list(st.session_state.keys()):
        if name.startswith(prefix):
            del st.session_state[name]
    if project_id is not None:
        st.session_state.pop(f"jira_last_ticket_{project_id}", None)


@st.dialog("Jira action", width="large")
def jira_action_dialog(user, project, response_body: str, response_id: str = "x") -> None:
    """Load full Package 2 implementation when present; otherwise show restore hint."""
    try:
        from services.jira_dialog_ui import run_dialog
        return run_dialog(user, project, response_body, response_id)
    except ImportError:
        st.warning(
            "Package 2 UI module not installed yet. "
            "Copy **services/jira_dialog_ui.py** from DIALOG_PKG2.zip and push."
        )
        st.info("Safety helpers and ticket load still work below after you apply the zip.")
        if not JIRA_ENABLED or not JIRA_BASE_URL:
            st.error("Jira is not configured.")
            return
        status = jira_service.credential_status(user.id)
        if not status.get("connected"):
            st.warning("Connect Jira under **Settings → Jira** first.")
            return
        st.caption(f"{status.get('display_name') or 'you'} · {JIRA_PRODUCT}")
        st.stop()
