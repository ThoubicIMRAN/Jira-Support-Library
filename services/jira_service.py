"""High-level Jira operations for the Support Library app."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from config import JIRA_BASE_URL, JIRA_PRODUCT, JIRA_REQUEST_TIMEOUT, JIRA_ENABLED
from database import SessionLocal, AuditLog
from services.jira_client import JiraClient, JiraError
from utils.security import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)

ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
# browse/KEY or issues/KEY
URL_KEY_RE = re.compile(
    r"(?:browse|issues)/([A-Z][A-Z0-9]+-\d+)",
    re.IGNORECASE,
)

TIME_RE = re.compile(
    r"^\s*(?:(\d+(?:\.\d+)?)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:ins?|inutes?)?)?\s*$",
    re.IGNORECASE,
)


def parse_issue_key(raw: str) -> str | None:
    """Extract issue key from KEY-123 or a Jira URL."""
    text = (raw or "").strip()
    if not text:
        return None
    m = URL_KEY_RE.search(text)
    if m:
        return m.group(1).upper()
    m = ISSUE_KEY_RE.search(text.upper())
    return m.group(1) if m else None


def normalize_time_spent(raw: str) -> str:
    """Accept '1h 30m', '1.5h', '90m' → Jira timeSpent string."""
    text = (raw or "").strip().lower()
    if not text:
        raise ValueError("Time spent is required (e.g. 1h 30m).")
    # already looks like Jira format with both units mixed
    m = TIME_RE.match(text)
    if not m or (not m.group(1) and not m.group(2)):
        # try pure minutes number
        if text.isdigit():
            return f"{text}m"
        raise ValueError("Use format like 1h 30m, 2h, or 45m.")
    hours = m.group(1)
    mins = m.group(2)
    parts = []
    if hours:
        # if decimal hours, convert remainder to minutes
        h_val = float(hours)
        whole = int(h_val)
        frac = h_val - whole
        if whole:
            parts.append(f"{whole}h")
        if frac > 0:
            parts.append(f"{int(round(frac * 60))}m")
        elif not mins and whole == 0:
            parts.append("0h")
    if mins:
        parts.append(f"{int(mins)}m")
    if not parts:
        raise ValueError("Use format like 1h 30m, 2h, or 45m.")
    return " ".join(parts)


def _audit(user_id: int, action: str, issue_key: str, details: str = "") -> None:
    try:
        with SessionLocal() as db:
            db.add(
                AuditLog(
                    user_id=user_id,
                    action=action,
                    entity_type="jira_issue",
                    entity_id=issue_key,
                    details=details or None,
                )
            )
            db.commit()
    except Exception:
        logger.exception("Failed to write Jira audit log")


def _load_credential_row(user_id: int):
    from database import UserJiraCredential

    with SessionLocal() as db:
        row = db.scalar(
            select(UserJiraCredential).where(UserJiraCredential.user_id == user_id)
        )
        if row:
            db.expunge(row)
        return row


def get_client_for_user(user_id: int) -> JiraClient:
    if not JIRA_ENABLED:
        raise JiraError("Jira integration is disabled.")
    if not JIRA_BASE_URL:
        raise JiraError("JIRA_BASE_URL is not configured.")
    row = _load_credential_row(user_id)
    if not row or not row.encrypted_secret:
        raise JiraError("Connect your Jira account in Settings first.")
    secret = decrypt_secret(row.encrypted_secret)
    if not secret:
        raise JiraError("Stored Jira credentials could not be decrypted.")
    product = row.product or JIRA_PRODUCT
    return JiraClient(
        base_url=JIRA_BASE_URL,
        product=product,
        email=row.email,
        secret=secret,
        timeout=JIRA_REQUEST_TIMEOUT,
    )


def save_user_credentials(
    user_id: int,
    *,
    product: str,
    email: str | None,
    secret: str,
) -> dict[str, Any]:
    """Store encrypted credentials and verify with /myself."""
    from database import UserJiraCredential

    product = (product or JIRA_PRODUCT).lower()
    if product not in {"cloud", "server"}:
        product = "cloud"
    client = JiraClient(
        base_url=JIRA_BASE_URL,
        product=product,
        email=email,
        secret=secret.strip(),
        timeout=JIRA_REQUEST_TIMEOUT,
    )
    me = client.myself()
    display = me.get("displayName") or me.get("name") or email or "Jira user"

    with SessionLocal() as db:
        row = db.scalar(
            select(UserJiraCredential).where(UserJiraCredential.user_id == user_id)
        )
        if not row:
            row = UserJiraCredential(user_id=user_id)
            db.add(row)
        row.product = product
        row.email = (email or "").strip() or None
        row.encrypted_secret = encrypt_secret(secret.strip())
        row.display_name = display
        row.is_valid = True
        row.last_tested_at = datetime.now(timezone.utc)
        db.commit()
    _audit(user_id, "jira_connect", "-", f"Connected as {display}")
    return {"display_name": display, "account_id": me.get("accountId") or me.get("key")}


def disconnect_user(user_id: int) -> None:
    from database import UserJiraCredential

    with SessionLocal() as db:
        row = db.scalar(
            select(UserJiraCredential).where(UserJiraCredential.user_id == user_id)
        )
        if row:
            db.delete(row)
            db.commit()
    _audit(user_id, "jira_disconnect", "-", "")


def credential_status(user_id: int) -> dict[str, Any]:
    row = _load_credential_row(user_id)
    if not row:
        return {"connected": False}
    return {
        "connected": True,
        "product": row.product,
        "email": row.email,
        "display_name": row.display_name,
        "last_tested_at": row.last_tested_at,
        "is_valid": row.is_valid,
    }


def get_jira_project_key(app_project_id: int) -> str | None:
    from database import ProjectJiraLink, Project

    with SessionLocal() as db:
        link = db.scalar(
            select(ProjectJiraLink).where(ProjectJiraLink.project_id == app_project_id)
        )
        if link:
            return link.jira_project_key
        # fallback: use app project.key uppercased
        proj = db.get(Project, app_project_id)
        return (proj.key or "").upper() if proj else None


def set_jira_project_key(app_project_id: int, jira_key: str) -> None:
    from database import ProjectJiraLink

    jira_key = (jira_key or "").strip().upper()
    with SessionLocal() as db:
        link = db.scalar(
            select(ProjectJiraLink).where(ProjectJiraLink.project_id == app_project_id)
        )
        if not link:
            link = ProjectJiraLink(project_id=app_project_id, jira_project_key=jira_key)
            db.add(link)
        else:
            link.jira_project_key = jira_key
        db.commit()


def load_issue(user_id: int, raw_ticket: str) -> dict[str, Any]:
    key = parse_issue_key(raw_ticket)
    if not key:
        raise JiraError("Enter a ticket like PROJ-123 or paste a Jira issue URL.")
    client = get_client_for_user(user_id)
    fields = "summary,status,assignee,reporter,issuetype,project"
    data = client.get_issue(key, fields=fields)
    f = data.get("fields") or {}
    status = (f.get("status") or {}).get("name")
    assignee = f.get("assignee") or {}
    reporter = f.get("reporter") or {}
    reporter_name = (
        reporter.get("displayName")
        or reporter.get("name")
        or reporter.get("emailAddress")
        or "Customer"
    )
    reporter_username = (
        reporter.get("name")
        or reporter.get("accountId")
        or ""
    )
    return {
        "key": data.get("key") or key,
        "summary": f.get("summary") or "",
        "status": status or "",
        "assignee": assignee.get("displayName") or assignee.get("name") or "Unassigned",
        "assignee_username": assignee.get("name") or assignee.get("accountId") or "",
        "reporter": reporter_name,
        "reporter_username": reporter_username,
        "issuetype": (f.get("issuetype") or {}).get("name") or "",
        "project_key": (f.get("project") or {}).get("key") or key.split("-")[0],
        "raw": data,
    }


def add_comment(user_id: int, issue_key: str, body: str, *, internal: bool = False) -> None:
    body = (body or "").strip()
    if not body:
        raise JiraError("Comment body is empty.")
    client = get_client_for_user(user_id)
    try:
        client.add_comment(issue_key, body, internal=internal)
    except TypeError:
        client.add_comment(issue_key, body)
    _audit(user_id, "jira_comment", issue_key, ("[internal] " if internal else "") + body[:200])
    try:
        remember_last_comment(user_id, body)
    except Exception:
        pass



_ATTACH_MAGIC = {
    "png": (b"\x89PNG",), "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF8",), "webp": (b"RIFF",), "pdf": (b"%PDF",),
}
_ATTACH_TEXT = {"txt", "log"}


def validate_attachment(filename: str, content: bytes) -> str:
    """Allow-list extension, size and file signature. Returns a safe file name."""
    import os
    from config import JIRA_MAX_ATTACHMENT_MB

    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not name or ext not in set(_ATTACH_MAGIC) | _ATTACH_TEXT:
        raise ValueError("File type not allowed. Use png, jpg, gif, webp, pdf, txt or log.")
    if not content or len(content) > JIRA_MAX_ATTACHMENT_MB * 1024 * 1024:
        raise ValueError(f"File is empty or larger than {JIRA_MAX_ATTACHMENT_MB} MB.")
    if ext in _ATTACH_MAGIC and not content.startswith(_ATTACH_MAGIC[ext]):
        raise ValueError("File content does not match its extension.")
    if ext in _ATTACH_TEXT and b"\x00" in content[:2048]:
        raise ValueError("Text attachments must not contain binary data.")
    return name[:120]


def add_attachment(user_id: int, issue_key: str, filename: str, content: bytes, content_type: str | None = None) -> None:
    filename = validate_attachment(filename, content)
    client = get_client_for_user(user_id)
    client.add_attachment(issue_key, filename, content, content_type)
    _audit(user_id, "jira_attachment", issue_key, filename)


def log_work(
    user_id: int,
    issue_key: str,
    time_raw: str,
    *,
    comment: str | None = None,
) -> str:
    time_spent = normalize_time_spent(time_raw)
    client = get_client_for_user(user_id)
    client.add_worklog(issue_key, time_spent=time_spent, comment=comment or None)
    _audit(user_id, "jira_worklog", issue_key, time_spent)
    return time_spent


def list_transitions_friendly(
    user_id: int,
    issue_key: str,
    jira_project_key: str | None = None,
) -> list[dict[str, str]]:
    """Return [{id, name, label}] with friendly labels when aliased."""
    from database import JiraTransitionAlias

    client = get_client_for_user(user_id)
    transitions = client.list_transitions(issue_key)

    aliases: dict[str, str] = {}
    with SessionLocal() as db:
        rows = db.scalars(select(JiraTransitionAlias)).all()
        for r in rows:
            if r.jira_project_key in {"*", jira_project_key or ""}:
                aliases[r.raw_name.lower()] = r.friendly_label

    out = []
    for t in transitions:
        name = t.get("name") or str(t.get("id"))
        label = aliases.get(name.lower()) or name
        out.append({"id": str(t["id"]), "name": name, "label": label})
    return out


def transition_issue(user_id: int, issue_key: str, transition_id: str, label: str = "") -> None:
    client = get_client_for_user(user_id)
    client.do_transition(issue_key, transition_id)
    _audit(user_id, "jira_transition", issue_key, label or transition_id)


# --------------------------------------------------------------------------- #
# Admin: project links & transition aliases
# --------------------------------------------------------------------------- #
def list_project_links() -> list[dict]:
    from database import Project, ProjectJiraLink

    with SessionLocal() as db:
        projects = list(db.scalars(select(Project).where(Project.is_deleted.is_(False)).order_by(Project.sort_order, Project.name)).all())
        links = {r.project_id: r.jira_project_key for r in db.scalars(select(ProjectJiraLink)).all()}
        return [
            {
                "project_id": p.id,
                "name": p.name,
                "app_key": p.key,
                "jira_project_key": links.get(p.id) or (p.key or "").upper(),
                "linked": p.id in links,
            }
            for p in projects
        ]


def list_transition_aliases(jira_project_key: str | None = None) -> list[dict]:
    from database import JiraTransitionAlias

    with SessionLocal() as db:
        stmt = select(JiraTransitionAlias).order_by(JiraTransitionAlias.sort_order, JiraTransitionAlias.raw_name)
        if jira_project_key:
            stmt = stmt.where(
                (JiraTransitionAlias.jira_project_key == jira_project_key)
                | (JiraTransitionAlias.jira_project_key == "*")
            )
        rows = list(db.scalars(stmt).all())
        return [
            {
                "id": r.id,
                "jira_project_key": r.jira_project_key,
                "raw_name": r.raw_name,
                "friendly_label": r.friendly_label,
                "sort_order": r.sort_order,
            }
            for r in rows
        ]


def upsert_transition_alias(
    *,
    jira_project_key: str,
    raw_name: str,
    friendly_label: str,
    sort_order: int = 0,
    alias_id: int | None = None,
) -> None:
    from database import JiraTransitionAlias

    jira_project_key = (jira_project_key or "*").strip() or "*"
    raw_name = (raw_name or "").strip()
    friendly_label = (friendly_label or "").strip()
    if not raw_name or not friendly_label:
        raise ValueError("Raw transition name and friendly label are required.")
    with SessionLocal() as db:
        row = db.get(JiraTransitionAlias, alias_id) if alias_id else None
        if not row:
            row = JiraTransitionAlias(
                jira_project_key=jira_project_key,
                raw_name=raw_name,
                friendly_label=friendly_label,
                sort_order=sort_order,
            )
            db.add(row)
        else:
            row.jira_project_key = jira_project_key
            row.raw_name = raw_name
            row.friendly_label = friendly_label
            row.sort_order = sort_order
        db.commit()


def delete_transition_alias(alias_id: int) -> None:
    from database import JiraTransitionAlias

    with SessionLocal() as db:
        row = db.get(JiraTransitionAlias, alias_id)
        if row:
            db.delete(row)
            db.commit()


def remember_last_comment(user_id: int, body: str) -> None:
    """Store last posted comment text in session-friendly module cache via Streamlit session if available."""
    try:
        import streamlit as st
        st.session_state[f"jira_last_comment_{user_id}"] = body
    except Exception:
        pass


def get_last_comment(user_id: int) -> str:
    try:
        import streamlit as st
        return st.session_state.get(f"jira_last_comment_{user_id}") or ""
    except Exception:
        return ""


def find_similar_open_issues(user_id: int, issue: dict, *, limit: int = 5) -> list[dict]:
    """Duplicate / similar open tickets in the same project (simple text JQL)."""
    key = issue.get("key") or ""
    project_key = issue.get("project_key") or (key.split("-")[0] if key else "")
    summary = (issue.get("summary") or "").strip()
    if not project_key or not summary:
        return []
    # Use first few significant words for ~jql
    words = [w for w in summary.replace('"', " ").split() if len(w) > 3][:4]
    if not words:
        return []
    text_clause = " ".join(words)
    jql = (
        f'project = "{project_key}" AND resolution = Unresolved '
        f'AND key != "{key}" AND text ~ "{text_clause}" '
        f"ORDER BY updated DESC"
    )
    client = get_client_for_user(user_id)
    try:
        issues = client.search_issues(jql, max_results=limit)
    except JiraError:
        return []
    out = []
    for it in issues:
        f = it.get("fields") or {}
        out.append(
            {
                "key": it.get("key"),
                "summary": f.get("summary") or "",
                "status": ((f.get("status") or {}).get("name") or ""),
            }
        )
    return out


def suggest_library_for_issue(user_id: int, project_id: int, issue: dict) -> list[dict]:
    """Smart suggestions: semantic match library responses to ticket summary/description."""
    from services import ai_service

    text = f"{issue.get('summary') or ''}\n{issue.get('status') or ''}"
    if not text.strip():
        return []
    try:
        hit, score = ai_service.find_best_match(project_id, text, threshold=0.5)
    except Exception:
        return []
    if not hit:
        return []
    # Also try a slightly lower bar for top few — find_best_match returns one; expand later
    return [
        {
            "id": hit.id,
            "title": hit.title,
            "body": hit.response_body,
            "score": score,
        }
    ]



def add_watchers(user_id: int, issue_key: str, identities: list[str]) -> list[str]:
    """Add watchers by username (Server/DC) or accountId (Cloud). Returns list of errors."""
    client = get_client_for_user(user_id)
    errors: list[str] = []
    for ident in identities:
        ident = (ident or "").strip()
        if not ident:
            continue
        try:
            client.add_watcher(issue_key, ident)
            _audit(user_id, "jira_watcher", issue_key, ident)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ident}: {exc}")
    return errors


def search_jira_users(user_id: int, query: str) -> list[dict]:
    client = get_client_for_user(user_id)
    return client.search_users(query)


def multi_step_transition(
    user_id: int,
    issue_key: str,
    transition_ids: list[str],
    *,
    labels: list[str] | None = None,
) -> list[str]:
    """Run sequential Jira transitions; returns list of applied labels/ids.

    Each step uses the issue's current available transitions. If an id is no
    longer available mid-chain, raises JiraError after applying prior steps.
    """
    if not transition_ids:
        return []
    labels = labels or []
    applied: list[str] = []
    client = get_client_for_user(user_id)
    for i, tid in enumerate(transition_ids):
        tid = str(tid).strip()
        if not tid:
            continue
        available = {str(t.get("id")): t for t in client.list_transitions(issue_key)}
        if tid not in available:
            raise JiraError(
                f"Transition {tid} not available after step {i} "
                f"(applied so far: {', '.join(applied) or 'none'})."
            )
        client.do_transition(issue_key, tid)
        lab = labels[i] if i < len(labels) else (available[tid].get("name") or tid)
        applied.append(str(lab))
        _audit(user_id, "jira_transition", issue_key, f"step={i+1}:{lab}")
    return applied


MY_QUEUE_FIELDS = (
    "summary,status,issuetype,project,assignee,reporter,duedate,priority,updated,created"
)
MY_QUEUE_JQL = (
    "assignee = currentUser() AND resolution = Unresolved "
    "ORDER BY duedate ASC, updated DESC"
)


def fetch_my_queue(user_id: int, *, max_results: int = 100) -> list[dict]:
    """Open issues assigned to the connected Jira user (all projects)."""
    client = get_client_for_user(user_id)
    raw = client.search_issues(
        MY_QUEUE_JQL,
        max_results=max_results,
        fields=MY_QUEUE_FIELDS,
    )
    out: list[dict] = []
    for issue in raw or []:
        fields = issue.get("fields") or {}
        project = fields.get("project") or {}
        status = fields.get("status") or {}
        itype = fields.get("issuetype") or {}
        assignee = fields.get("assignee") or {}
        out.append({
            "key": issue.get("key") or "",
            "summary": fields.get("summary") or "",
            "status": status.get("name") or "",
            "issuetype": itype.get("name") or "Unknown",
            "project_key": project.get("key") or (issue.get("key") or "").split("-")[0],
            "project_name": project.get("name") or project.get("key") or "",
            "assignee": assignee.get("displayName") or assignee.get("name") or "",
            "duedate": fields.get("duedate") or None,
            "priority": (fields.get("priority") or {}).get("name") or "",
            "updated": fields.get("updated") or "",
        })
    return out


def aggregate_queue_dashboard(issues: list[dict]) -> dict:
    """Build project×status counts and due-date buckets for charts."""
    from collections import defaultdict
    from datetime import date, timedelta

    today = date.today()
    by_project_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    due_buckets = {"Overdue": 0, "Due today": 0, "Next 7 days": 0, "Later": 0, "No due date": 0}

    for it in issues:
        pk = it.get("project_key") or "?"
        st_name = it.get("status") or "Unknown"
        by_project_status[pk][st_name] += 1
        raw = it.get("duedate")
        if not raw:
            due_buckets["No due date"] += 1
            continue
        try:
            d = date.fromisoformat(str(raw)[:10])
        except ValueError:
            due_buckets["No due date"] += 1
            continue
        if d < today:
            due_buckets["Overdue"] += 1
        elif d == today:
            due_buckets["Due today"] += 1
        elif d <= today + timedelta(days=7):
            due_buckets["Next 7 days"] += 1
        else:
            due_buckets["Later"] += 1

    # Flatten for st.bar_chart: rows of {project, status, count}
    flat = []
    for proj, statuses in sorted(by_project_status.items()):
        for status, count in sorted(statuses.items()):
            flat.append({"project": proj, "status": status, "count": count})

    return {
        "by_project_status": {k: dict(v) for k, v in by_project_status.items()},
        "flat_project_status": flat,
        "due_buckets": due_buckets,
        "total": len(issues),
    }


def group_queue_by_project_type(issues: list[dict]) -> dict[str, dict[str, list]]:
    """project_key -> issuetype -> [issues]."""
    from collections import defaultdict
    tree: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for it in issues:
        tree[it.get("project_key") or "?"][it.get("issuetype") or "Unknown"].append(it)
    return {p: dict(types) for p, types in sorted(tree.items())}
