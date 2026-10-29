"""Jira action dialog — single-screen compact layout + multi-step transitions."""
from __future__ import annotations

import re

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


        # ---- Mentions / participants (watchers) ----
        with st.expander("Mentions & participants", expanded=False):
            st.caption(
                "Mention in the comment with Jira wiki [~username]. "
                "Anyone written as @username in the template or fields is mentioned and **automatically added as a watcher/participant** on the ticket (whether they were already on it or not)."
            )
            assignee_name = issue.get("assignee") or ""
            assignee_id = issue.get("assignee_username") or ""
            c_m1, c_m2 = st.columns(2)
            mention_assignee = c_m1.checkbox(
                f"Mention assignee ({assignee_name or '—'})",
                value=False,
                key=_sk(response_id, "mention_assignee"),
                disabled=not bool(assignee_id or assignee_name),
            )
            c_m2.checkbox(
                "Add assignee as watcher",
                value=False,
                key=_sk(response_id, "watch_assignee"),
                disabled=not bool(assignee_id),
            )
            extra_mentions = st.text_input(
                "Other usernames to mention (comma-separated)",
                key=_sk(response_id, "extra_mentions"),
                placeholder="j.doe, a.smith",
                help="Server/DC: Jira username. Cloud: accountId or email if your site allows.",
            )
            st.checkbox(
                "Also add these users as watchers on the ticket",
                value=True,
                key=_sk(response_id, "extra_as_watchers"),
            )
            # Append mention lines into preview path via session for post
            mention_bits = []
            if mention_assignee and (assignee_id or assignee_name):
                mention_bits.append(f"[~{assignee_id}]" if assignee_id else assignee_name)
            for part in re.split(r"[,;\s]+", extra_mentions or ""):
                part = part.strip().lstrip("@")
                if part:
                    mention_bits.append(f"[~{part}]")
            st.session_state[_sk(response_id, "mention_line")] = (
                ("cc: " + " ".join(mention_bits)) if mention_bits else ""
            )

        # Dynamic [bracket] fields — library template unchanged; fill only for this post
        from services.template_fields import extract_bracket_fields, apply_bracket_fields

        _field_source = body_template or ""
        _bracket_labels = extract_bracket_fields(_field_source)
        # Also detect fields that remain after personalize (if greeting path left any)
        for _lbl in extract_bracket_fields(preview):
            if _lbl not in _bracket_labels:
                _bracket_labels.append(_lbl)
        field_values: dict[str, str] = {}
        if _bracket_labels:
            st.markdown("**Template fields**")
            st.caption("Fill-in for this ticket only (library unchanged). Paste plain URLs, markdown links, or HTML links — they are normalized for Jira.")
            for _lbl in _bracket_labels:
                _fkey = _sk(response_id, "tf_" + _lbl.lower().replace(" ", "_")[:40])
                field_values[_lbl] = st.text_input(_lbl, key=_fkey, placeholder=f"Text or paste link for [{_lbl}]")
            preview = apply_bracket_fields(preview, field_values)
            # Re-apply on body if some tokens only in template path
            preview = apply_bracket_fields(preview, field_values)

        _ml = st.session_state.get(_sk(response_id, "mention_line")) or ""
        if _ml and _ml not in (preview or ""):
            preview = ((preview or "").rstrip() + "\n\n" + _ml + "\n")

        from services.mention_utils import extract_at_usernames, to_jira_wiki_mentions
        preview = to_jira_wiki_mentions(preview or "")
        st.session_state[_sk(response_id, "auto_watch_from_body")] = extract_at_usernames(
            (st.session_state.get(_sk(response_id, "body_override")) or response_body or "")
            + " " + (st.session_state.get(_sk(response_id, "mention_line")) or "")
            + " " + (st.session_state.get(_sk(response_id, "extra_mentions")) or "")
        )

        with st.expander("Preview", expanded=True):
            st.code(preview, language=None, wrap_lines=True)
            st.caption("Tokens: @TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS @R · [custom fields] above")

    transition_chain = []
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
        # Multi-step transitions: order of selection = execution order
        label_to_id = {}
        labels_ordered = []
        for x in transitions:
            lab = x.get("label") or x.get("name") or str(x.get("id"))
            labels_ordered.append(lab)
            label_to_id[lab] = str(x.get("id"))
        selected_labels = t2.multiselect(
            "Transitions (order = steps)",
            labels_ordered,
            key=_sk(response_id, "transitions_multi"),
            help="Select one or more. Applied in list order before/with the comment.",
        )
        transition_chain = [(label_to_id[lab], lab) for lab in selected_labels if lab in label_to_id]
        transition_id = transition_chain[0][0] if len(transition_chain) == 1 else None
        transition_label = transition_chain[0][1] if len(transition_chain) == 1 else None

        uploads = st.file_uploader(
            "Attachments",
            accept_multiple_files=True,
            type=["png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log"],
            key=_sk(response_id, "uploads"),
        )
        if st.session_state.pop(_sk(response_id, "pending_clear_clip"), None):
            st.session_state[_sk(response_id, "clipboard_bridge")] = ""
        st.text_area(
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
                        # Use template + [fields], NOT preview (preview has first ticket's reporter)
                        from services.template_fields import apply_bracket_fields, extract_bracket_fields
                        _bulk_body = st.session_state.get(_sk(response_id, "body_override")) or response_body
                        _fv = {}
                        for _lbl in extract_bracket_fields(_bulk_body):
                            _fk = _sk(response_id, "tf_" + _lbl.lower().replace(" ", "_")[:40])
                            _fv[_lbl] = st.session_state.get(_fk, "")
                        _bulk_body = apply_bracket_fields(_bulk_body, _fv)
                        result = post_bulk_comment(
                            user.id,
                            parse_keys(bulk_raw),
                            _bulk_body,
                            required_prefix=req,
                            time_raw=time_raw,
                            internal=internal,
                            mention_mode=st.session_state.get(_sk(response_id, "mention_mode"), "plain"),
                            resolution_notes=st.session_state.get(_sk(response_id, "res_notes"), "") or "",
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


            # Watchers / participants — always add anyone @mentioned in the comment
            from services.mention_utils import extract_at_usernames
            watch_ids = []
            if st.session_state.get(_sk(response_id, "watch_assignee")) and issue.get("assignee_username"):
                watch_ids.append(issue["assignee_username"])
            for part in re.split(r"[,;\s]+", st.session_state.get(_sk(response_id, "extra_mentions")) or ""):
                part = (part or "").strip().lstrip("@")
                if part:
                    watch_ids.append(part)
            for u in st.session_state.get(_sk(response_id, "auto_watch_from_body")) or []:
                watch_ids.append(u)
            # Also scan final preview text for @user / already converted names
            for u in extract_at_usernames(preview or ""):
                watch_ids.append(u)
            # de-dupe preserve order
            _seen_w = set()
            _deduped = []
            for w in watch_ids:
                wl = (w or "").strip().lower()
                if wl and wl not in _seen_w:
                    _seen_w.add(wl)
                    _deduped.append(w.strip())
            watch_ids = _deduped
            if watch_ids:
                try:
                    werr = jira_service.add_watchers(user.id, issue["key"], watch_ids)
                    if werr:
                        for e in werr:
                            errors.append(f"Watcher: {e}")
                    else:
                        results.append("Watchers updated")
                except Exception as exc:
                    errors.append(f"Watchers: {_msg(exc)}")

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
            if transition_chain:
                try:
                    if len(transition_chain) == 1:
                        jira_service.transition_issue(
                            user.id, issue["key"], transition_chain[0][0],
                            label=transition_chain[0][1],
                        )
                        results.append(f"→ {transition_chain[0][1]}")
                    else:
                        applied = jira_service.multi_step_transition(
                            user.id,
                            issue["key"],
                            [x[0] for x in transition_chain],
                            labels=[x[1] for x in transition_chain],
                        )
                        results.append("→ " + " → ".join(applied))
                except Exception as exc:
                    errors.append(f"Transition: {_msg(exc)}")

            if results:
                st.success(
                    f"**Posted to {issue['key']}**\n\n" + "\n".join(f"• {r}" for r in results)
                )
            for e in errors:
                st.error(e)
