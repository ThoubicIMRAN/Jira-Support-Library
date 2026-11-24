"""Pure helpers for the Jira action dialog.

No Streamlit dependency. Validation, sanitisation, watcher collection, and
attachment preparation live here so they can be unit-tested and reused.
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

from config import JIRA_MAX_ATTACHMENT_MB
from services import jira_service
from services.jira_client import JiraError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / validation
# ---------------------------------------------------------------------------
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}-\d{1,8}$")
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
WIKI_USER_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,64}$")
CONF_URL_RE = re.compile(r"^https?://[^\s]+$")
DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,")
EXT_WHITELIST = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log"}
MIME_WHITELIST = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
}
MAX_PASTE_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_ATTACH_BYTES = JIRA_MAX_ATTACHMENT_MB * 1024 * 1024
MAX_QUERY_LEN = 200
MAX_EXTRA_USERS = 25


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------
def safe_text(value: object, limit: int = 400) -> str:
    """Make a user-influenced string safe for Markdown/error rendering."""
    s = str(value or "")
    s = s.replace("\x00", "")
    s = re.sub(r"[\[\]\(\)<>`]", "", s)
    s = re.sub(r"[\x01-\x08\x0b-\x1f]", "", s)
    return s[:limit]


def safe_wiki_user(raw: str) -> str | None:
    s = (raw or "").strip()
    return s if WIKI_USER_RE.match(s) else None


def safe_filename(name: str) -> str:
    base = (name or "file").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f]", "", base).strip() or "file"
    return base[:180]


def safe_conf_url(url: str) -> str | None:
    s = (url or "").strip()
    return s if CONF_URL_RE.match(s) else None


# ---------------------------------------------------------------------------
# Project / issue key guards
# ---------------------------------------------------------------------------
def linked_prefix(project: Any) -> str | None:
    """Return the Jira project key linked to a library project, or None."""
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


def assert_issue_allowed(issue_key: str, project: Any) -> None:
    """Raise JiraError if the issue key is not allowed for this library project."""
    required = linked_prefix(project)
    if not required:
        raise JiraError("Link this library project to a Jira key (Admin → Jira).")
    prefix = (issue_key or "").split("-", 1)[0].upper()
    if not PREFIX_RE.match(prefix):
        raise JiraError(f"Invalid issue key: `{safe_text(issue_key)}`")
    if prefix != required:
        raise JiraError(
            f"Only **{safe_text(required)}-*** tickets allowed. Got **{safe_text(issue_key)}**."
        )


# ---------------------------------------------------------------------------
# Watchers
# ---------------------------------------------------------------------------
def collect_watcher_ids(
    *,
    watch_assignee: bool,
    assignee_username: str | None,
    extra_as_watchers: bool,
    extra_mentions: str,
    auto_watch_from_body: list[str] | None,
) -> list[str]:
    """Build a de-duplicated, capped list of watcher identities."""
    ids: list[str] = []
    if watch_assignee:
        aid = safe_wiki_user(assignee_username or "")
        if aid:
            ids.append(aid)
    if extra_as_watchers:
        for part in re.split(r"[,;\s]+", extra_mentions or ""):
            u = safe_wiki_user(part.lstrip("@"))
            if u:
                ids.append(u)
        ids.extend(auto_watch_from_body or [])
    seen: set[str] = set()
    out: list[str] = []
    for u in ids:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out[:MAX_EXTRA_USERS]


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def prepare_attachment_files(
    uploads: Any,
    paste_val: str,
    issue_key: str,
) -> tuple[list[tuple[str, bytes, str | None]], list[str]]:
    """Validate uploaded files and an optional pasted screenshot.

    Returns ``(files, problems)`` where each file is ``(name, bytes, mime|None)``.
    """
    files: list[tuple[str, bytes, str | None]] = []
    problems: list[str] = []
    for f in uploads or []:
        name = safe_filename(f.name)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        mime = getattr(f, "type", None) or ""
        data = f.getvalue()
        if ext not in EXT_WHITELIST:
            problems.append(f"File {name}: unsupported extension")
        elif mime and mime not in MIME_WHITELIST:
            problems.append(f"File {name}: unsupported type {mime}")
        elif len(data) > MAX_ATTACH_BYTES:
            problems.append(f"File {name}: larger than {JIRA_MAX_ATTACHMENT_MB} MB")
        else:
            files.append((name, data, mime or None))
    if isinstance(paste_val, str) and paste_val.startswith("data:image"):
        try:
            if not DATA_URL_RE.match(paste_val):
                raise ValueError("Only PNG/JPEG/GIF/WEBP data-URLs are accepted")
            header, b64data = paste_val.split(",", 1)
            ext = (
                "jpg"
                if ("jpeg" in header or "jpg" in header)
                else header.split("/")[1].split(";")[0]
            )
            raw = base64.b64decode(b64data, validate=True)
            if len(raw) > MAX_PASTE_BYTES:
                raise ValueError("Pasted image is larger than 8 MB")
            files.append(
                (safe_filename(f"paste_{issue_key}.{ext}"), raw, f"image/{ext}")
            )
        except ValueError as exc:
            problems.append(f"Paste: {exc}")
    return files, problems
