"""Notifications page.

Notifications are a *derived view*: `notification_items()` returns `Response`
rows whose `created_at` or `updated_at` is newer than the user's
`UserNotificationState.last_seen_at` watermark, scoped to projects the user
can see.

There is no per-item read flag in the schema (only `last_seen_at`), so the
only read action is "Mark all read". Each card links to the owning project.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Sequence

import streamlit as st

from components.cards import page_header
from services.notification_service import (
    get_state,
    mark_all_read,
    notification_items,
    save_notification_settings,
)
from utils.navigation import PAGE_PROJECT, goto

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_NEW_RESPONSES_ENABLED = True
DEFAULT_UPDATED_RESPONSES_ENABLED = True

SESSION_MARK_ALL = "notifications_mark_all"


# --------------------------------------------------------------------------- #
# Text / time helpers
# --------------------------------------------------------------------------- #
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f]")
_MARKUP_RE = re.compile(r"[\[\]<>`]")


def _safe_text(v: Any, limit: int = 400) -> str:
    s = str(v or "")
    s = _CTRL_RE.sub("", s)
    s = _MARKUP_RE.sub("", s)
    return s[:limit]


def _format_ts(v: datetime | None) -> str:
    if not v:
        return ""
    try:
        return v.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return _safe_text(v, 40)


# --------------------------------------------------------------------------- #
# Project accessors (pinned to Response.category.project)
# --------------------------------------------------------------------------- #
def _project_of(row: Any):
    cat = getattr(row, "category", None)
    return getattr(cat, "project", None) if cat is not None else None


def _project_label(row: Any) -> str:
    proj = _project_of(row)
    if proj is None:
        return ""
    icon = getattr(proj, "icon", "") or ""
    name = getattr(proj, "name", "") or "Project"
    return f"{icon} {name}".strip()


def _category_name(row: Any) -> str:
    cat = getattr(row, "category", None)
    return getattr(cat, "name", "") or "" if cat is not None else ""


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
def _open_project(project_id: int) -> None:
    goto(PAGE_PROJECT, project_id=project_id)


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
def _render_preferences(user, state: dict[str, Any]) -> None:
    with st.expander("⚙️ Notification preferences"):
        with st.form("notification_preferences", clear_on_submit=False):
            new_enabled = st.checkbox(
                "New responses",
                value=bool(
                    state.get("notify_new_responses", DEFAULT_NEW_RESPONSES_ENABLED)
                ),
                help="Notify me when a response is added to a project I follow.",
            )
            updated_enabled = st.checkbox(
                "Updated responses",
                value=bool(
                    state.get(
                        "notify_updated_responses", DEFAULT_UPDATED_RESPONSES_ENABLED
                    )
                ),
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
            logger.exception(
                "Notification preferences save failed for user %s", user.id
            )
            st.error("Could not save notification preferences. Please try again.")
            return

        st.toast("Notification preferences saved.", icon="✅")
        st.rerun()


# --------------------------------------------------------------------------- #
# Header / mark-all
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
        st.session_state[SESSION_MARK_ALL] = True


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def _apply_filters(items: Sequence[Any]) -> list[Any]:
    projects = sorted({_project_label(r) for r in items if _project_label(r)})
    categories = sorted({_category_name(r) for r in items if _category_name(r)})

    c1, c2, c3 = st.columns([2, 2, 3])
    pick_proj = c1.multiselect(
        "Filter by project",
        projects,
        key="notifications_filter_project",
        placeholder="All projects",
    )
    pick_cat = c2.multiselect(
        "Filter by category",
        categories,
        key="notifications_filter_category",
        placeholder="All categories",
    )
    search = c3.text_input(
        "Search",
        key="notifications_filter_search",
        placeholder="Title or preview text…",
    )

    needle = (search or "").strip().lower()

    def _keep(r: Any) -> bool:
        if pick_proj and _project_label(r) not in pick_proj:
            return False
        if pick_cat and _category_name(r) not in pick_cat:
            return False
        if needle:
            hay = f"{getattr(r, 'title', '')} {getattr(r, 'preview', '')}".lower()
            if needle not in hay:
                return False
        return True

    return [r for r in items if _keep(r)]


# --------------------------------------------------------------------------- #
# Item rendering
# --------------------------------------------------------------------------- #
def _render_item(row: Any) -> None:
    response_id = str(getattr(row, "id", "") or "")
    if not response_id:
        return

    proj = _project_of(row)
    project_id = getattr(proj, "id", None) if proj is not None else None

    title = _safe_text(getattr(row, "title", "") or "", 240) or "Untitled response"
    preview = _safe_text(getattr(row, "preview", "") or "", 400)
    badge = _safe_text(getattr(row, "badge", "") or "", 40)
    updated_at = _format_ts(getattr(row, "updated_at", None))
    created_at = _format_ts(getattr(row, "created_at", None))

    with st.container(border=True):
        st.markdown(f"**{title}**")
        if badge:
            st.caption(f"`{badge}`")

        meta = [
            b
            for b in (
                _project_label(row),
                f"📂 {_category_name(row)}" if _category_name(row) else "",
                f"Updated {updated_at}" if updated_at else "",
                f"Created {created_at}" if created_at else "",
            )
            if b
        ]
        if meta:
            st.caption(" · ".join(meta))

        if preview:
            st.write(preview)

        if project_id is not None:
            if st.button(
                "Open project",
                key=f"notification_open_{response_id}",
                width="content",
            ):
                _open_project(project_id)
        else:
            st.button(
                "Open project",
                key=f"notification_open_{response_id}",
                disabled=True,
                width="content",
                help="This notification is not linked to a project.",
            )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def render(user) -> None:
    page_header("🔔 Notifications")

    try:
        state = get_state(user.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load notification settings for user %s", user.id)
        st.error("Could not load notification settings. Please try again.")
        state = {}

    _render_preferences(user, state)

    try:
        items = list(notification_items(user.id))
    except Exception:  # noqa: BLE001
        logger.exception("Could not load notifications for user %s", user.id)
        st.error("Could not load notifications. Please try again.")
        return

    _render_header(len(items))

    if st.session_state.pop(SESSION_MARK_ALL, False):
        try:
            mark_all_read(user.id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not mark all notifications as read for user %s", user.id
            )
            st.error("Could not update notification status. Please try again.")
            return
        st.rerun()

    if not items:
        st.success("You are up to date.")
        return

    filtered = _apply_filters(items)
    if not filtered:
        st.success("No unread notifications match your filters.")
        return
    for row in filtered:
        _render_item(row)
