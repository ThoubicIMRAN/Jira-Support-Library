"""Content operations: response CRUD, ordering, JSON import/export.

Every mutating function enforces RBAC itself (never trusts the UI), runs in one
transaction, rolls back on failure and writes an audit record.
"""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import func, select

from auth import allowed
from database import AuditLog, Category, Project, Response, SessionLocal

logger = logging.getLogger(__name__)

MAX_TITLE = 200
MAX_BADGE = 40
MAX_PREVIEW = 300
MAX_BODY = 20000
MAX_IMPORT_RESPONSES = 2000


class ContentError(ValueError):
    """Validation / authorisation failure that is safe to show to the user."""


def _require(role: str, permission: str) -> None:
    if not allowed(role, permission):
        raise ContentError("You do not have permission to do that.")


def _check_project(user_id, role, project_id):
    from services.project_access import visible_project_ids
    ids = visible_project_ids(user_id, role)
    if ids is not None and int(project_id) not in ids:
        raise ContentError("You do not have access to this project.")


def _new_id() -> str:
    return "r_" + uuid.uuid4().hex[:16]


def _clean_fields(title, badge, preview, body):
    title, body = (title or "").strip(), (body or "").strip()
    badge, preview = (badge or "").strip(), (preview or "").strip()
    if not title or not body:
        raise ContentError("Title and response body are required.")
    if len(title) > MAX_TITLE or len(badge) > MAX_BADGE or len(preview) > MAX_PREVIEW or len(body) > MAX_BODY:
        raise ContentError("One of the fields is too long.")
    return title, badge or None, preview or None, body


def audit(db, user_id, action, entity_type, entity_id=None, details=None):
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    details=json.dumps(details or {}, ensure_ascii=False)))


def normalize_orders(db, model, parent_filter=None):
    """Re-number sort_order 0..n-1 so swaps are never no-ops on duplicates."""
    stmt = select(model).order_by(model.sort_order, model.id)
    if parent_filter is not None:
        stmt = stmt.where(parent_filter)
    rows = db.scalars(stmt).all()
    for index, row in enumerate(rows):
        row.sort_order = index
    return rows


def _move(db, rows, entity_id, direction):
    index = next((i for i, row in enumerate(rows) if row.id == entity_id), None)
    target = index + direction if index is not None else -1
    if index is None or target < 0 or target >= len(rows):
        return False
    rows[index].sort_order, rows[target].sort_order = rows[target].sort_order, rows[index].sort_order
    return True


def move_project(project_id, direction, user_id, role="superadmin"):
    _require(role, "manage_content")
    with SessionLocal() as db:
        rows = normalize_orders(db, Project, Project.is_deleted == False)  # noqa: E712
        if not _move(db, rows, project_id, direction):
            db.rollback()
            return False
        audit(db, user_id, "reorder", "project", project_id, {"direction": direction})
        db.commit()
        return True


def move_category(category_id, direction, user_id, role="superadmin"):
    _require(role, "manage_content")
    with SessionLocal() as db:
        current = db.get(Category, category_id)
        if not current:
            return False
        rows = normalize_orders(db, Category, Category.project_id == current.project_id)
        if not _move(db, rows, category_id, direction):
            db.rollback()
            return False
        audit(db, user_id, "reorder", "category", category_id, {"direction": direction})
        db.commit()
        return True


def find_near_duplicates(
    project_id: int,
    body: str,
    *,
    threshold: float = 0.85,
    limit: int = 3,
) -> list[dict]:
    """Semantic near-duplicates of body within a project (for save warnings)."""
    from services.similarity_search import find_near_duplicates as _fn
    return _fn(project_id, body, threshold=threshold, limit=limit)


def create_response(user_id, role, category_id, title, badge, preview, body):
    from services.rate_limit import limit_content_write
    limit_content_write(user_id)
    _require(role, "create")
    title, badge, preview, body = _clean_fields(title, badge, preview, body)
    try:
        with SessionLocal() as db:
            category = db.get(Category, category_id)
            if not category:
                raise ContentError("Category not found.")
            _check_project(user_id, role, category.project_id)
            order = (db.scalar(select(func.max(Response.sort_order)).where(Response.category_id == category_id)) or 0) + 1
            row = Response(id=_new_id(), category_id=category_id, title=title, badge=badge,
                           preview=preview, response_body=body, sort_order=order)
            db.add(row)
            audit(db, user_id, "create", "response", row.id, {"title": title})
            db.commit()
            return row.id
    except ContentError:
        raise
    except Exception:
        logger.exception("create_response failed")
        raise ContentError("Could not create the response.")
