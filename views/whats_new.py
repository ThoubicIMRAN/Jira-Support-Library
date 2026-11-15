"""What's New — release notes for agents and admins.

Source of truth: docs/releases.json (update on every release).
See docs/RELEASE_PROCESS.md and docs/BUGFIXES.md.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import streamlit as st

from components.cards import page_header
from config import APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)

_RELEASES_PATH = Path(__file__).resolve().parent.parent / "docs" / "releases.json"


def _load_releases() -> list[dict]:
    try:
        data = json.loads(_RELEASES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        logger.exception("Failed to load %s", _RELEASES_PATH)
    return []


def render(user) -> None:
    page_header("✨ What's New")
    st.caption(f"{APP_NAME} · current version **{APP_VERSION}**")
    st.caption("Release notes are maintained in `docs/releases.json`. Bug fixes: `docs/BUGFIXES.md`.")

    releases = _load_releases()
    if not releases:
        st.info("No release notes found. Add entries to `docs/releases.json`.")
        return

    for rel in releases:
        version = rel.get("version") or "?"
        date = rel.get("date") or ""
        title = rel.get("title") or ""
        features = rel.get("features") or rel.get("items") or []
        fixes = rel.get("fixes") or []
        with st.container(border=True):
            st.markdown(f"### v{version} · {date}")
            if title:
                st.markdown(f"**{title}**")
            if features:
                st.markdown("**Features**")
                for item in features:
                    st.markdown(f"- {item}")
            if fixes:
                st.markdown("**Bug fixes**")
                for item in fixes:
                    st.markdown(f"- {item}")
