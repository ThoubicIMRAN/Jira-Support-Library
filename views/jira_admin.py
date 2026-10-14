"""Admin: map app projects → Jira keys, manage transition friendly labels."""
from __future__ import annotations

import logging

import streamlit as st

from config import JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from services import jira_service

logger = logging.getLogger(__name__)


def render_jira_admin(user) -> None:
    st.subheader("🎫 Jira administration")
    if user.role not in ("admin", "superadmin"):
        st.warning("Admin access required.")
        return

    if not JIRA_ENABLED:
        st.info("Jira integration is disabled.")
        return

    st.caption(
        f"Site: `{JIRA_BASE_URL or '(not set)'}` · Product: **{JIRA_PRODUCT}**"
    )

    tab_map, tab_alias = st.tabs(["Project → Jira key", "Transition labels"])

    with tab_map:
        st.markdown("Link each **library project** to a **Jira project key**.")
        try:
            links = jira_service.list_project_links()
        except Exception:
            logger.exception("Could not load Jira project links")
            st.error("Could not load project links.")
            links = []
        if not links:
            st.info("No library projects yet.")
        else:
            for row in links:
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{row['name']}**  \n`{row['app_key']}`")
                key_val = c2.text_input(
                    "Jira key",
                    value=row["jira_project_key"],
                    key=f"jira_link_{row['project_id']}",
                    label_visibility="collapsed",
                    placeholder="e.g. SIT",
                )
                if c3.button("Save", key=f"jira_link_save_{row['project_id']}", width="stretch"):
                    try:
                        jira_service.set_jira_project_key(row["project_id"], key_val)
                        st.toast(f"Linked {row['name']} → {key_val.upper()}")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    with tab_alias:
        st.markdown(
            "Map Jira transition **raw names** to **friendly labels** shown in the app. "
            "Use project key `*` for global defaults."
        )
        aliases = jira_service.list_transition_aliases()
        if aliases:
            for a in aliases:
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                c1.caption(a["jira_project_key"])
                c2.write(a["raw_name"])
                c3.write(f"→ **{a['friendly_label']}**")
                if c4.button("🗑", key=f"jira_alias_del_{a['id']}", help="Delete"):
                    jira_service.delete_transition_alias(a["id"])
                    st.rerun()
        else:
            st.caption("No aliases yet.")

        st.markdown("---")
        st.markdown("**Add alias**")
        with st.form("jira_alias_form"):
            f1, f2 = st.columns(2)
            proj_key = f1.text_input("Jira project key", value="*", help="* = all projects")
            raw = f2.text_input("Raw transition name", placeholder="e.g. Resolve this issue")
            label = st.text_input("Friendly label", placeholder="e.g. Resolve")
            sort_order = st.number_input("Sort order", min_value=0, value=0, step=1)
            if st.form_submit_button("Add alias", type="primary"):
                try:
                    jira_service.upsert_transition_alias(
                        jira_project_key=proj_key,
                        raw_name=raw,
                        friendly_label=label,
                        sort_order=int(sort_order),
                    )
                    st.success("Alias saved.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
