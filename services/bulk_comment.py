"""Bulk Jira comment engine — the single implementation used by the UI.

Safety rails: all keys must belong to one Jira project, a hard cap per run
(BULK_MAX_TICKETS), a pause between posts (BULK_DELAY_SECONDS), abort on
authentication failure, no raw exception text for unexpected errors, and a
database log row for every run (see ``list_bulk_logs``).
"""
from __future__ import annotations

import json
import logging
import re
import time

from sqlalchemy import select

from config import BULK_DELAY_SECONDS, BULK_MAX_TICKETS
from database import AuditLog, BulkPostLog, SessionLocal, User
from services import jira_service
from services.jira_client import JiraError
from utils.personalization import personalize

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")
_CONTEXT_RE = re.compile(r"@(R|SUMMARY|ASSIGNEE|STATUS)\b", re.I)


class BulkError(ValueError):
    """Validation failure that is safe to show to the user."""


def project_prefix(key: str) -> str:
    return key.split("-")[0].upper()


def parse_keys(raw: str) -> list[str]:
    """Extract unique ticket keys (plain keys or browse URLs), keeping order."""
    seen: dict[str, None] = {}
    for key in _KEY_RE.findall((raw or "").upper()):
        seen.setdefault(key, None)
    return list(seen)


def validate_same_project(keys: list[str], required_prefix: str = "") -> tuple[str, list[str]]:
    if not keys:
        raise BulkError("Enter at least one ticket key.")
    required = (required_prefix or "").strip().upper() or project_prefix(keys[0])
    bad = [k for k in keys if project_prefix(k) != required]
    if bad:
        raise BulkError(f"All tickets must be in project {required}. Not allowed: {', '.join(bad[:5])}")
    return required, keys


def _write_log(user_id, prefix, keys, ok, failed, body):
    with SessionLocal() as db:
        row = BulkPostLog(
            user_id=user_id, jira_prefix=prefix, total=len(keys), ok_count=len(ok), failed_count=len(failed),
            ok_keys=",".join(ok), failed_json=json.dumps(failed, ensure_ascii=False),
            body_preview=(body or "").strip().replace("\n", " ")[:300],
        )
        db.add(row)
        db.add(AuditLog(user_id=user_id, action="jira_bulk_comment", entity_type="jira_project",
                        entity_id=prefix, details=f"{len(ok)}/{len(keys)} posted"))
        db.commit()
        return row.id


def post_bulk_comment(user_id: int, keys: list[str], body: str, required_prefix: str = "", *,
                      time_raw: str = "", internal: bool = False,
                      mention_mode: str = "plain",
                      resolution_notes: str = "",
                      max_tickets: int | None = None, delay: float | None = None) -> dict:
    """Post one comment to many tickets. Returns {prefix, ok, failed[(key, msg)], log_id}.

    ``body`` must be the **template** (with @R / @NAME / Customer), not a preview
    already filled for a single ticket. Each key is loaded so reporter and ticket
    tokens are applied per issue.
    """
    from services.jira_text import build_comment_preview

    limit = BULK_MAX_TICKETS if max_tickets is None else max_tickets
    pause = BULK_DELAY_SECONDS if delay is None else delay
    if not (body or "").strip():
        raise BulkError("Comment text is empty.")
    prefix, keys = validate_same_project(keys, required_prefix)
    if len(keys) > limit:
        raise BulkError(f"Bulk posting is limited to {limit} tickets at a time (you entered {len(keys)}).")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == user_id))
    ok: list[str] = []
    failed: list[list[str]] = []

    for index, key in enumerate(keys):
        try:
            issue = jira_service.load_issue(user_id, key)
            recipient = (issue.get("reporter") or "Customer").strip() or "Customer"
            mention_user = (issue.get("reporter_username") or "").strip()
            context = {
                "TICKET": key,
                "PROJECT": prefix,
                "SUMMARY": issue.get("summary") or "",
                "ASSIGNEE": issue.get("assignee") or issue.get("assignee_name") or "",
                "STATUS": issue.get("status") or "",
            }
            text = build_comment_preview(
                body,
                reporter_name=recipient,
                mention_mode=mention_mode or "plain",
                mention_username=mention_user,
                resolution_notes=resolution_notes or "",
            )
            text = personalize(text, user, None, recipient=recipient, context=context)
            jira_service.add_comment(user_id, key, text, internal=internal)
            if (time_raw or "").strip():
                jira_service.log_work(user_id, key, time_raw)
            ok.append(key)
        except (JiraError, ValueError) as exc:
            failed.append([key, str(exc)[:200]])
            if isinstance(exc, JiraError) and exc.status in (401, 403) and not ok:
                failed.extend([k, "skipped (authentication failed)"] for k in keys[index + 1:])
                break
        except Exception:  # noqa: BLE001
            logger.exception("Bulk comment failed for %s", key)
            failed.append([key, "unexpected error (see server log)"])
        if pause and index < len(keys) - 1:
            time.sleep(pause)

    log_id = _write_log(user_id, prefix, keys, ok, failed, body)
    return {"prefix": prefix, "ok": ok, "failed": failed, "log_id": log_id}



def list_bulk_logs(user_id: int | None = None, limit: int = 50) -> list[dict]:
    """Newest first. ``user_id=None`` returns every user's runs (admin view)."""
    with SessionLocal() as db:
        stmt = select(BulkPostLog, User.username).join(User, User.id == BulkPostLog.user_id, isouter=True)
        if user_id is not None:
            stmt = stmt.where(BulkPostLog.user_id == user_id)
        rows = db.execute(stmt.order_by(BulkPostLog.created_at.desc()).limit(limit)).all()
    out = []
    for row, username in rows:
        out.append({
            "id": row.id, "when": row.created_at, "user": username or "(deleted)", "prefix": row.jira_prefix,
            "total": row.total, "ok": row.ok_count, "failed": row.failed_count,
            "ok_keys": [k for k in row.ok_keys.split(",") if k], "failed_items": json.loads(row.failed_json or "[]"),
            "text": row.body_preview,
        })
    return out
