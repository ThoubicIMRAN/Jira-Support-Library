"""Admin: map app projects → Jira keys, transition labels, multi-step chains."""

from __future__ import annotations

import logging

import streamlit as st

from config import JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from services import jira_service
from services import jira_transition_chains as jtc
from utils.errors import safe_message

logger = logging.getLogger(__name__)


def _render_project_mapping() -> None:
    st.markdown("Link each internal library project to a Jira project key.")

    try:
        links = jira_service.list_project_links()
    except Exception:
        logger.exception("Could not load Jira project links")
        st.error("Could not load project links.")
        return

    if not links:
        st.info("No library projects exist yet. Create a project first.")
        return

    # Render mappings as a clean list of cards
    for row in links:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")

            with c1:
                st.markdown(f"**{row['name']}**")
                st.caption(f"Internal Key: `{row['app_key']}`")

            with c2:
                key_val = st.text_input(
                    "Jira Key",
                    value=row["jira_project_key"],
                    key=f"jira_link_{row['project_id']}",
                    label_visibility="collapsed",
                    placeholder="e.g. SIT",
                )

            with c3:
                if st.button(
                    "Save Link",
                    key=f"jira_link_save_{row['project_id']}",
                    width="stretch",
                ):
                    try:
                        jira_service.set_jira_project_key(row["project_id"], key_val)
                        st.toast(f"Mapped {row['name']} → {key_val.upper()}", icon="✅")
                        st.rerun()
                    except ValueError as exc:
                        st.error(safe_message(exc))


def _render_aliases() -> None:
    st.markdown("Map Jira's raw transition names to clean labels for the app UI.")
    st.caption("Use project key `*` for global defaults across all projects.")

    aliases = jira_service.list_transition_aliases()

    # Existing Aliases
    if aliases:
        for a in aliases:
            c1, c2, c3, c4 = st.columns([1, 3, 2, 1], vertical_alignment="center")
            c1.code(a["jira_project_key"], language=None)
            c2.caption(f"{a['raw_name']}  →  **{a['friendly_label']}**")
            if c4.button("🗑", key=f"jira_alias_del_{a['id']}", help="Delete alias"):
                jira_service.delete_transition_alias(a["id"])
                st.rerun()
    else:
        st.info("No aliases configured yet.")

    st.divider()

    # Add New Alias
    with st.expander("➕ Add New Alias", expanded=False):
        with st.form("jira_alias_form"):
            f1, f2 = st.columns(2)
            proj_key = f1.text_input(
                "Jira project key", value="*", help="* = all projects"
            )
            raw = f2.text_input(
                "Raw transition name", placeholder="e.g. Resolve this issue"
            )

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
                    st.toast("Alias saved.", icon="✅")
                    st.rerun()
                except ValueError as exc:
                    st.error(safe_message(exc))


def _render_chains() -> None:
    st.markdown("Create multi-step transition presets (macros).")
    st.caption("Agents select a chain to execute multiple Jira steps in one click.")

    chains = jtc.list_transition_chains()

    # Existing Chains
    if chains:
        for ch in chains:
            steps = ch.get("steps") or []
            c1, c2, c3 = st.columns([1, 4, 1], vertical_alignment="center")
            c1.code(ch["jira_project_key"], language=None)
            c2.markdown(f"**{ch['name']}**  \n" + " → ".join(f"`{s}`" for s in steps))
            if c3.button("🗑", key=f"jira_chain_del_{ch['id']}", help="Delete chain"):
                jtc.delete_transition_chain(ch["id"])
                st.rerun()
    else:
        st.info("No chains configured yet.")

    st.divider()

    # Add New Chain
    with st.expander("➕ Add New Chain", expanded=False):
        with st.form("jira_chain_form"):
            f1, f2 = st.columns(2)
            pk = f1.text_input("Jira project key", value="*", help="* = all projects")
            name = f2.text_input("Chain name", placeholder="e.g. Quick Resolve")

            steps_raw = st.text_input(
                "Steps (comma-separated raw names)",
                placeholder="Start Progress, Resolve Issue, Close Issue",
            )
            sort_order = st.number_input(
                "Sort order", min_value=0, value=0, step=1, key="ja_chain_ord"
            )

            if st.form_submit_button("Add chain", type="primary"):
                try:
                    steps = [
                        s.strip() for s in (steps_raw or "").split(",") if s.strip()
                    ]
                    jtc.upsert_transition_chain(
                        jira_project_key=pk,
                        name=name,
                        steps=steps,
                        sort_order=int(sort_order),
                    )
                    st.toast("Chain saved.", icon="✅")
                    st.rerun()
                except ValueError as exc:
                    st.error(safe_message(exc))


def render_jira_admin(user) -> None:
    if user.role not in ("admin", "superadmin"):
        st.warning("Admin access required.")
        return

    if not JIRA_ENABLED:
        st.info("Jira integration is disabled.")
        return

    st.markdown(
        f"""
        <div style="background: var(--secondary-background-color); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
            <strong>Jira Instance:</strong> <code>{JIRA_BASE_URL or "Not configured"}</code> &nbsp;|&nbsp; 
            <strong>Product:</strong> {JIRA_PRODUCT}
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_map, tab_alias, tab_chain = st.tabs(
        ["🔗 Project Mapping", "🏷️ Transition Labels", "⛓️ Transition Chains"]
    )

    with tab_map:
        _render_project_mapping()
    with tab_alias:
        _render_aliases()
    with tab_chain:
        _render_chains()
