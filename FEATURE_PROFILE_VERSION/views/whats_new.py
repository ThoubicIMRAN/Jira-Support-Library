"""What\'s New — release notes for agents and admins."""
from __future__ import annotations

import streamlit as st

from components.cards import page_header
from config import APP_NAME, APP_VERSION

# Newest first
RELEASES: list[dict] = [
    {
        "version": "2.2.0",
        "date": "2026-10-29",
        "title": "My Dashboard, avatars, multi-step transitions",
        "items": [
            "**My Dashboard** — open issues assigned to you (all projects), charts by project/status and due date",
            "**Profile photo** — upload PNG/JPEG/WebP (max 500 KB), stored encrypted-at-rest path in DB",
            "**Admin user edit** — name, email, designation, role, avatar from Admin → Users",
            "**Categories** — edit name, parent (sub-category), sort order inline",
            "**Jira dialog** — reporter/assignee/status row, validator field, multi-select transitions in order",
            "**Multi-step transitions** — chain statuses in one Post (e.g. To Do → In Progress → Resolved)",
            "**Security** — login rate limits, stronger password policy, production FERNET_KEY gate",
            f"**Version** — Application info shows **{APP_VERSION}**",
        ],
    },
    {
        "version": "2.1.x",
        "date": "2026-10",
        "title": "Library + Jira / Confluence core",
        "items": [
            "Command library with projects, categories, responses, AI approval",
            "Jira comment / log time / transition with per-user tokens",
            "Template `[bracket]` fields and @mentions → watchers",
            "Confluence resolution notes, bulk comment, health checks",
        ],
    },
]


def render(user) -> None:
    page_header("✨ What\'s New")
    st.caption(f"{APP_NAME} · current version **{APP_VERSION}**")

    for rel in RELEASES:
        with st.container(border=True):
            st.markdown(f"### v{rel['version']} · {rel['date']}")
            st.markdown(f"**{rel['title']}**")
            for item in rel["items"]:
                st.markdown(f"- {item}")
