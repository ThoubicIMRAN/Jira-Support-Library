"""Jira action dialog — full feature set, strict project key, visible controls."""
from __future__ import annotations

import base64
import logging

import streamlit as st

from config import JIRA_BASE_URL, JIRA_ENABLED, JIRA_PRODUCT
from services import jira_service
from services.confluence_client import ConfluenceError
from services.jira_client import JiraError
from services.jira_text import build_comment_preview

logger = logging.getLogger(__name__)


def _msg(exc: Exception) -> str:
    if isinstance(exc, (JiraError, ValueError, ConfluenceError)):
        return str(exc)
    return "unexpected error (see server log)"


def _sk(response_id: str, name: str) -> str:
    return f"jira_dlg_{response_id}_{name}"


def _linked_prefix(project) -> str | None:
    """Required Jira project key for this library project."""
    pid = getattr(project, "id", None)
    if pid is None:
        return None
    try:
        key = jira_service.get_jira_project_key(int(pid))
        if key and str(key).strip():
            return str(key).strip().upper()
    except Exception:
        pass
    # Fallback: library project.key (often mirrors Jira key)
    lib = (getattr(project, "key", None) or "").strip().upper()
    return lib or None


def _ticket_prefix(key_or_url: str) -> str:
    from services.bulk_comment import parse_keys

    keys = parse_keys(key_or_url or "")
    if keys:
        return keys[0].split("-", 1)[0].upper()
    # raw KEY-123
    text = (key_or_url or "").strip().upper()
    if "-" in text and text.split("-", 1)[0].isalnum():
        return text.split("-", 1)[0]
    return ""


def _assert_allowed(issue_key: str, project) -> None:
    required = _linked_prefix(project)
    if not required:
        raise JiraError(
            "This library project has no Jira key linked. "
            "Admin must set it under Admin → Jira (project link) "
            "or set the library project key to match Jira (e.g. PROJ)."
        )
    prefix = (issue_key or "").split("-", 1)[0].upper()
    if prefix != required:
        raise JiraError(
            f"Only **{required}-*** tickets are allowed in this library project. "
            f"You entered **{issue_key}** ({prefix})."
        )


def _clear(response_id: str, project_id) -> None:
    for name in list(st.session_state.keys()):
        if name.startswith(f"jira_dlg_{response_id}_"):
            st.session_state.pop(name, None)
    if project_id is not None:
        st.session_state.pop(f"jira_last_ticket_{project_id}", None)


