"""Bulk Jira comment dialog + bulk-post log (B4)."""
from __future__ import annotations

import html
import logging

import streamlit as st
from sqlalchemy import select

from config import BULK_MAX_TICKETS, JIRA_BASE_URL, JIRA_ENABLED
from database import Category, Response, SessionLocal
from services import jira_service
from services.bulk_comment import BulkError, list_bulk_logs, parse_keys, post_bulk_comment, validate_same_project
from utils.personalization import PLACEHOLDER_HELP, personalize

logger = logging.getLogger(__name__)


def _library_choices(project_id):
    if project_id is None:
        return {}
    with SessionLocal() as db:
        rows = db.execute(
            select(Response.title, Response.response_body).join(Category)
            .where(Category.project_id == project_id).order_by(Category.sort_order, Response.sort_order)
        ).all()
    return {title: body for title, body in rows}


def render_bulk_log(user, *, everyone: bool = False, limit: int = 25) -> None:
    """Table of recent bulk runs. ``everyone`` (admins) shows all users."""
    logs = list_bulk_logs(None if everyone else user.id, limit)
    if not logs:
        st.caption("No bulk posts yet.")
        return
    rows = "".join(
        f"<tr><td>{l['when']:%Y-%m-%d %H:%M}</td><td>{html.escape(l['user'])}</td><td>{html.escape(l['prefix'])}</td>"
        f"<td>{l['ok']}/{l['total']}</td><td>{html.escape(', '.join(l['ok_keys'][:6]))}{' …' if len(l['ok_keys']) > 6 else ''}</td>"
        f"<td>{'<span class=jsl-bad>' + str(l['failed']) + '</span>' if l['failed'] else '0'}</td>"
        f"<td>{html.escape(l['text'][:70])}</td></tr>" for l in logs
    )
    st.markdown(
        '<div class="jsl-table-wrap"><table class="jsl-table"><thead><tr><th>When</th><th>By</th><th>Project</th>'
        f"<th>Posted</th><th>Tickets</th><th>Failed</th><th>Comment</th></tr></thead><tbody>{rows}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    failures = [(l, f) for l in logs for f in l["failed_items"]][:10]
    if failures:
        with st.expander(f"Failed tickets ({len(failures)} shown)"):
            for l, (key, msg) in failures:
                st.caption(f"{l['when']:%m-%d %H:%M} · **{key}** — {msg}")


@st.dialog("Bulk Jira comment", width="large")
def bulk_comment_dialog(user, project=None) -> None:
    if not JIRA_ENABLED or not JIRA_BASE_URL:
        st.error("Jira is not configured.")
        return
    if not jira_service.credential_status(user.id).get("connected"):
        st.warning("Connect Jira under Personal settings first.")
        return

    tab_new, tab_log = st.tabs(["New bulk comment", "My bulk log"])
    with tab_log:
        render_bulk_log(user)
    with tab_new:
        project_id = getattr(project, "id", None)
        linked = jira_service.get_jira_project_key(project_id) if project_id else None
        st.caption(f"Same comment on up to **{BULK_MAX_TICKETS}** tickets of one Jira project"
                   + (f" (**{linked}**)." if linked else "."))
        raw = st.text_area("Ticket keys or links", placeholder="PROJ-1, PROJ-2\nPROJ-3", height=80, key="bulk_keys")
        keys = parse_keys(raw)
        choices = _library_choices(project_id)
        pick = st.selectbox("Start from a library response (optional)", ["(write my own)"] + list(choices), key="bulk_pick")
        default = choices.get(pick, "") if pick != "(write my own)" else ""
        body = st.text_area("Comment", value=default, height=170, key=f"bulk_body_{pick}", help=PLACEHOLDER_HELP)

        c1, c2 = st.columns(2)
        time_raw = c1.text_input("Log time on each (optional)", placeholder="15m", key="bulk_time")
        internal = c2.checkbox("Internal comment (Jira Service Management)", key="bulk_internal")

        problem = None
        if keys:
            try:
                validate_same_project(keys, linked or "")
                if len(keys) > BULK_MAX_TICKETS:
                    problem = f"Limit is {BULK_MAX_TICKETS} tickets per run (you entered {len(keys)})."
            except BulkError as exc:
                problem = str(exc)
            st.caption(f"{len(keys)} ticket(s): {', '.join(keys[:12])}{' …' if len(keys) > 12 else ''}")
            if body.strip():
                st.markdown("**Preview (first ticket)**")
                st.code(personalize(body, user, project_id, recipient="Customer", context={"TICKET": keys[0], "PROJECT": keys[0].split("-")[0]}),
                        language=None, wrap_lines=True)
        if problem:
            st.error(problem)

        done = st.session_state.get("bulk_result")
        if done:
            st.success(f"Posted {len(done['ok'])} of {len(done['ok']) + len(done['failed'])} tickets.")
            for key, msg in done["failed"]:
                st.error(f"{key}: {msg}")
            if st.button("Start a new bulk comment", key="bulk_reset"):
                st.session_state.pop("bulk_result", None)
            else:
                return

        ready = bool(keys and body.strip() and not problem)
        confirm = st.checkbox(f"I confirm posting this comment to {len(keys)} ticket(s)", key="bulk_confirm", disabled=not ready)
        if st.button("Post to all", type="primary", key="bulk_go", disabled=not (ready and confirm)):
            with st.spinner(f"Posting to {len(keys)} tickets…"):
                try:
                    st.session_state["bulk_result"] = post_bulk_comment(
                        user.id, keys, body, linked or "", time_raw=time_raw, internal=internal)
                except BulkError as exc:
                    st.error(str(exc))
                    return
                except Exception:  # noqa: BLE001
                    logger.exception("Bulk comment run failed")
                    st.error("The bulk comment could not be completed. See the log for details.")
                    return
            done = st.session_state["bulk_result"]
            st.success(f"Posted {len(done['ok'])} of {len(done['ok']) + len(done['failed'])} tickets. Details are in the bulk log tab.")
            for key, msg in done["failed"]:
                st.error(f"{key}: {msg}")
