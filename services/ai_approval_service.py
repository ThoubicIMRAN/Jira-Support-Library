"""Queue / approve AI responses into the library."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from auth import allowed
from database import SessionLocal, Response, Category, AuditLog, User

MAX_BODY = 20000


class ApprovalError(ValueError):
    """Authorisation / validation failure that is safe to show to the user."""


def _require(user_id: int, permission: str) -> None:
    """Check the caller's role from the database (never trust the UI)."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active or not allowed(user.role, permission):
            raise ApprovalError("You do not have permission to do that.")


def submit_pending(
    *,
    user_id: int,
    project_id: int,
    category_id: int | None,
    title: str,
    body: str,
    ticket_excerpt: str | None = None,
) -> int:
    from database import AiPendingResponse

    _require(user_id, "use_ai")
    if not (body or "").strip() or len(body) > MAX_BODY:
        raise ApprovalError("Response text is empty or too long.")
    with SessionLocal() as db:
        row = AiPendingResponse(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            title=(title or "AI generated response")[:200],
            body=body,
            ticket_excerpt=(ticket_excerpt or "")[:2000] or None,
            status="pending",
        )
        db.add(row)
        db.add(
            AuditLog(
                user_id=user_id,
                action="ai_submit_approval",
                entity_type="ai_pending",
                entity_id="pending",
                details=(title or "")[:120],
            )
        )
        db.commit()
        db.refresh(row)
        return row.id


def list_pending(project_id: int | None = None) -> list[dict]:
    from database import AiPendingResponse, User, Project

    with SessionLocal() as db:
        stmt = (
            select(AiPendingResponse, User.username, Project.name)
            .join(User, User.id == AiPendingResponse.user_id)
            .join(Project, Project.id == AiPendingResponse.project_id)
            .where(AiPendingResponse.status == "pending")
            .order_by(AiPendingResponse.created_at.desc())
        )
        if project_id:
            stmt = stmt.where(AiPendingResponse.project_id == project_id)
        rows = db.execute(stmt).all()
        out = []
        for row, username, project_name in rows:
            out.append(
                {
                    "id": row.id,
                    "username": username,
                    "project_name": project_name,
                    "project_id": row.project_id,
                    "category_id": row.category_id,
                    "title": row.title,
                    "body": row.body,
                    "ticket_excerpt": row.ticket_excerpt,
                    "created_at": row.created_at,
                }
            )
        return out


def approve_pending(pending_id: int, reviewer_id: int, category_id: int | None = None) -> str | None:
    """Save into library; returns new response id."""
    from database import AiPendingResponse

    _require(reviewer_id, "approve_content")

    with SessionLocal() as db:
        row = db.get(AiPendingResponse, pending_id)
        if not row or row.status != "pending":
            return None
        cat_id = category_id or row.category_id
        if not cat_id:
            # pick first category in project
            cat = db.scalar(
                select(Category)
                .where(Category.project_id == row.project_id)
                .order_by(Category.sort_order, Category.id)
            )
            cat_id = cat.id if cat else None
        if not cat_id:
            raise ValueError("No category available to save this response.")

        resp_id = str(uuid.uuid4())
        db.add(
            Response(
                id=resp_id,
                category_id=cat_id,
                title=row.title,
                response_body=row.body,
                preview=(row.body or "")[:160],
            )
        )
        row.status = "approved"
        row.reviewer_id = reviewer_id
        row.reviewed_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                user_id=reviewer_id,
                action="ai_approve",
                entity_type="response",
                entity_id=resp_id,
                details=f"pending:{pending_id}",
            )
        )
        db.commit()
        return resp_id


def reject_pending(pending_id: int, reviewer_id: int, note: str = "") -> bool:
    from database import AiPendingResponse

    _require(reviewer_id, "approve_content")

    with SessionLocal() as db:
        row = db.get(AiPendingResponse, pending_id)
        if not row or row.status != "pending":
            return False
        row.status = "rejected"
        row.reviewer_id = reviewer_id
        row.review_note = (note or "")[:500] or None
        row.reviewed_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                user_id=reviewer_id,
                action="ai_reject",
                entity_type="ai_pending",
                entity_id=str(pending_id),
                details=note[:120] if note else None,
            )
        )
        db.commit()
        return True
