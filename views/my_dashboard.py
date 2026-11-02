"""My Dashboard — assignee queue + charts (all projects) + SLA badges."""
from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from components.cards import page_header
from services import jira_service
from services.jira_service import JiraError
from services.rate_limit import limit_sensitive_api, RateLimitExceeded
from services.sla_utils import issue_badges, badge_label

logger = logging.getLogger(__name__)


def render(user) -> None:
    page_header("📊 My Dashboard")
    st.caption(
        "Your open Jira issues (`assignee = currentUser()`), all projects. "
        "Connect Jira under **Personal settings** if this is empty. "
        "Click **🎫** to pre-fill that ticket for the next Jira action."
    )

    c1, c2 = st.columns([1, 4])
    refresh = c1.button("Refresh", type="primary", key="mq_refresh")
    max_n = c2.slider("Max issues", 20, 200, 100, 10, key="mq_max")

    cache_key = f"my_queue_{user.id}"
    if refresh or cache_key not in st.session_state:
        try:
            limit_sensitive_api(user.id, "my_queue")
            with st.spinner("Loading your Jira queue…"):
                issues = jira_service.fetch_my_queue(user.id, max_results=int(max_n))
            st.session_state[cache_key] = issues
        except RateLimitExceeded as exc:
            st.warning(str(exc))
            issues = st.session_state.get(cache_key) or []
        except JiraError as exc:
            st.error(str(exc))
            issues = st.session_state.get(cache_key) or []
        except Exception:
            logger.exception("My queue load failed")
            st.error("Could not load your queue. Check Jira connection in Settings.")
            issues = st.session_state.get(cache_key) or []
    else:
        issues = st.session_state.get(cache_key) or []

    if not issues:
        st.info("No open issues assigned to you, or Jira is not connected.")
        return

    dash = jira_service.aggregate_queue_dashboard(issues)
    m1, m2, m3 = st.columns(3)
    m1.metric("Open assigned to you", dash["total"])
    n_overdue = sum(1 for it in issues if "overdue" in issue_badges(it))
    n_stale = sum(1 for it in issues if "stale" in issue_badges(it))
    m2.metric("Overdue", n_overdue)
    m3.metric("No recent update (14d+)", n_stale)

    tab_charts, tab_queue = st.tabs(["Charts", "My Queue"])

    with tab_charts:
        st.subheader("Issues by project and status")
        flat = dash.get("flat_project_status") or []
        if flat:
            df = pd.DataFrame(flat)
            pivot = df.pivot_table(
                index="project", columns="status", values="count", aggfunc="sum", fill_value=0
            )
            st.bar_chart(pivot)
            with st.expander("Table"):
                st.dataframe(pivot, width="stretch")
        else:
            st.caption("No data for project/status chart.")

        st.subheader("Due dates")
        due = dash.get("due_buckets") or {}
        if due:
            due_df = pd.DataFrame(
                {"bucket": list(due.keys()), "count": list(due.values())}
            ).set_index("bucket")
            st.bar_chart(due_df)
            overdue = due.get("Overdue") or 0
            if overdue:
                st.warning(f"**{overdue}** issue(s) overdue.")
            with st.expander("Due-date breakdown"):
                st.dataframe(due_df, width="stretch")

    with tab_queue:
        tree = jira_service.group_queue_by_project_type(issues)
        for project_key, types in tree.items():
            n_proj = sum(len(v) for v in types.values())
            with st.expander(f"**{project_key}** ({n_proj})", expanded=n_proj <= 8):
                for itype, rows in sorted(types.items(), key=lambda x: x[0]):
                    st.markdown(f"**{itype}** · {len(rows)}")
                    for it in rows:
                        due = it.get("duedate") or "—"
                        badges = issue_badges(it)
                        badge_txt = " ".join(badge_label(b) for b in badges)
                        cols = st.columns([1.4, 3.2, 1.2, 1.2, 1.4, 0.8])
                        cols[0].markdown(f"`{it['key']}`")
                        cols[1].caption(it.get("summary") or "")
                        cols[2].caption(it.get("status") or "")
                        cols[3].caption(f"Due {due}")
                        cols[4].caption(badge_txt or "—")
                        if cols[5].button(
                            "🎫",
                            key=f"mq_open_{it['key']}",
                            help="Pre-fill this ticket for the next Jira action dialog",
                        ):
                            st.session_state["mq_prefill_ticket"] = it["key"]
                            st.session_state["jira_last_ticket_global"] = it["key"]
                            st.toast(
                                f"Ticket {it['key']} ready — open a library response and click 🎫"
                            )
                    st.divider()
