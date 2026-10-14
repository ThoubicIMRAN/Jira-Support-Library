"""Shared layout helpers."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

MIN_COLUMNS = 1
MAX_COLUMNS = 4
DEFAULT_COLUMNS = 3


def card_columns(prefs: Mapping[str, Any] | None = None) -> int:
    """Number of cards per row from the user's preference (clamped to 1-4)."""
    prefs = prefs if prefs is not None else (st.session_state.get("user_preferences") or {})
    try:
        value = int(prefs.get("card_columns", DEFAULT_COLUMNS))
    except (TypeError, ValueError):
        value = DEFAULT_COLUMNS
    return max(MIN_COLUMNS, min(MAX_COLUMNS, value))


def flash(message: str, icon: str = "✅") -> None:
    """Queue a toast that survives the next st.rerun()."""
    st.session_state.setdefault("_flash", []).append((message, icon))


def show_flash() -> None:
    for message, icon in st.session_state.pop("_flash", []):
        st.toast(message, icon=icon)
