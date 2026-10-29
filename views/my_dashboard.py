"""My Dashboard — assignee queue + charts (all projects)."""
from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

from components.cards import page_header
from services import jira_service
from services.jira_service import JiraError
from services.rate_limit import limit_sensitive_api, RateLimitExceeded

logger = logging.getLogger(__name__)


def render(user) -> None:
    page_header("📊 My Dashboard")
    st.caption("Open issues assigned to you across all Jira projects (current user).")

    try:
        limit_sensitive_api(user.id, "my_queue")
    except RateLimitExceeded as exc:
        st.warning(str(exc))
        return

    with st.spinner("Loading your queue from Jira…"):
        try:
            issues = jira_service.fetch_my_queue(user.id)
        except JiraError as exc:
            st.error(str(exc))
            st.info("Link your Jira credentials under Personal settings → Jira connection.")
            return
        except Exception:
            logger.exception("My Dashboard queue failed")
            st.error("Could not load queue. Check Jira connection and server logs.")
            return

    if not issues:
        st.success("No open issues assigned to you.")
        return

    dash = jira_service.aggregate_queue_dashboard(issues)
    c1, c2, c3 = st.columns(3)
    c1.metric("Open assigned", dash["total"])
    overdue = dash["due_buckets"].get("Overdue", 0)
    c2.metric("Overdue", overdue)
    c3.metric("Due today", dash["due_buckets"].get("Due today", 0))

    st.subheader("By project and status")
    flat = dash.get("flat_project_status") or []
    if flat:
        df = pd.DataFrame(flat)
        try:
            pivot = df.pivot_table(index="project", columns="status", values="count", fill_value=0)
            st.bar_chart(pivot)
        except Exception:
            st.dataframe(df, use_container_width=True)
    else:
        st.caption("No status breakdown.")

    st.subheader("Due dates")
    due = dash.get("due_buckets") or {}
    if due:
        st.bar_chart(pd.DataFrame({"count": list(due.values())}, index=list(due.keys())))

    st.subheader("Issues")
    tree = jira_service.group_queue_by_project_type(issues)
    for project, types in tree.items():
        with st.expander(f"{project} ({sum(len(v) for v in types.values())})", expanded=False):
            for itype, items in types.items():
                st.markdown(f"**{itype}**")
                for it in items:
                    key = it.get("key") or "?"
                    summary = it.get("summary") or ""
                    status = it.get("status") or ""
                    st.markdown(f"- `{key}` · {status} — {summary}")
