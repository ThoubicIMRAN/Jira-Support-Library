"""Jira action dialog — compact tabs (Ticket | Comment | Post)."""
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
    logger.exception("jira dialog error")
    return f"{type(exc).__name__}: {exc}"


def _sk(response_id: str, name: str) -> str:
    return f"jira_dlg_{response_id}_{name}"


def _linked_prefix(project) -> str | None:
    pid = getattr(project, "id", None)
    if pid is not None:
        try:
            key = jira_service.get_jira_project_key(int(pid))
            if key and str(key).strip():
                return str(key).strip().upper()
        except Exception:
            pass
    return (getattr(project, "key", None) or "").strip().upper() or None


def _ticket_prefix(key_or_url: str) -> str:
    try:
        from services.bulk_comment import parse_keys
        keys = parse_keys(key_or_url or "")
        if keys:
            return keys[0].split("-", 1)[0].upper()
    except Exception:
        pass
    text = (key_or_url or "").strip().upper()
    return text.split("-", 1)[0] if "-" in text else ""


def _assert_allowed(issue_key: str, project) -> None:
    required = _linked_prefix(project)
    if not required:
        raise JiraError(
            "Link this library project to a Jira key (Admin → Jira)."
        )
    prefix = (issue_key or "").split("-", 1)[0].upper()
    if prefix != required:
        raise JiraError(f"Only **{required}-*** tickets allowed. Got **{issue_key}**.")


