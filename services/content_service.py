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


def create_response(user_id, role, category_id, title, badge, preview, body):
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
        raise


def update_response(user_id, role, response_id, category_id, title, badge, preview, body):
    _require(role, "edit")
    title, badge, preview, body = _clean_fields(title, badge, preview, body)
    try:
        with SessionLocal() as db:
            row = db.get(Response, response_id)
            if not row:
                raise ContentError("Response not found.")
            _check_project(user_id, role, db.get(Category, row.category_id).project_id)
            target = db.get(Category, category_id)
            if not target:
                raise ContentError("Category not found.")
            _check_project(user_id, role, target.project_id)
            row.category_id, row.title, row.badge, row.preview, row.response_body = category_id, title, badge, preview, body
            audit(db, user_id, "update", "response", response_id, {"title": title})
            db.commit()
    except ContentError:
        raise
    except Exception:
        logger.exception("update_response failed")
        raise


def delete_response(user_id, role, response_id):
    _require(role, "delete")
    try:
        with SessionLocal() as db:
            row = db.get(Response, response_id)
            if not row:
                raise ContentError("Response not found.")
            _check_project(user_id, role, db.get(Category, row.category_id).project_id)
            audit(db, user_id, "delete", "response", response_id, {"title": row.title})
            db.delete(row)
            db.commit()
    except ContentError:
        raise
    except Exception:
        logger.exception("delete_response failed")
        raise


def duplicate_response(response_id, user_id, role="superadmin"):
    _require(role, "duplicate")
    with SessionLocal() as db:
        source = db.get(Response, response_id)
        if not source:
            return False
        _check_project(user_id, role, db.get(Category, source.category_id).project_id)
        max_order = db.scalar(select(func.max(Response.sort_order)).where(Response.category_id == source.category_id)) or 0
        clone = Response(id=_new_id(), category_id=source.category_id,
                         title=f'{source.title} (Copy)', badge=source.badge, preview=source.preview,
                         response_body=source.response_body, sort_order=max_order + 1)
        db.add(clone)
        audit(db, user_id, 'duplicate', 'response', clone.id, {'source_id': response_id})
        db.commit()
        return True


def export_project_payload(project_id):
    """Serialise one project. The result round-trips through import_project_payload."""
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if not p:
            return None
        return {
            "schema_version": 1,
            "project": {"key": p.key, "name": p.name, "description": p.description, "icon": p.icon, "color": p.color},
            "categories": [
                {"name": c.name, "sort_order": c.sort_order, "responses": [
                    {"id": r.id, "title": r.title, "badge": r.badge, "preview": r.preview,
                     "response_body": r.response_body, "sort_order": r.sort_order}
                    for r in c.responses
                ]} for c in p.categories
            ],
        }


def _normalise_payload(payload):
    """Accept schema v1 ({categories:[...]}) and the legacy {data:{name:[...]}} export."""
    if not isinstance(payload, dict):
        raise ContentError("Unsupported JSON structure.")
    if isinstance(payload.get("categories"), list):
        return payload["categories"]
    legacy = payload.get("data")
    if isinstance(legacy, dict):
        return [{"name": name, "responses": items} for name, items in legacy.items()]
    raise ContentError("Unsupported JSON structure.")


def import_project_payload(project_id, payload, user_id, role="superadmin"):
    _require(role, "import")
    _check_project(user_id, role, project_id)
    categories = _normalise_payload(payload)
    if sum(len(c.get("responses", []) or []) for c in categories if isinstance(c, dict)) > MAX_IMPORT_RESPONSES:
        raise ContentError(f"Import is limited to {MAX_IMPORT_RESPONSES} responses.")
    try:
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            if not project:
                raise ContentError("Project not found.")
            existing_ids = set(db.scalars(select(Response.id)).all())
            next_cat = len(project.categories)
            added = 0
            for ci, category_data in enumerate(categories):
                if not isinstance(category_data, dict):
                    raise ContentError(f"Category {ci + 1} is malformed.")
                name = str(category_data.get("name", "")).strip()
                if not name:
                    raise ContentError(f"Category {ci + 1} has no name.")
                category = db.scalar(select(Category).where(Category.project_id == project_id, Category.name == name))
                if not category:
                    category = Category(project_id=project_id, name=name[:180], sort_order=next_cat)
                    next_cat += 1
                    db.add(category)
                    db.flush()
                responses = category_data.get("responses", [])
                if not isinstance(responses, list):
                    raise ContentError(f"Responses in {name} must be a list.")
                base = (db.scalar(select(func.max(Response.sort_order)).where(Response.category_id == category.id)) or 0)
                for ri, record in enumerate(responses):
                    if not isinstance(record, dict):
                        raise ContentError(f"Invalid response at {name} row {ri + 1}.")
                    try:
                        title, badge, preview, body = _clean_fields(
                            record.get("title"), record.get("badge"), record.get("preview"),
                            record.get("response_body", record.get("response")))
                    except ContentError:
                        raise ContentError(f"Invalid response at {name} row {ri + 1}.")
                    proposed = str(record.get("id", "")).strip()
                    rid = proposed if proposed and len(proposed) <= 80 and proposed not in existing_ids else _new_id()
                    existing_ids.add(rid)
                    db.add(Response(id=rid, category_id=category.id, title=title, badge=badge,
                                    preview=preview, response_body=body, sort_order=base + ri + 1))
                    added += 1
            audit(db, user_id, "import", "project", project_id, {"responses_added": added})
            db.commit()
            return added
    except ContentError:
        raise
    except Exception:
        logger.exception("import_project_payload failed")
        raise



def list_category_tree(project_id: int) -> list[dict]:
    """Return [{id, name, parent_id, children:[{id,name,...}]}] top-level only with children."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Category)
            .where(Category.project_id == project_id)
            .order_by(Category.sort_order, Category.id)
        ).all()
    by_parent: dict[int | None, list] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)
    def node(c):
        return {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "children": [node(ch) for ch in by_parent.get(c.id, [])],
        }
    return [node(c) for c in by_parent.get(None, [])]


def create_category(user_id, role, project_id, name, parent_id=None):
    name = (name or "").strip()
    if not name:
        raise ContentError("Category name is required.")
    with SessionLocal() as db:
        _check_project(user_id, role, project_id)
        if parent_id:
            parent = db.get(Category, parent_id)
            if not parent or parent.project_id != project_id:
                raise ContentError("Parent category not found.")
            if parent.parent_id is not None:
                raise ContentError("Only one level of sub-categories is supported.")
        order = (
            db.scalar(
                select(func.max(Category.sort_order)).where(
                    Category.project_id == project_id,
                    Category.parent_id == parent_id if parent_id else Category.parent_id.is_(None),
                )
            )
            or 0
        ) + 1
        row = Category(project_id=project_id, name=name, parent_id=parent_id, sort_order=order)
        db.add(row)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise ContentError("Category already exists or could not be saved.")
        audit(db, user_id, "create", "category", row.id, {"name": name, "parent_id": parent_id})
        return row.id
