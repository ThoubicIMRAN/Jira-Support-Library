"""Jira action dialog — single-screen layout, people pickers, safety hardened."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import uuid

import streamlit as st

from config import JIRA_BASE_URL, JIRA_ENABLED, JIRA_MAX_ATTACHMENT_MB, JIRA_PRODUCT
from services import jira_service
from services.confluence_client import ConfluenceError
from services.jira_client import JiraError
from services.jira_dialog_safety import (
    action_plan_lines,
    execution_fingerprint,
    unresolved_placeholders,
)
from services.jira_dialog_helpers import first_step_problem, preset_chain
from services.jira_post_flow import run_post_steps
from services.jira_transition_chains import chains_for_project
from services.jira_text import build_comment_preview
from utils.errors import log_ignored

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / validation
# ---------------------------------------------------------------------------
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}-\d{1,8}$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
_WIKI_USER_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,64}$")
_CONF_URL_RE = re.compile(r"^https?://[^\s]+$")
_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,")
_EXT_WHITELIST = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log"}
_MIME_WHITELIST = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
}
_MAX_PASTE_BYTES = 8 * 1024 * 1024  # 8 MB
_MAX_ATTACH_BYTES = JIRA_MAX_ATTACHMENT_MB * 1024 * 1024
_MAX_QUERY_LEN = 200
_MAX_EXTRA_USERS = 25
_DEBUG = False  # flip to True locally; never in prod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_text(value: object, limit: int = 400) -> str:
    """Make a user-influenced string safe for Markdown/error rendering."""
    s = str(value or "")
    s = s.replace("\x00", "")
    # strip Markdown link/paren/angle soup and control chars
    s = re.sub(r"[\[\]\(\)<>`]", "", s)
    s = re.sub(r"[\x01-\x08\x0b-\x1f]", "", s)
    return s[:limit]


def _msg(exc: Exception) -> str:
    if isinstance(exc, (JiraError, ValueError, ConfluenceError)):
        return _safe_text(str(exc))
    logger.exception("jira dialog error")
    if _DEBUG:
        return _safe_text(f"{type(exc).__name__}: {exc}")
    return "Unexpected error — see logs."


def _safe_wiki_user(raw: str) -> str | None:
    s = (raw or "").strip()
    return s if _WIKI_USER_RE.match(s) else None


def _safe_filename(name: str) -> str:
    base = (name or "file").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f]", "", base).strip() or "file"
    return base[:180]


def _safe_conf_url(url: str) -> str | None:
    s = (url or "").strip()
    return s if _CONF_URL_RE.match(s) else None


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
            logger.warning(
                "get_jira_project_key failed for project %s", pid, exc_info=True
            )
    fallback = (getattr(project, "key", None) or "").strip().upper()
    return fallback or None


def _assert_allowed(issue_key: str, project) -> None:
    required = _linked_prefix(project)
    if not required:
        raise JiraError("Link this library project to a Jira key (Admin → Jira).")
    prefix = (issue_key or "").split("-", 1)[0].upper()
    if not _PREFIX_RE.match(prefix):
        raise JiraError(f"Invalid issue key: `{_safe_text(issue_key)}`")
    if prefix != required:
        raise JiraError(
            f"Only **{_safe_text(required)}-*** tickets allowed. Got **{_safe_text(issue_key)}**."
        )


def _clear_dialog_state(response_id: str, project_id) -> None:
    prefix = f"jira_dlg_{response_id}_"
    for name in list(st.session_state.keys()):
        if name.startswith(prefix):
            del st.session_state[name]
    if project_id is not None:
        st.session_state.pop(f"jira_last_ticket_{project_id}", None)


def _apply_pending(response_id: str, widget_name: str) -> None:
    """Transfer a pending_<name> shadow value into the widget-owned key before widget creation."""
    pending = _sk(response_id, f"pending_{widget_name}")
    if pending in st.session_state:
        st.session_state[_sk(response_id, widget_name)] = st.session_state.pop(pending)


def _collect_watch_ids(response_id: str, issue: dict) -> list[str]:
    ids: list[str] = []
    if st.session_state.get(_sk(response_id, "watch_assignee")):
        aid = _safe_wiki_user(issue.get("assignee_username") or "")
        if aid:
            ids.append(aid)
    if st.session_state.get(_sk(response_id, "extra_as_watchers"), True):
        raw = st.session_state.get(_sk(response_id, "extra_mentions")) or ""
        for part in re.split(r"[,;\s]+", raw):
            u = _safe_wiki_user(part.lstrip("@"))
            if u:
                ids.append(u)
        ids.extend(st.session_state.get(_sk(response_id, "auto_watch_from_body")) or [])
    # de-dupe, cap
    seen, out = set(), []
    for u in ids:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out[:_MAX_EXTRA_USERS]


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
@st.dialog("Jira action", width="medium")
def jira_action_dialog(
    user, project, response_body: str, response_id: str = "x"
) -> None:
    if not JIRA_ENABLED or not JIRA_BASE_URL:
        st.error("Jira is not configured.")
        return
    status = jira_service.credential_status(user.id)
    if not status.get("connected"):
        st.warning("Connect Jira under **Settings → Jira** first.")
        return

    required = _linked_prefix(project)
    project_id = getattr(project, "id", None)
    idem_key = _sk(response_id, "idem")
    if idem_key not in st.session_state:
        st.session_state[idem_key] = uuid.uuid4().hex

    # ---------------- header ----------------
    st.caption(
        f"{_safe_text(status.get('display_name') or 'you')} · {JIRA_PRODUCT}"
        + (f" · only **{required}-***" if required else " · ⚠️ no Jira link")
    )

    remembered = (
        st.session_state.pop("mq_prefill_ticket", None)
        or st.session_state.get(f"jira_last_ticket_{project_id or 'global'}", "")
        or st.session_state.get("jira_last_ticket_global", "")
        or ""
    )
    issue_store = _sk(response_id, "issue")
    posted_key = _sk(response_id, "posted_ok")

    # ---------------- ticket bar ----------------
    r1, r2, r3, r4 = st.columns([3.4, 1, 1.1, 1])
    raw = r1.text_input(
        "Ticket",
        value=st.session_state.get(_sk(response_id, "raw"), remembered),
        placeholder=f"{required or 'KEY'}-123",
        key=_sk(response_id, "ticket_input"),
        label_visibility="collapsed",
    )
    do_load = r2.button(
        "Load", type="primary", key=_sk(response_id, "load"), width="stretch"
    )
    do_reload = r3.button("Reload", key=_sk(response_id, "reload"), width="stretch")
    if r4.button("Reset", key=_sk(response_id, "reset"), width="stretch"):
        _clear_dialog_state(response_id, project_id)
        st.toast("Cleared")
        return  # nothing else this run; user starts fresh

    if do_load or do_reload:
        with st.spinner("Loading ticket…"):
            try:
                key_in = (raw or "").strip().upper()
                if not _KEY_RE.match(key_in):
                    raise JiraError("Enter a valid ticket key, e.g. `ABC-123`.")
                if required and key_in.split("-", 1)[0] != required:
                    raise JiraError(f"Only **{required}-*** allowed.")
                issue = jira_service.load_issue(user.id, key_in)
                _assert_allowed(issue["key"], project)
                st.session_state[issue_store] = issue
                st.session_state[_sk(response_id, "raw")] = key_in
                st.session_state[_sk(response_id, "pending_mention_user")] = (
                    issue.get("reporter_username") or ""
                )
                st.session_state.pop(_sk(response_id, "body_override"), None)
                if project_id is not None:
                    st.session_state[f"jira_last_ticket_{project_id}"] = key_in
                st.session_state["jira_last_ticket_global"] = key_in
            except Exception as exc:
                st.error(_msg(exc))
                return

    issue = st.session_state.get(issue_store)
    if not issue:
        st.info("Enter a ticket key and click **Load**.")
        return

    # ---------------- issue summary ----------------
    st.markdown(
        f"##### {_safe_text(issue['key'])} · {_safe_text(issue.get('status') or '—')}\n"
        f"{_safe_text((issue.get('summary') or '')[:120])}"
    )
    meta1, meta2 = st.columns(2)
    meta1.caption(f"Reporter: **{_safe_text(issue.get('reporter') or '—')}**")
    meta2.caption(
        f"Assignee: **{_safe_text(issue.get('assignee') or issue.get('assignee_name') or '—')}**"
    )

    # optional AD enrich
    try:
        from services.ad_directory import ad_enabled, enrich_from_reporter

        if ad_enabled():
            ad = enrich_from_reporter(
                issue.get("reporter") or "", issue.get("reporter_username") or ""
            )
            if ad:
                st.caption(
                    "AD: "
                    + " · ".join(
                        filter(
                            None,
                            [
                                _safe_text(
                                    ad.get("display_name") or ad.get("username")
                                ),
                                _safe_text(ad.get("title") or ""),
                                _safe_text(ad.get("department") or ""),
                                _safe_text(ad.get("email") or ""),
                            ],
                        )
                    )
                )
                if ad.get("username"):
                    _u = _safe_wiki_user(ad["username"])
                    if _u and not st.session_state.get(
                        _sk(response_id, "mention_user")
                    ):
                        st.session_state[_sk(response_id, "pending_mention_user")] = _u
    except Exception:
        logger.debug("AD enrich skipped", exc_info=True)

    # suggestions
    if project_id:
        try:
            suggestions = (
                jira_service.suggest_library_for_issue(user.id, project_id, issue) or []
            )
        except Exception:
            logger.warning("suggest_library_for_issue failed", exc_info=True)
            suggestions = []
        if suggestions:
            st.markdown(
                '<div class="jsl-jd-label">Suggested replies</div>',
                unsafe_allow_html=True,
            )
            cols = st.columns(min(3, len(suggestions)))
            for i, sug in enumerate(suggestions[:3]):
                with cols[i]:
                    if st.button(
                        f"📌 {_safe_text(sug.get('title') or '')[:24]}",
                        key=_sk(response_id, f"sug_{sug.get('id')}"),
                        width="stretch",
                    ):
                        st.session_state[_sk(response_id, "body_override")] = (
                            sug.get("body") or ""
                        )
                        st.toast("Template applied")
                    fb1, fb2, _fb = st.columns([1, 1, 8])
                    if fb1.button("👍", key=_sk(response_id, f"up_{sug.get('id')}")):
                        try:
                            from services.suggestion_feedback import record_vote

                            record_vote(user.id, str(sug.get("id")), issue["key"], "up")
                            st.toast("Thanks")
                        except Exception:
                            log_ignored(__name__)
                    if fb2.button("👎", key=_sk(response_id, f"dn_{sug.get('id')}")):
                        try:
                            from services.suggestion_feedback import record_vote

                            record_vote(
                                user.id, str(sug.get("id")), issue["key"], "down"
                            )
                            st.toast("Thanks")
                        except Exception:
                            log_ignored(__name__)

    # ---------------- greeting + visibility ----------------
    st.markdown(
        '<div class="jsl-jd-label">Reply & visibility</div>', unsafe_allow_html=True
    )
    mention_mode = st.radio(
        "Greeting",
        ["plain", "wiki", "none"],
        format_func=lambda x: {
            "plain": "Hello Name",
            "wiki": "Hello [~user]",
            "none": "Hello Customer",
        }[x],
        horizontal=True,
        key=_sk(response_id, "mention_mode"),
        label_visibility="collapsed",
    )
    _apply_pending(response_id, "mention_user")
    g2, g3 = st.columns([3, 2])
    mention_user = g2.text_input(
        "Wiki user",
        key=_sk(response_id, "mention_user"),
        disabled=mention_mode != "wiki",
        placeholder="username to greet (Hello [~user])",
    )
    visibility = g3.radio(
        "Visibility",
        ["customer", "internal"],
        format_func=lambda x: "Customer" if x == "customer" else "Internal",
        horizontal=True,
        key=_sk(response_id, "visibility"),
    )
    internal = visibility == "internal"
    st.markdown(
        '<span class="jsl-jd-vis jsl-jd-vis-internal">Internal only · not shared with the customer</span>'
        if internal
        else '<span class="jsl-jd-vis jsl-jd-vis-customer">Visible to the customer</span>',
        unsafe_allow_html=True,
    )

    # ---------------- people ----------------
    with st.expander("People (mentions & watchers)", expanded=False):
        st.caption(
            "Mention with Jira wiki `[~username]`. Selected people are also added as watchers on post."
        )
        chip_cols = st.columns(4)
        reporter_name = issue.get("reporter") or ""
        reporter_id = issue.get("reporter_username") or ""
        assignee_name = issue.get("assignee") or ""
        assignee_id = issue.get("assignee_username") or ""
        if chip_cols[0].button(
            f"Reporter: {_safe_text(reporter_name)[:18] or '—'}",
            key=_sk(response_id, "chip_rep"),
            disabled=not bool(reporter_id or reporter_name),
            help="Set wiki user to reporter",
        ):
            u = _safe_wiki_user(reporter_id or reporter_name)
            if u:
                st.session_state[_sk(response_id, "pending_mention_user")] = u
                st.toast("Reporter set as wiki user")
        if chip_cols[1].button(
            f"Assignee: {_safe_text(assignee_name)[:18] or '—'}",
            key=_sk(response_id, "chip_asg"),
            disabled=not bool(assignee_id or assignee_name),
            help="Mention + watch assignee",
        ):
            st.session_state[_sk(response_id, "pending_mention_assignee")] = True
            st.session_state[_sk(response_id, "pending_watch_assignee")] = True
            st.toast("Assignee will be mentioned & watched")

        _apply_pending(response_id, "mention_assignee")
        _apply_pending(response_id, "watch_assignee")
        chip_cols[2].checkbox(
            "Mention assignee",
            key=_sk(response_id, "mention_assignee"),
            disabled=not bool(assignee_id or assignee_name),
        )
        chip_cols[3].checkbox(
            "Watch assignee",
            key=_sk(response_id, "watch_assignee"),
            disabled=not bool(assignee_id),
        )

        # Jira user search
        pq1, pq2 = st.columns([3, 1])
        people_q = pq1.text_input(
            "Search Jira users",
            key=_sk(response_id, "people_q"),
            placeholder="name or username…",
            label_visibility="collapsed",
        )
        if pq2.button("Search", key=_sk(response_id, "people_search")):
            q = (people_q or "").strip()[:_MAX_QUERY_LEN]
            if not q:
                st.toast("Enter a search term")
            else:
                with st.spinner("Searching users…"):
                    try:
                        hits = jira_service.search_jira_users(user.id, q) or []
                        st.session_state[_sk(response_id, "people_hits")] = hits
                    except Exception as exc:
                        st.error(_msg(exc))
                        st.session_state[_sk(response_id, "people_hits")] = []
        people_hits = st.session_state.get(_sk(response_id, "people_hits")) or []
        if people_hits:
            for i, u in enumerate(people_hits[:8]):
                label = (
                    u.get("displayName") or u.get("name") or u.get("accountId") or "?"
                )
                ident_raw = (u.get("name") or u.get("accountId") or "").strip()
                ident = _safe_wiki_user(ident_raw)
                email = _safe_text(u.get("emailAddress") or "")
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.caption(
                    f"**{_safe_text(label)}**"
                    + (f" · {email}" if email else "")
                    + (f" · `{ident}`" if ident else "")
                )
                if c2.button(
                    "Wiki", key=_sk(response_id, f"p_wiki_{i}"), disabled=not ident
                ):
                    st.session_state[_sk(response_id, "pending_mention_user")] = ident
                    st.toast(f"Wiki user → {ident}")
                if c3.button(
                    "+Watch", key=_sk(response_id, f"p_watch_{i}"), disabled=not ident
                ):
                    cur = st.session_state.get(_sk(response_id, "extra_mentions")) or ""
                    parts = [p.strip() for p in re.split(r"[,;\s]+", cur) if p.strip()]
                    if ident not in parts and len(parts) < _MAX_EXTRA_USERS:
                        parts.append(ident)
                    st.session_state[_sk(response_id, "pending_extra_mentions")] = (
                        ", ".join(parts)
                    )
                    st.session_state[_sk(response_id, "pending_extra_as_watchers")] = (
                        True
                    )
                    st.toast(f"Added watcher {ident}")

        _apply_pending(response_id, "extra_mentions")
        _apply_pending(response_id, "extra_as_watchers")
        extra_mentions = st.text_input(
            "Other usernames (comma-separated)",
            key=_sk(response_id, "extra_mentions"),
            placeholder="j.doe, a.smith",
            help="Server/DC: username. Cloud: accountId when required.",
        )
        st.checkbox(
            "Also add these users as watchers",
            value=True,
            key=_sk(response_id, "extra_as_watchers"),
        )

        # validate extra_mentions
        bad_tokens = []
        mention_bits = []
        if st.session_state.get(_sk(response_id, "mention_assignee")) and assignee_id:
            a = _safe_wiki_user(assignee_id)
            if a:
                mention_bits.append(f"[~{a}]")
        for part in re.split(r"[,;\s]+", extra_mentions or ""):
            if not part:
                continue
            u = _safe_wiki_user(part.lstrip("@"))
            if u:
                mention_bits.append(f"[~{u}]")
            else:
                bad_tokens.append(_safe_text(part, 24))
        if bad_tokens:
            st.warning("Ignored invalid usernames: " + ", ".join(bad_tokens[:8]))
        st.session_state[_sk(response_id, "mention_line")] = (
            ("cc: " + " ".join(mention_bits)) if mention_bits else ""
        )

    # ---------------- actions: time + transitions + attachments ----------------
    st.markdown('<div class="jsl-jd-label">Actions</div>', unsafe_allow_html=True)
    t1, t2 = st.columns(2)
    time_raw = t1.text_input(
        "Log time", placeholder="15m / 1h 30m", key=_sk(response_id, "time")
    )
    cache_k = _sk(response_id, "tr_cache_" + str(issue.get("key") or ""))
    transitions = st.session_state.get(cache_k) or []
    if not transitions:
        try:
            transitions = (
                jira_service.list_transitions_friendly(
                    user.id, issue["key"], jira_project_key=issue.get("project_key")
                )
                or []
            )
            st.session_state[cache_k] = transitions
        except Exception:
            logger.exception("list transitions failed")
            transitions = []
    label_to_id = {}
    labels_ordered = []
    for x in transitions:
        lab = x.get("label") or x.get("name") or str(x.get("id"))
        labels_ordered.append(lab)
        label_to_id[lab] = str(x.get("id"))
    # Saved chains (Admin Settings > Jira > Transition chains) run as one preset.
    preset_steps: list[str] = []
    chain_problem = ""
    try:
        saved_chains = chains_for_project(issue.get("project_key"))
    except Exception:  # noqa: BLE001 - presets are optional; the manual picker still works
        logger.exception("could not load transition chains")
        saved_chains = []
    if saved_chains:
        preset_key = _sk(response_id, "chain_preset")
        preset_options = ["None", *[c["name"] for c in saved_chains]]
        if st.session_state.get(preset_key) not in preset_options:
            st.session_state.pop(preset_key, None)  # the chain was renamed or deleted
        preset_name = t2.selectbox(
            "Transition chain",
            preset_options,
            key=preset_key,
            help="Runs a saved set of status changes one after another, each checked against the ticket's current status.",
        )
        preset_steps = next((c["steps"] for c in saved_chains if c["name"] == preset_name), [])
    selected_labels = t2.multiselect(
        "Transitions (order = steps)",
        labels_ordered,
        key=_sk(response_id, "transitions_multi"),
        disabled=bool(preset_steps),
        help="Select one or more. Applied in list order with the comment."
        if not preset_steps
        else "A transition chain is selected. Choose None above to pick transitions by hand.",
    )
    if preset_steps:
        transition_chain = preset_chain(preset_steps)
        t2.caption("Steps: " + " \u2192 ".join(preset_steps))
        chain_problem = first_step_problem(preset_steps, transitions)
        if chain_problem:
            t2.warning(_safe_text(chain_problem, 300))
    else:
        transition_chain = [
            (label_to_id[lab], lab) for lab in selected_labels if lab in label_to_id
        ]

    uploads = st.file_uploader(
        "Attachments",
        accept_multiple_files=True,
        type=sorted(_EXT_WHITELIST),
        key=_sk(response_id, "uploads"),
    )
    if st.session_state.pop(_sk(response_id, "pending_clear_clip"), None):
        st.session_state[_sk(response_id, "clipboard_bridge")] = ""
    with st.expander("Paste a screenshot (advanced)", expanded=False):
        st.text_area(
            "Screenshot data-URL",
            key=_sk(response_id, "clipboard_bridge"),
            height=60,
            label_visibility="collapsed",
            placeholder="data:image/png;base64,…",
        )

    # ---------------- resolution (only when closing) ----------------
    is_closing = st.checkbox("Closing / resolve", key=_sk(response_id, "closing"))
    resolution_notes = ""
    if is_closing:
        with st.expander("Resolution details", expanded=True):
            conf_key = _sk(response_id, "conf_url")
            notes_key = _sk(response_id, "res_notes")
            _apply_pending(response_id, "conf_url")
            _apply_pending(response_id, "res_notes")

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
                    format_func=lambda i: (
                        "— pick —"
                        if i is None
                        else _safe_text(notes_lib[i]["title"], 60)
                    ),
                    key=_sk(response_id, "rn_pick"),
                )
                if pick is not None and st.button(
                    "Use saved note", key=_sk(response_id, "rn_use")
                ):
                    st.session_state[_sk(response_id, "pending_res_notes")] = notes_lib[
                        pick
                    ]["notes"]
                    if notes_lib[pick].get("confluence_url"):
                        st.session_state[_sk(response_id, "pending_conf_url")] = (
                            notes_lib[pick]["confluence_url"]
                        )
                    st.toast("Note selected — fields update below")

            cq1, cq2 = st.columns([3, 1])
            cq = cq1.text_input(
                "Search Confluence",
                key=_sk(response_id, "conf_q"),
                label_visibility="collapsed",
                placeholder="Search Confluence…",
            )
            if cq2.button("Search", key=_sk(response_id, "conf_search")):
                q = (cq or "").strip()[:_MAX_QUERY_LEN]
                if not q:
                    st.toast("Enter a search term")
                else:
                    with st.spinner("Searching…"):
                        try:
                            from services.confluence_search import search_pages

                            st.session_state[_sk(response_id, "conf_hits")] = (
                                search_pages(user.id, q)
                            )
                        except Exception as exc:
                            st.error(_msg(exc))
            hits = st.session_state.get(_sk(response_id, "conf_hits")) or []
            if hits:
                pick = st.selectbox(
                    "Page",
                    range(len(hits)),
                    format_func=lambda i: _safe_text(hits[i]["title"], 60),
                    key=_sk(response_id, "conf_pick"),
                )
                if st.button("Use page", key=_sk(response_id, "conf_use")):
                    _u = _safe_conf_url(hits[pick]["url"])
                    if _u:
                        st.session_state[_sk(response_id, "pending_conf_url")] = _u
                        st.toast("URL selected")
                    else:
                        st.error("Page URL is not http(s).")
            use_ai_notes = st.checkbox(
                "Polish with AI (slower)",
                value=False,
                key=_sk(response_id, "conf_ai"),
                help="Off = fast template from Confluence page. On = Ollama rewrite.",
            )
            if st.button("Draft notes", key=_sk(response_id, "conf_draft")):
                conf_to_use = st.session_state.get(conf_key) or conf_url or ""
                safe_conf = _safe_conf_url(conf_to_use) or ""
                with st.spinner(
                    "Drafting with AI…" if use_ai_notes else "Fetching Confluence…"
                ):
                    try:
                        from services.resolution_notes_service import (
                            draft_resolution_notes,
                        )

                        notes = draft_resolution_notes(
                            user_id=user.id,
                            confluence_url=safe_conf,
                            ticket_key=issue["key"],
                            ticket_summary=issue.get("summary") or "",
                            extra_context="",
                            use_ai=bool(use_ai_notes),
                        )
                        st.session_state[_sk(response_id, "pending_res_notes")] = (
                            notes or ""
                        )
                        st.toast("Notes ready")
                    except Exception as exc:
                        st.error(_msg(exc))

            if notes_key not in st.session_state:
                st.session_state[notes_key] = ""
            resolution_notes = st.text_area(
                "Resolution notes", height=80, key=notes_key
            )
            if resolution_notes.strip() and st.button(
                "Save note to library", key=_sk(response_id, "rn_save")
            ):
                try:
                    from services.resolution_notes_library import save_note

                    save_note(
                        project_id=project_id,
                        title=f"{issue['key']} note",
                        notes=resolution_notes,
                        confluence_url=_safe_conf_url(
                            st.session_state.get(conf_key) or ""
                        )
                        or "",
                        user_id=user.id,
                    )
                    st.toast("Saved to resolution library")
                except Exception as exp:
                    st.error(_msg(exp))

    # ---------------- template fields + preview ----------------
    from services.template_fields import apply_bracket_fields, extract_bracket_fields

    body_template = (
        st.session_state.get(_sk(response_id, "body_override")) or response_body
    )
    bracket_labels = extract_bracket_fields(body_template)
    field_values: dict[str, str] = {}
    if bracket_labels:
        st.markdown(
            '<div class="jsl-jd-label">Template fields</div>', unsafe_allow_html=True
        )
        st.caption(
            "Fill each field used in the library template. Required before posting."
        )
        # Never use ``with st:`` — the streamlit module is not a context manager.
        # Only DeltaGenerator columns from st.columns() support the with-protocol.
        if len(bracket_labels) == 1:
            label = bracket_labels[0]
            key = _sk(response_id, "tf_" + label.lower().replace(" ", "_")[:40])
            field_values[label] = st.text_input(
                label,
                key=key,
                placeholder=f"Value for [{label}]",
            )
        else:
            cols = st.columns(2)
            for i, label in enumerate(bracket_labels):
                key = _sk(response_id, "tf_" + label.lower().replace(" ", "_")[:40])
                with cols[i % 2]:
                    field_values[label] = st.text_input(
                        label,
                        key=key,
                        placeholder=f"Value for [{label}]",
                    )

    reporter = issue.get("reporter") or "Customer"
    preview = build_comment_preview(
        body_template,
        reporter_name=reporter,
        mention_mode=mention_mode,
        mention_username=mention_user or issue.get("reporter_username") or "",
        resolution_notes=resolution_notes if is_closing else "",
    )
    try:
        from services.workspace_service import designation_overrides
        from utils.personalization import personalize

        overrides = designation_overrides(user.id)
        pid = int(project_id) if project_id is not None else None
        preview = personalize(
            preview,
            user,
            pid,
            designation_overrides=overrides,
            recipient=reporter,
            context={
                "TICKET": issue.get("key") or "",
                "SUMMARY": issue.get("summary") or "",
                "ASSIGNEE": issue.get("assignee") or issue.get("assignee_name") or "",
                "PROJECT": issue.get("project_key")
                or (issue.get("key") or "").split("-")[0],
                "STATUS": issue.get("status") or "",
            },
        )
    except Exception:
        log_ignored(__name__)

    filled = {k: v for k, v in field_values.items() if (v or "").strip()}
    if filled:
        preview = apply_bracket_fields(preview, filled, leave_missing=True)

    _ml = st.session_state.get(_sk(response_id, "mention_line")) or ""
    if _ml:
        preview = (preview or "").rstrip() + "\n\n" + _ml
    try:
        from services.mention_utils import extract_at_usernames, to_jira_wiki_mentions

        preview = to_jira_wiki_mentions(preview or "")
        st.session_state[_sk(response_id, "auto_watch_from_body")] = (
            extract_at_usernames(
                (
                    st.session_state.get(_sk(response_id, "body_override"))
                    or response_body
                    or ""
                )
                + " "
                + (st.session_state.get(_sk(response_id, "mention_line")) or "")
                + " "
                + (st.session_state.get(_sk(response_id, "extra_mentions")) or "")
            )
        )
    except Exception:
        log_ignored(__name__)

    post_comment = st.checkbox(
        "Post comment",
        value=True,
        key=_sk(response_id, "post_comment"),
        help="Turn this off to submit only a work log, transition, attachment or watcher update.",
    )
    st.markdown(
        '<div class="jsl-jd-label">Comment preview</div>', unsafe_allow_html=True
    )
    st.code(preview or "", language=None, wrap_lines=True)
    st.caption(
        "Comment will not be sent; selected Jira actions will run independently."
        if not post_comment
        else "Tokens: @TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS @R · fill [custom fields] above"
    )

    # ---------------- safety: plan + placeholders ----------------
    st.markdown(
        '<div class="jsl-jd-label">Before you post</div>', unsafe_allow_html=True
    )
    files_n = len(uploads) if uploads else 0
    _tlabels = [lab for _, lab in transition_chain]
    plan = action_plan_lines(
        issue_key=issue["key"],
        internal=internal,
        time_raw=time_raw or "",
        transition_labels=_tlabels,
        files_n=files_n,
        closing=bool(is_closing),
        include_comment=bool(post_comment and (preview or "").strip()),
    )
    for line in plan:
        st.caption("• " + _safe_text(line))

    leftover = (
        [
            t
            for t in unresolved_placeholders(preview or "")
            if not str(t).startswith("[~")
        ]
        if post_comment
        else []
    )
    for m in re.finditer(r"\[([^\]\n]{1,40})\]", preview or "") if post_comment else []:
        if m.group(1).startswith("~"):
            continue
        if m.group(0) not in leftover:
            leftover.append(m.group(0))
    if leftover:
        st.warning(
            "Unresolved placeholders: "
            + ", ".join(_safe_text(x, 40) for x in leftover[:8])
            + ". Fill template fields or remove them before posting."
        )

    # ---------------- post (sticky footer) ----------------
    steps_key = _sk(response_id, "steps_done")
    watchers_for_post = _collect_watch_ids(response_id, issue)
    paste_value = st.session_state.get(_sk(response_id, "clipboard_bridge")) or ""
    file_fingerprints = []
    for uploaded in uploads or []:
        try:
            file_fingerprints.append(
                (
                    _safe_filename(uploaded.name),
                    hashlib.sha256(uploaded.getvalue()).hexdigest(),
                )
            )
        except Exception:
            # The upload validation path will report unreadable files on submit.
            file_fingerprints.append(
                (_safe_filename(getattr(uploaded, "name", "file")), "unreadable")
            )
    if paste_value:
        file_fingerprints.append(
            ("clipboard-paste", hashlib.sha256(paste_value.encode("utf-8")).hexdigest())
        )
    fingerprint = execution_fingerprint(
        issue_key=issue["key"],
        comment=preview or "",
        include_comment=bool(post_comment),
        internal=internal,
        watchers=watchers_for_post,
        file_fingerprints=file_fingerprints,
        time_raw=time_raw or "",
        chain=transition_chain,
    )
    fingerprint_key = _sk(response_id, "execution_fingerprint")
    previous_fingerprint = st.session_state.get(fingerprint_key)
    if previous_fingerprint != fingerprint:
        # A changed payload (or legacy state created before fingerprints existed)
        # is a new execution, not a retry of the previous one.
        if previous_fingerprint is not None or st.session_state.get(steps_key):
            st.session_state[steps_key] = set()
            st.session_state[idem_key] = uuid.uuid4().hex
            st.session_state.pop(posted_key, None)
    st.session_state[fingerprint_key] = fingerprint
    done: set = st.session_state.setdefault(steps_key, set())
    has_file_action = bool(uploads) or bool(paste_value.strip())
    has_selected_action = bool(
        (post_comment and (preview or "").strip())
        or (time_raw or "").strip()
        or transition_chain
        or watchers_for_post
        or has_file_action
    )
    with st.container(key=_sk(response_id, "footer")):
        if st.session_state.get(posted_key):
            msg = st.session_state[posted_key]
            st.success(
                msg if isinstance(msg, str) else "Already posted in this dialog."
            )
            if st.button(
                "Post another update",
                key=_sk(response_id, "post_again"),
                width="stretch",
            ):
                # no st.rerun(): inside a dialog it would close the dialog
                st.session_state.pop(posted_key, None)
                st.session_state[steps_key] = done = set()
                st.session_state[idem_key] = uuid.uuid4().hex
            else:
                return

        can_post = not leftover and has_selected_action and not chain_problem
        label = "Retry failed steps" if done else "Post to Jira"
        if st.button(
            label,
            type="primary",
            key=_sk(response_id, "post"),
            disabled=not can_post,
            width="stretch",
            help=(
                "Fill or remove comment placeholders"
                if leftover
                else "The chain cannot start from this ticket's current status"
                if chain_problem
                else "Select at least one Jira action"
                if not has_selected_action
                else "Run the selected actions"
            ),
        ):
            key = issue["key"]
            files, problems = _prepare_files(
                uploads,
                st.session_state.get(_sk(response_id, "clipboard_bridge")) or "",
                key,
            )
            with st.spinner("Posting…"):
                out = run_post_steps(
                    user.id,
                    key,
                    comment=(preview or "") if post_comment else "",
                    internal=internal,
                    idempotency_key=st.session_state[idem_key],
                    done=done,
                    watchers=watchers_for_post,
                    files=files,
                    time_raw=time_raw,
                    chain=transition_chain,
                    jira_project_key=issue.get("project_key"),
                )
            st.session_state[steps_key] = done
            if any(n.startswith("file:paste_") for n in done):
                st.session_state[_sk(response_id, "pending_clear_clip")] = True
            errors = problems + out.errors
            if out.results:
                st.success(
                    f"**Posted to {_safe_text(key)}**\n\n"
                    + "\n".join(f"- {_safe_text(r)}" for r in out.results)
                )
            for e in errors:
                st.error(_safe_text("✖ " + e))
            if errors and done:
                st.caption(
                    "Steps that finished are kept. Click the button again to retry only what failed."
                )
            if out.results and not errors:
                st.session_state[posted_key] = (
                    f"Posted to {_safe_text(key)} ({len(out.results)} action(s))."
                )


def _prepare_files(
    uploads, paste_val: str, key: str
) -> tuple[list[tuple[str, bytes, str | None]], list[str]]:
    """Validate uploaded files and an optional pasted screenshot. Returns (files, problems)."""
    files: list[tuple[str, bytes, str | None]] = []
    problems: list[str] = []
    for f in uploads or []:
        name = _safe_filename(f.name)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        mime = getattr(f, "type", None) or ""
        data = f.getvalue()
        if ext not in _EXT_WHITELIST:
            problems.append(f"File {name}: unsupported extension")
        elif mime and mime not in _MIME_WHITELIST:
            problems.append(f"File {name}: unsupported type {mime}")
        elif len(data) > _MAX_ATTACH_BYTES:
            problems.append(f"File {name}: larger than {JIRA_MAX_ATTACHMENT_MB} MB")
        else:
            files.append((name, data, mime or None))
    if isinstance(paste_val, str) and paste_val.startswith("data:image"):
        try:
            if not _DATA_URL_RE.match(paste_val):
                raise ValueError("Only PNG/JPEG/GIF/WEBP data-URLs are accepted")
            header, b64data = paste_val.split(",", 1)
            ext = (
                "jpg"
                if ("jpeg" in header or "jpg" in header)
                else header.split("/")[1].split(";")[0]
            )
            raw = base64.b64decode(b64data, validate=True)
            if len(raw) > _MAX_PASTE_BYTES:
                raise ValueError("Pasted image is larger than 8 MB")
            files.append((_safe_filename(f"paste_{key}.{ext}"), raw, f"image/{ext}"))
        except ValueError as exc:
            problems.append(f"Paste: {exc}")
    return files, problems