def _clear(response_id: str, project_id) -> None:
    prefix = f"jira_dlg_{response_id}_"
    for name in list(st.session_state.keys()):
        if name.startswith(prefix):
            del st.session_state[name]
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
    project_id = getattr(project, "id", None)
    st.caption(
        f"{status.get('display_name') or 'you'} · {JIRA_PRODUCT}"
        + (f" · only **{required}-***" if required else " · ⚠️ no Jira link")
    )

    remembered = st.session_state.get(f"jira_last_ticket_{project_id or 'global'}", "")
    issue_store = _sk(response_id, "issue")

    # ---- Compact ticket bar ----
    r1, r2, r3, r4, r5 = st.columns([3.2, 0.9, 0.9, 1.1, 0.9])
    raw = r1.text_input(
        "Ticket",
        value=st.session_state.get(_sk(response_id, "raw"), remembered),
        placeholder=f"{required or 'KEY'}-123",
        key=_sk(response_id, "ticket_input"),
        label_visibility="collapsed",
    )
    do_load = r2.button("Load", type="primary", key=_sk(response_id, "load"))
    do_reload = r3.button("Reload", key=_sk(response_id, "reload"))
    if r4.button("Last", key=_sk(response_id, "same_last"), help="Reuse last comment body"):
        last = jira_service.get_last_comment(user.id)
        if last:
            st.session_state[_sk(response_id, "body_override")] = last
            st.toast("Last comment applied")
        else:
            st.toast("No previous comment")
    if r5.button("Reset", key=_sk(response_id, "reset")):
        _clear(response_id, project_id)
        st.toast("Cleared")

    if do_load or do_reload:
        with st.spinner("Loading ticket…"):
            try:
                pre = _ticket_prefix(raw)
                if required and pre and pre != required:
                    raise JiraError(f"Only **{required}-*** allowed (got {pre}).")
                issue = jira_service.load_issue(user.id, raw)
                _assert_allowed(issue["key"], project)
                st.session_state[issue_store] = issue
                st.session_state[_sk(response_id, "raw")] = raw
                # pending applied before Wiki user widget on next run
                st.session_state[_sk(response_id, "pending_mention_user")] = (
                    issue.get("reporter_username") or ""
                )
                st.session_state.pop(_sk(response_id, "body_override"), None)
                if project_id is not None:
                    st.session_state[f"jira_last_ticket_{project_id}"] = raw
                # no st.rerun() — keeps @st.dialog open
            except Exception as exc:
                st.error(_msg(exc))

    issue = st.session_state.get(issue_store)
    if not issue:
        st.info("Enter a ticket key and click **Load**.")
        return

    st.markdown(
        f"**{issue['key']}** · {issue.get('status')} · "
        f"{(issue.get('summary') or '')[:70]}  \n"
        f"Reporter: **{issue.get('reporter') or '—'}**"
        + (f" · Assignee: **{issue.get('assignee') or issue.get('assignee_name') or '—'}**"
           if issue.get('assignee') or issue.get('assignee_name') else "")
    )

    # Suggestions (compact)
    
    # Optional AD enrich (does not block if AD disabled)
    try:
        from services.ad_directory import ad_enabled, enrich_from_reporter
        if ad_enabled():
            ad = enrich_from_reporter(
                issue.get("reporter") or "",
                issue.get("reporter_username") or "",
            )
            if ad:
                st.caption(
                    f"AD: **{ad.get('display_name') or ad.get('username')}**"
                    + (f" · {ad.get('title')}" if ad.get('title') else "")
                    + (f" · {ad.get('department')}" if ad.get('department') else "")
                    + (f" · {ad.get('email')}" if ad.get('email') else "")
                )
                if ad.get("username") and not st.session_state.get(_sk(response_id, "mention_user")):
                    st.session_state[_sk(response_id, "pending_mention_user")] = ad["username"]
    except Exception:
        pass

    if project_id:
        try:
            suggestions = jira_service.suggest_library_for_issue(user.id, project_id, issue) or []
        except Exception:
            suggestions = []
        if suggestions:
            cols = st.columns(min(3, len(suggestions)))
            for i, sug in enumerate(suggestions[:3]):
                with cols[i]:
                    if st.button(f"📌 {sug['title'][:22]}", key=_sk(response_id, f"sug_{sug['id']}"), width="stretch"):
                        st.session_state[_sk(response_id, "body_override")] = sug["body"]
                        st.toast("Template applied")
                    fb1, fb2 = st.columns(2)
                    if fb1.button("👍", key=_sk(response_id, f"up_{sug['id']}")):
                        try:
                            from services.suggestion_feedback import record_vote
                            record_vote(user.id, str(sug["id"]), issue["key"], "up")
                            st.toast("Thanks")
                        except Exception:
                            pass
                    if fb2.button("👎", key=_sk(response_id, f"dn_{sug['id']}")):
                        try:
                            from services.suggestion_feedback import record_vote
                            record_vote(user.id, str(sug["id"]), issue["key"], "down")
                            st.toast("Thanks")
                        except Exception:
                            pass

    body_template = st.session_state.get(_sk(response_id, "body_override")) or response_body

    tab_c, tab_a, tab_m = st.tabs(["Comment", "Actions", "More"])

    with tab_c:
        g1, g2 = st.columns([2, 2])
        mention_mode = g1.radio(
            "Greeting",
            ["plain", "wiki", "none"],
            format_func=lambda x: {"plain": "Hello Name", "wiki": "Hello [~user]", "none": "Hello Customer"}[x],
            horizontal=True,
            key=_sk(response_id, "mention_mode"),
        )
        _pm = _sk(response_id, "pending_mention_user")
        if _pm in st.session_state:
            st.session_state[_sk(response_id, "mention_user")] = st.session_state.pop(_pm)
        mention_user = g2.text_input("Wiki user", key=_sk(response_id, "mention_user"))
        visibility = st.radio(
            "Visibility",
            ["customer", "internal"],
            format_func=lambda x: "Share with customer" if x == "customer" else "Comment internally",
            horizontal=True,
            key=_sk(response_id, "visibility"),
        )
        internal = visibility == "internal"

        is_closing = st.checkbox("Closing / resolve", key=_sk(response_id, "closing"))
        resolution_notes = ""
        if is_closing:
            # Apply pending values BEFORE widgets (Streamlit rule)
            conf_key = _sk(response_id, "conf_url")
            notes_key = _sk(response_id, "res_notes")
            pending_conf = _sk(response_id, "pending_conf_url")
            pending_notes = _sk(response_id, "pending_res_notes")
            if pending_conf in st.session_state:
                st.session_state[conf_key] = st.session_state.pop(pending_conf)
            if pending_notes in st.session_state:
                st.session_state[notes_key] = st.session_state.pop(pending_notes)

            conf_url = st.text_input("Confluence URL", key=conf_key)

            try:
                from services.resolution_notes_library import list_notes
                notes_lib = list_notes(project_id)
            except Exception:
                notes_lib = []
            if notes_lib:
                pick = st.selectbox(
                    "Saved resolution notes",
                    options=[None] + list(range(len(notes_lib))),
                    format_func=lambda i: "— pick —" if i is None else notes_lib[i]["title"],
                    key=_sk(response_id, "rn_pick"),
                )
                if pick is not None and st.button("Use saved note", key=_sk(response_id, "rn_use")):
                    st.session_state[pending_notes] = notes_lib[pick]["notes"]
                    if notes_lib[pick].get("confluence_url"):
                        st.session_state[pending_conf] = notes_lib[pick]["confluence_url"]
                    st.toast("Note selected — fields update below")

            cq1, cq2 = st.columns([3, 1])
            cq = cq1.text_input(
                "Search Confluence",
                key=_sk(response_id, "conf_q"),
                label_visibility="collapsed",
                placeholder="Search Confluence…",
            )
            if cq2.button("Search", key=_sk(response_id, "conf_search")) and (cq or "").strip():
                with st.spinner("Searching…"):
                    try:
                        from services.confluence_search import search_pages
                        hits = search_pages(user.id, cq.strip())
                        st.session_state[_sk(response_id, "conf_hits")] = hits
                    except Exception as exc:
                        st.error(_msg(exc))
            hits = st.session_state.get(_sk(response_id, "conf_hits")) or []
            if hits:
                pick = st.selectbox(
                    "Page",
                    range(len(hits)),
                    format_func=lambda i: hits[i]["title"][:50],
                    key=_sk(response_id, "conf_pick"),
                )
                if st.button("Use page", key=_sk(response_id, "conf_use")):
                    st.session_state[pending_conf] = hits[pick]["url"]
                    st.toast("URL selected")
            use_ai_notes = st.checkbox(
                "Polish with AI (slower)",
                value=False,
                key=_sk(response_id, "conf_ai"),
                help="Off = fast template from Confluence page. On = Ollama rewrite.",
            )
            if st.button("Draft notes", key=_sk(response_id, "conf_draft")):
                label = "Drafting with AI…" if use_ai_notes else "Fetching Confluence…"
                with st.spinner(label):
                    try:
                        from services.resolution_notes_service import draft_resolution_notes
                        notes = draft_resolution_notes(
                            user_id=user.id,
                            confluence_url=st.session_state.get(conf_key, "") or conf_url or "",
                            ticket_key=issue["key"],
                            ticket_summary=issue.get("summary") or "",
                            extra_context="",
                            use_ai=bool(use_ai_notes),
                        )
                        st.session_state[pending_notes] = notes or ""
                        st.toast("Notes ready")
                    except Exception as exc:
                        st.error(_msg(exc))

            if notes_key not in st.session_state:
                st.session_state[notes_key] = ""
            resolution_notes = st.text_area("Resolution notes", height=80, key=notes_key)
            if resolution_notes.strip() and st.button("Save note to library", key=_sk(response_id, "rn_save")):
                try:
                    from services.resolution_notes_library import save_note
                    save_note(
                        project_id=project_id,
                        title=f"{issue['key']} note",
                        notes=resolution_notes,
                        confluence_url=st.session_state.get(conf_key) or conf_url,
                        user_id=user.id,
                    )
                    st.toast("Saved to resolution library")
                except Exception as exp:
                    st.error(_msg(exp))

        body_template = st.session_state.get(_sk(response_id, "body_override")) or response_body
        reporter = issue.get("reporter") or "Customer"
        preview = build_comment_preview(
            body_template,
            reporter_name=reporter,
            mention_mode=mention_mode,
            mention_username=mention_user or issue.get("reporter_username") or "",
            resolution_notes=resolution_notes if is_closing else "",
            issue=issue,
        )
        try:
            from utils.personalization import personalize
            from services.workspace_service import designation_overrides

            overrides = designation_overrides(user.id)
            # Ensure project_id key type matches DB (int)
            pid = int(project_id) if project_id is not None else None
            ticket_ctx = {
                "TICKET": issue.get("key") or "",
                "SUMMARY": issue.get("summary") or "",
                "ASSIGNEE": issue.get("assignee") or issue.get("assignee_name") or "",
                "PROJECT": issue.get("project_key")
                or (issue.get("key") or "").split("-")[0],
                "STATUS": issue.get("status") or "",
            }
            preview = personalize(
                preview,
                user,
                pid,
                designation_overrides=overrides,
                recipient=reporter,
                context=ticket_ctx,
            )
        except Exception:
            pass
        with st.expander("Preview", expanded=True):
            st.code(preview, language=None, wrap_lines=True)
            st.caption("Tokens: @TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS @R")

    with tab_a:
        t1, t2 = st.columns(2)
        time_raw = t1.text_input("Log time", placeholder="15m / 1h 30m", key=_sk(response_id, "time"))
        transitions = []
        try:
            transitions = jira_service.list_transitions_friendly(
                user.id, issue["key"], jira_project_key=issue.get("project_key")
            ) or []
        except Exception:
            pass
        options = ["(none)"] + [(x.get("label") or x.get("name") or str(x.get("id"))) for x in transitions]
        choice = t2.selectbox("Transition", options, key=_sk(response_id, "transition"))
        transition_id = transition_label = None
        if choice != "(none)":
            for x in transitions:
                lab = x.get("label") or x.get("name") or str(x.get("id"))
                if lab == choice:
                    transition_id, transition_label = x["id"], lab
                    break

        uploads = st.file_uploader(
            "Attachments",
            accept_multiple_files=True,
            type=["png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log"],
            key=_sk(response_id, "uploads"),
        )
        if st.session_state.pop(_sk(response_id, "pending_clear_clip"), None):
            st.session_state[_sk(response_id, "clipboard_bridge")] = ""
        _paste_b64 = st.text_area(
            f"clipboard_bridge_{str(response_id).replace('-', '')[:12]}",
            key=_sk(response_id, "clipboard_bridge"),
            height=40,
            label_visibility="collapsed",
            placeholder="Optional: paste data-URL for screenshot",
        )

        req = required or (issue.get("project_key") or issue["key"].split("-")[0]).upper()
        with st.expander(f"Bulk ({req}-*)"):
            bulk_raw = st.text_input("Keys", key=_sk(response_id, "bulk"), placeholder=f"{req}-1, {req}-2")
            if st.button("Post bulk", key=_sk(response_id, "bulk_go")):
                from services.bulk_comment import parse_keys, post_bulk_comment
                with st.spinner("Bulk posting…"):
                    try:
                        result = post_bulk_comment(
                            user.id,
                            parse_keys(bulk_raw),
                            preview,
                            required_prefix=req,
                            time_raw=time_raw,
                            internal=internal,
                        )
                        if result.get("ok"):
                            st.success("OK: " + ", ".join(result["ok"]))
                        for f in result.get("failed") or []:
                            st.error(str(f))
                    except Exception as exc:
                        st.error(_msg(exc))

    with tab_m:
        lang = st.selectbox("Translate to", ["Original", "English", "French", "German", "Spanish"], key=_sk(response_id, "lang"))
        if st.button("Translate", key=_sk(response_id, "translate")) and lang != "Original":
            with st.spinner("Translating…"):
                try:
                    from services.ai_service import chat
                    src = st.session_state.get(_sk(response_id, "body_override")) or response_body
                    out = chat(
                        f"Translate this support reply into {lang}. Keep names and URLs. Output only translation.",
                        src,
                    )
                    if (out or "").strip():
                        st.session_state[_sk(response_id, "body_override")] = out.strip()
                        st.toast("Translated")
                except Exception as exc:
                    st.error(_msg(exc))
        if st.session_state.get(_sk(response_id, "body_override")) and st.button("Clear translation", key=_sk(response_id, "clear_tr")):
            st.session_state.pop(_sk(response_id, "body_override"), None)
            st.toast("Cleared translation")

    # ---- Post (always visible) ----
    if st.button("Post to Jira", type="primary", key=_sk(response_id, "post")):
        with st.spinner("Posting…"):
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
                results.append("Comment (internal)" if internal else "Comment (customer)")
            except Exception as exc:
                errors.append(f"Comment: {_msg(exc)}")

            for f in uploads or []:
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
                    errors.append(f"File: {_msg(exc)}")

            paste_val = st.session_state.get(_sk(response_id, "clipboard_bridge")) or ""
            if isinstance(paste_val, str) and paste_val.startswith("data:image"):
                try:
                    header, b64data = paste_val.split(",", 1)
                    ext = "jpg" if "jpeg" in header or "jpg" in header else "png"
                    raw_b = base64.b64decode(b64data)
                    fname = f"paste_{issue['key']}.{ext}"
                    if hasattr(jira_service, "add_attachment"):
                        jira_service.add_attachment(user.id, issue["key"], fname, raw_b, f"image/{ext}")
                    results.append(f"Screenshot {fname}")
                    st.session_state[_sk(response_id, "pending_clear_clip")] = True
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
                st.success(
                    f"**Posted to {issue['key']}**\n\n" + "\n".join(f"• {r}" for r in results)
                )
            for e in errors:
                st.error(e)
