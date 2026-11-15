"""Lightweight workspace helpers: dialog drafts and saved queue filters.

Phase 1 stores data in ``st.session_state`` only (survives reruns, not browser
restarts). A later release can persist to the database without changing callers.
"""
from __future__ import annotations

from typing import Any

_DRAFT_PREFIX = "dialog_draft:"
_FILTERS_KEY = "saved_queue_filters"


def draft_key(user_id: int, issue_key: str) -> str:
    return f"{_DRAFT_PREFIX}{user_id}:{issue_key}"


def save_dialog_draft(session: dict, user_id: int, issue_key: str, body: str) -> None:
    key = (issue_key or "").strip().upper()
    if not key:
        return
    session[draft_key(user_id, key)] = body or ""


def load_dialog_draft(session: dict, user_id: int, issue_key: str) -> str:
    key = (issue_key or "").strip().upper()
    if not key:
        return ""
    return session.get(draft_key(user_id, key)) or ""


def clear_dialog_draft(session: dict, user_id: int, issue_key: str) -> None:
    key = (issue_key or "").strip().upper()
    if key:
        session.pop(draft_key(user_id, key), None)


def list_saved_filters(session: dict) -> list[dict[str, Any]]:
    raw = session.get(_FILTERS_KEY) or []
    return list(raw) if isinstance(raw, list) else []


def save_filter(session: dict, name: str, payload: dict[str, Any]) -> None:
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("Filter name is required.")
    filters = list_saved_filters(session)
    filters = [f for f in filters if f.get("name") != name]
    filters.append({"name": name, "payload": dict(payload or {})})
    session[_FILTERS_KEY] = filters[-20:]


def delete_filter(session: dict, name: str) -> None:
    filters = [f for f in list_saved_filters(session) if f.get("name") != name]
    session[_FILTERS_KEY] = filters
