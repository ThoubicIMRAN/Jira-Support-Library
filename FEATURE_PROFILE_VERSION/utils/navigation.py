"""Shared navigation contract for the app.

Defines page names, workspace tab names, and session keys in one place so
every view agrees on the same strings. The `goto()` helper is the only
sanctioned way to change pages — it keeps the page and related state in
sync.
"""
from __future__ import annotations

import streamlit as st


# --------------------------------------------------------------------------- #
# Top-level pages
# --------------------------------------------------------------------------- #
PAGE_LOGIN = "login"
PAGE_HOME = "home"
PAGE_PROJECT = "project"
PAGE_WORKSPACE = "workspace"
PAGE_PROFILE = "profile"
PAGE_ADMIN = "admin"
PAGE_SECURITY_ADMIN = "security"
PAGE_CHANGE_PASSWORD = "change_password"
PAGE_HEALTH = "health"
PAGE_SETTINGS = "settings"
PAGE_NOTIFICATIONS = "notifications"
PAGE_AI = "ai"
PAGE_ADMIN_SETTINGS = "admin_settings"
PAGE_SUPPORT = "support"
PAGE_DASHBOARD = "dashboard"
PAGE_WHATS_NEW = "whats_new"
PAGE_ASSETS = "assets"  # Snipe-IT asset management hub

VALID_PAGES = {
    PAGE_LOGIN,
    PAGE_HOME,
    PAGE_PROJECT,
    PAGE_WORKSPACE,
    PAGE_PROFILE,
    PAGE_ADMIN,
    PAGE_SECURITY_ADMIN,
    PAGE_CHANGE_PASSWORD,
    PAGE_HEALTH,
    PAGE_SETTINGS,
    PAGE_NOTIFICATIONS,
    PAGE_AI,
    PAGE_ADMIN_SETTINGS,
    PAGE_SUPPORT,
    PAGE_DASHBOARD,
    PAGE_WHATS_NEW,
    PAGE_ASSETS,
}


# --------------------------------------------------------------------------- #
# Workspace tabs
# --------------------------------------------------------------------------- #
WORKSPACE_TAB_SEARCH = "search"
WORKSPACE_TAB_FAVORITES = "favorites"
WORKSPACE_TAB_RECENT = "recent"
WORKSPACE_TAB_SAVED = "saved"

WORKSPACE_TABS = (
    WORKSPACE_TAB_SEARCH,
    WORKSPACE_TAB_FAVORITES,
    WORKSPACE_TAB_RECENT,
    WORKSPACE_TAB_SAVED,
)


# --------------------------------------------------------------------------- #
# Session keys
# --------------------------------------------------------------------------- #
SESSION_PAGE = "page"
SESSION_PROJECT_ID = "project_id"
SESSION_CATEGORY_FILTER = "category_filter"
SESSION_WORKSPACE_TAB = "workspace_tab"
SESSION_WORKSPACE_TAB_INTENT = "workspace_tab_intent"
SESSION_USER_ID = "user_id"


# --------------------------------------------------------------------------- #
# Navigation helper
# --------------------------------------------------------------------------- #
def goto(
    page: str,
    *,
    workspace_tab: str | None = None,
    project_id: int | None = None,
    clear_project: bool = False,
) -> None:
    """Set navigation state and rerun.

    Args:
        page: one of the PAGE_* constants.
        workspace_tab: when landing on the workspace, which tab to open.
            Ignored for other pages.
        project_id: set the active project for project-scoped views.
        clear_project: drop `project_id` and `category_filter`. Takes
            precedence over `project_id` if both are given.

    Raises:
        ValueError: if `page` is not a known page.
    """
    if page not in VALID_PAGES:
        raise ValueError(f"Unknown page: {page!r}")

    st.session_state[SESSION_PAGE] = page

    if page == PAGE_WORKSPACE:
        if workspace_tab not in WORKSPACE_TABS:
            workspace_tab = WORKSPACE_TAB_SEARCH
        st.session_state[SESSION_WORKSPACE_TAB] = workspace_tab
        # Separate intent key so the workspace widget can override its
        # own sticky value on the next render.
        st.session_state[SESSION_WORKSPACE_TAB_INTENT] = workspace_tab

    if clear_project:
        st.session_state.pop(SESSION_PROJECT_ID, None)
        st.session_state.pop(SESSION_CATEGORY_FILTER, None)
    elif project_id is not None:
        st.session_state[SESSION_PROJECT_ID] = project_id
        st.session_state.pop(SESSION_CATEGORY_FILTER, None)

    st.rerun()