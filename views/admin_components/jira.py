from __future__ import annotations

import streamlit as st

from auth import allowed
from config import JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from services import jira_service


def render(user) -> None:
    if user.role not in {"admin", "superadmin"} and not allowed(user.role, "manage_content"):
        st.error("Administrator access required.")
        return

    st.subheader("Jira")
    st.caption("Configure project mappings and friendly workflow labels. User credentials remain personal and encrypted.")
    if not JIRA_ENABLED:
        st.info("Jira integration is disabled in configuration.")
        return

    with st.container(border=True):
        c1, c2 = st.columns(2)
        c1.metric("Product", JIRA_PRODUCT)
        c2.metric("Connection", "Configured" if JIRA_BASE_URL else "Missing base URL")
        st.caption(JIRA_BASE_URL or "JIRA_BASE_URL is not configured")

    tab_map, tab_alias = st.tabs(["Project mappings", "Transition aliases"])
    with tab_map:
        links = jira_service.list_project_links()
        if not links:
            st.info("No application projects are available.")
        for row in links:
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.markdown(f"**{row['name']}**  \n`{row['app_key']}`")
            value = c2.text_input("Jira key", row["jira_project_key"], key=f"ac_jira_{row['project_id']}", label_visibility="collapsed")
            if c3.button("Save", key=f"ac_jira_save_{row['project_id']}", use_container_width=True):
                try:
                    jira_service.set_jira_project_key(row["project_id"], value)
                    st.toast("Jira project mapping saved.", icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with tab_alias:
        aliases = jira_service.list_transition_aliases()
        for alias in aliases:
            c1, c2, c3 = st.columns([2, 4, 1])
            c1.code(alias["jira_project_key"])
            c2.write(f"{alias['raw_name']} → **{alias['friendly_label']}**")
            if c3.button("Delete", key=f"ac_alias_{alias['id']}"):
                jira_service.delete_transition_alias(alias["id"])
                st.rerun()
        with st.form("ac_alias_form"):
            c1, c2 = st.columns(2)
            project_key = c1.text_input("Project key", "*")
            raw = c2.text_input("Raw transition")
            label = st.text_input("Friendly label")
            order = st.number_input("Sort order", min_value=0, value=0, step=1)
            save = st.form_submit_button("Add transition alias", type="primary")
        if save:
            try:
                jira_service.upsert_transition_alias(project_key, raw, label, int(order))
                st.success("Transition alias saved.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