@st.dialog("Jira action", width="large")
def jira_action_dialog(user, project, response_body: str, response_id: str = "x") -> None:
    if not JIRA_ENABLED or not JIRA_BASE_URL:
        st.error("Jira is not configured.")
        return
    status = jira_service.credential_status(user.id)
    if not status.get("connected"):
        st.warning("Connect Jira under **Settings → Jira** first.")
        return

    required = _linked_prefix(project)
    st.caption(f"{status.get('display_name') or 'you'} · {JIRA_PRODUCT}")
    if required:
        st.info(f"This project only accepts tickets **{required}-***")
    else:
        st.error(
            "No Jira project key linked to this library project. "
            "Configure the link before posting."
        )

    project_id = getattr(project, "id", None)
    remembered = st.session_state.get(f"jira_last_ticket_{project_id or 'global'}", "")

    # ---- Ticket row + Reset (always visible) ----
    c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1.2, 1])
    raw = c1.text_input(
        "Ticket",
        value=st.session_state.get(_sk(response_id, "raw"), remembered),
        placeholder=f"{required or 'KEY'}-123 or URL",
        key=_sk(response_id, "ticket_input"),
        label_visibility="collapsed",
    )
    load_btn = c2.button("Load", type="primary", key=_sk(response_id, "load"))
    reload_btn = c3.button("Reload", key=_sk(response_id, "reload"))
    last_btn = c4.button("Last comment", key=_sk(response_id, "same_last"))
    reset_btn = c5.button("Reset", key=_sk(response_id, "reset"))

    # Quick command (shortcuts)

    if reset_btn:
        _clear(response_id, project_id)
        st.toast("Dialog cleared")
        st.rerun()

    issue_store = _sk(response_id, "issue")

    if load_btn or reload_btn:
        with st.spinner("Ticket is loading…"):
            try:
                # Pre-check prefix before API when possible
                pre = _ticket_prefix(raw)
                if required and pre and pre != required:
                    raise JiraError(
                        f"Only **{required}-*** tickets are allowed. You entered prefix **{pre}**."
                    )
                issue = jira_service.load_issue(user.id, raw)
                _assert_allowed(issue["key"], project)
                st.session_state[issue_store] = issue
                st.session_state[_sk(response_id, "raw")] = raw
                st.session_state[_sk(response_id, "mention_user")] = (
                    issue.get("reporter_username") or ""
                )
                if project_id is not None:
                    st.session_state[f"jira_last_ticket_{project_id}"] = raw
                st.success(issue["key"])
            except Exception as exc:
                st.error(_msg(exc))

    if last_btn:
        last = jira_service.get_last_comment(user.id)
        if last:
            st.session_state[_sk(response_id, "force_body")] = last
            st.info("Last comment body applied (greeting uses the loaded ticket).")
        else:
            st.warning("No previous comment in this session.")

    issue = st.session_state.get(issue_store)
    if not issue:
        st.info("Load a ticket to continue.")
        return

    st.markdown(
        f"**{issue['key']}** · {issue.get('status')} · {issue.get('summary', '')[:90]}  \n"
        f"Reporter: **{issue.get('reporter') or '—'}**"
    )

    # Suggestions from library (optional)
    if project_id:
        try:
            suggestions = jira_service.suggest_library_for_issue(user.id, project_id, issue)
        except Exception:
            suggestions = []
        if suggestions:
            cols = st.columns(min(3, len(suggestions)))
            for i, sug in enumerate(suggestions):
                label = f"Use: {sug['title'][:30]}"
                if cols[i].button(label, key=_sk(response_id, f"sug_{sug['id']}")):
                    st.session_state[_sk(response_id, "force_body")] = sug["body"]
                    st.rerun()

    body_template = st.session_state.pop(_sk(response_id, "force_body"), None) or response_body

    g1, g2 = st.columns(2)
    mention_mode = g1.radio(
        "Greeting",
        ["plain", "wiki", "none"],
        format_func=lambda x: {
            "plain": "Hello Name",
            "wiki": "Hello [~user]",
            "none": "Hello Customer",
        }[x],
        horizontal=True,
        key=_sk(response_id, "mention_mode"),
    )
    mention_user = g2.text_input("Wiki username", key=_sk(response_id, "mention_user"))

    visibility = st.radio(
        "Comment visibility",
        ["customer", "internal"],
        format_func=lambda x: "Share with customer" if x == "customer" else "Internal only",
        horizontal=True,
        key=_sk(response_id, "visibility"),
    )
    internal = visibility == "internal"

    # Language pack — always visible
    st.markdown("**Language pack**")
    l1, l2 = st.columns([2, 1])
    lang = l1.selectbox(
        "Translate preview to",
        ["Original", "English", "French", "German", "Spanish"],
        key=_sk(response_id, "lang"),
        label_visibility="collapsed",
    )
    if l2.button("Translate", key=_sk(response_id, "translate")) and lang != "Original":
        with st.spinner("Translating…"):
            try:
                from services.ai_service import chat

                out = chat(
                    f"Translate this support reply into {lang}. Keep names and URLs. Output only the translation.",
                    body_template,
                )
                if (out or "").strip():
                    st.session_state[_sk(response_id, "force_body")] = out.strip()
                    st.rerun()
            except Exception as exc:
                st.error(_msg(exc))

    is_closing = st.checkbox("Closing / resolve", key=_sk(response_id, "closing"))
    resolution_notes = ""
    if is_closing:
        st.markdown("**Confluence**")
        conf_url = st.text_input("Page URL", key=_sk(response_id, "conf_url"))
        cq = st.text_input("Search Confluence", placeholder="password reset", key=_sk(response_id, "conf_q"))
        if st.button("Search pages", key=_sk(response_id, "conf_search")) and (cq or "").strip():
            with st.spinner("Searching Confluence…"):
                try:
                    from services.confluence_search import search_pages

                    hits = search_pages(user.id, cq.strip())
                    st.session_state[_sk(response_id, "conf_hits")] = hits
                    if not hits:
                        st.info("No pages found.")
                except Exception as exc:
                    st.error(_msg(exc))
        hits = st.session_state.get(_sk(response_id, "conf_hits")) or []
        if hits:
            pick = st.selectbox(
                "Pick page",
                range(len(hits)),
                format_func=lambda i: f"{hits[i]['title']} ({hits[i].get('space') or ''})",
                key=_sk(response_id, "conf_pick"),
            )
            if st.button("Use selected page", key=_sk(response_id, "conf_use")):
                st.session_state[_sk(response_id, "conf_url")] = hits[pick]["url"]
                st.rerun()
        conf_extra = st.text_input("Extra context", key=_sk(response_id, "conf_extra"))
        if st.button("Draft notes from Confluence", key=_sk(response_id, "conf_draft")):
            with st.spinner("AI is generating the response…"):
                try:
                    from services.resolution_notes_service import draft_resolution_notes

                    notes = draft_resolution_notes(
                        user_id=user.id,
                        confluence_url=st.session_state.get(_sk(response_id, "conf_url"), "") or conf_url or "",
                        ticket_key=issue["key"],
                        ticket_summary=issue.get("summary") or "",
                        extra_context=conf_extra or "",
                    )
                    st.session_state[_sk(response_id, "res_notes")] = notes or ""
                    st.rerun()
                except Exception as exc:
                    st.error(_msg(exc))
        if _sk(response_id, "res_notes") not in st.session_state:
            st.session_state[_sk(response_id, "res_notes")] = ""
        resolution_notes = st.text_area("Resolution notes", height=100, key=_sk(response_id, "res_notes"))

    reporter = issue.get("reporter") or "Customer"
    preview = build_comment_preview(
        body_template,
        reporter_name=reporter,
        mention_mode=mention_mode,
        mention_username=mention_user or issue.get("reporter_username") or "",
        resolution_notes=resolution_notes if is_closing else "",
    )
    try:
        from utils.personalization import personalize

        preview = personalize(
            preview, user, project_id, recipient=reporter,
            context={
                "TICKET": issue.get("key"), "SUMMARY": issue.get("summary"),
                "ASSIGNEE": issue.get("assignee"), "STATUS": issue.get("status"),
                "PROJECT": issue.get("project_key"),
            },
        )
    except Exception:
        pass

    with st.expander("Comment preview", expanded=True):
        st.code(preview, language=None, wrap_lines=True)

    st.markdown("**Attachments**")
    try:
        from components.clipboard_paste import clipboard_paste_zone

        clipboard_paste_zone(key=str(response_id).replace("-", "")[:12])
    except Exception:
        logger.exception("Clipboard paste component failed")
    st.text_area(
        f"clipboard_bridge_{str(response_id).replace('-', '')[:12]}",
        key=_sk(response_id, "clipboard_bridge"),
        height=60,
        label_visibility="collapsed",
        placeholder="After Ctrl+V in the zone, image data may appear here",
    )
    uploads = st.file_uploader(
        "Browse files",
        accept_multiple_files=True,
        type=["png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log"],
        key=_sk(response_id, "uploads"),
    )

    t1, t2 = st.columns(2)
    time_raw = t1.text_input("Log time", placeholder="15m / 1h 30m", key=_sk(response_id, "time"))
    transitions = []
    try:
        transitions = jira_service.list_transitions_friendly(
            user.id, issue["key"], jira_project_key=issue.get("project_key")
        ) or []
    except Exception:
        pass
    options = ["(no transition)"] + [(x.get("label") or x.get("name") or str(x.get("id"))) for x in transitions]
    choice = t2.selectbox("Transition", options, key=_sk(response_id, "transition"))
    transition_id = transition_label = None
    if choice != "(no transition)":
        for x in transitions:
            lab = x.get("label") or x.get("name") or str(x.get("id"))
            if lab == choice:
                transition_id, transition_label = x["id"], lab
                break

    st.caption("Need the same comment on many tickets? Use **📣 Bulk comment** on the project page.")

    posted_key = _sk(response_id, "posted")
    if st.session_state.get(posted_key):
        st.success(st.session_state[posted_key])
        if st.button("Post another update", key=_sk(response_id, "again")):
            st.session_state.pop(posted_key, None)
        else:
            return

    do_post = st.button("Post to Jira", type="primary", key=_sk(response_id, "post"))
    if do_post:
        with st.spinner("Posting to Jira…"):
            results, errors = [], []
            try:
                _assert_allowed(issue["key"], project)
            except Exception as exc:
                st.error(_msg(exc))
                return
            try:
                try:
                    jira_service.add_comment(user.id, issue["key"], preview, internal=internal)
                except TypeError:
                    jira_service.add_comment(user.id, issue["key"], preview)
                results.append("Comment" + (" (internal)" if internal else " (customer)"))
            except Exception as exc:
                errors.append(f"Comment: {_msg(exc)}")

            if uploads:
                for f in uploads:
                    try:
                        data = f.getvalue()
                        if hasattr(jira_service, "add_attachment"):
                            jira_service.add_attachment(user.id, issue["key"], f.name, data, f.type)
                        else:
                            jira_service.get_client_for_user(user.id).add_attachment(
                                issue["key"], f.name, data, f.type
                            )
                        results.append(f"File {f.name}")
                    except Exception as exc:
                        errors.append(f"File {f.name}: {_msg(exc)}")

            paste_val = st.session_state.get(_sk(response_id, "clipboard_bridge")) or ""
            if isinstance(paste_val, str) and paste_val.startswith("data:image"):
                try:
                    header, b64data = paste_val.split(",", 1)
                    ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
                    raw_b = base64.b64decode(b64data)
                    fname = f"paste_{issue['key']}.{ext}"
                    if hasattr(jira_service, "add_attachment"):
                        jira_service.add_attachment(user.id, issue["key"], fname, raw_b, f"image/{ext}")
                    else:
                        jira_service.get_client_for_user(user.id).add_attachment(
                            issue["key"], fname, raw_b, f"image/{ext}"
                        )
                    results.append(f"Pasted screenshot ({fname})")
                    st.session_state[_sk(response_id, "clipboard_bridge")] = ""
                except Exception as exc:
                    errors.append(f"Paste: {_msg(exc)}")

            if (time_raw or "").strip():
                try:
                    spent = jira_service.log_work(user.id, issue["key"], time_raw)
                    results.append(f"Time {spent}")
                except Exception as exc:
                    errors.append(f"Worklog: {_msg(exc)}")
            if transition_id:
                try:
                    jira_service.transition_issue(
                        user.id, issue["key"], transition_id, label=transition_label
                    )
                    results.append(f"→ {transition_label}")
                except Exception as exc:
                    errors.append(f"Transition: {_msg(exc)}")

            if results:
                summary = f"**Post confirmation — {issue['key']}**\n\n" + "\n".join(f"• {r}" for r in results)
                st.success(summary)
                if not errors:
                    st.session_state[posted_key] = summary  # blocks an accidental second post
            for e in errors:
                st.error(e)
