"""Notifications page.

Renders:
  - notification preferences (new / updated responses)
  - unread count + mark-all-read
  - list of unread notification items with project-open action

Navigation uses the shared page state so project-scoped views stay
consistent.
"""
from __future__ import annotations

from typing import Any, Sequence

import streamlit as st

from components.cards import page_header

from utils.navigation import PAGE_PROJECT, goto

from services.notification_service import (
    get_state,
    mark_all_read,
    notification_items,
    save_notification_settings,
)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_NEW_RESPONSES_ENABLED = True
DEFAULT_UPDATED_RESPONSES_ENABLED = True


# --------------------------------------------------------------------------- #
# Navigation helper
# --------------------------------------------------------------------------- #
def _open_project(project_id: int) -> None:
    """Navigate to the given project and clear any stale category filter."""
    goto(PAGE_PROJECT, project_id=project_id)


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
def _render_preferences(user, state: dict[str, Any]) -> None:
    with st.expander("⚙️ Notification preferences"):
        with st.form("notification_preferences", clear_on_submit=False):
            new_enabled = st.checkbox(
                "New responses",
                value=state.get("notify_new_responses", DEFAULT_NEW_RESPONSES_ENABLED),
                help="Notify me when a response is added to a project I follow.",
            )
            updated_enabled = st.checkbox(
                "Updated responses",
                value=state.get("notify_updated_responses", DEFAULT_UPDATED_RESPONSES_ENABLED),
                help="Notify me when an existing response is edited.",
            )
            submitted = st.form_submit_button(
                "Save preferences", type="primary", width="content"
            )

        if not submitted:
            return

        try:
            save_notification_settings(user.id, new_enabled, updated_enabled)
        except Exception:  # noqa: BLE001
            logger = __import__("logging").getLogger(__name__)
            logger.exception("Notification preferences save failed for user %s", user.id)
            st.error("Could not save notification preferences. Please try again.")
            return

        st.toast("Notification preferences saved.", icon="✅")
        st.rerun()


# --------------------------------------------------------------------------- #
# Header / actions
# --------------------------------------------------------------------------- #
def _render_header(count: int) -> None:
    col_count, col_action = st.columns([5, 1])
    col_count.caption(f"{count} unread item(s)")

    if col_action.button(
        "Mark all read",
        key="notifications_mark_all_read",
        width="stretch",
        disabled=count == 0,
        help="Mark every notification as read" if count else "Nothing to mark",
    ):
        st.session_state["notifications_mark_all"] = True


# --------------------------------------------------------------------------- #
# Item rendering
# --------------------------------------------------------------------------- #
def _render_item(row: Any) -> None:
    project = row.category.project

    with st.container(border=True):
        st.markdown(f"**{row.title}**")
        st.caption(
            f"{project.icon} {project.name} · 📂 {row.category.name} "
            f"· Updated {row.updated_at}"
        )
        if row.preview:
            st.write(row.preview)

        if st.button(
            "Open project",
            key=f"notification_open_{row.id}",
            width="content",
        ):
            _open_project(project.id)


def _render_items(items: Sequence[Any]) -> None:
    if not items:
        st.success("You are up to date.")
        return
    for row in items:
        _render_item(row)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def render(user) -> None:
    page_header("🔔 Notifications")

    try:
        state = get_state(user.id)
    except Exception:  # noqa: BLE001
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Could not load notification settings for user %s", user.id)
        st.error("Could not load notification settings. Please try again.")
        state = {}

    _render_preferences(user, state)

    try:
        items = list(notification_items(user.id))
    except Exception:  # noqa: BLE001
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Could not load notifications for user %s", user.id)
        st.error("Could not load notifications. Please try again.")
        return

    _render_header(len(items))

    # Handle mark-all-read after the button click so the count is fresh.
    if st.session_state.pop("notifications_mark_all", False):
        try:
            mark_all_read(user.id)
        except Exception:  # noqa: BLE001
            logger = __import__("logging").getLogger(__name__)
            logger.exception("Could not mark all notifications as read for user %s", user.id)
            st.error("Could not update notification status. Please try again.")
            return
        st.rerun()

    _render_items(items)