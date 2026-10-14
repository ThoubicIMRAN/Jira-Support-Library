"""Announcements, maintenance, feature feedback + notify managers/admins."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from database import SessionLocal

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def active_maintenance() -> dict | None:
    from database import MaintenanceWindow

    with SessionLocal() as db:
        row = db.scalar(
            select(MaintenanceWindow)
            .where(MaintenanceWindow.is_active.is_(True))
            .order_by(MaintenanceWindow.id.desc())
        )
        if not row:
            return None
        return {"id": row.id, "title": row.title, "message": row.message}


def active_announcements(limit: int = 10) -> list[dict]:
    from database import Announcement

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(Announcement)
                .where(Announcement.is_active.is_(True))
                .order_by(Announcement.created_at.desc())
                .limit(limit)
            ).all()
        )
        return [
            {"id": r.id, "title": r.title, "body": r.body, "created_at": r.created_at}
            for r in rows
        ]


def set_maintenance(*, user_id: int, title: str, message: str, active: bool) -> None:
    from database import MaintenanceWindow

    with SessionLocal() as db:
        if active:
            for row in db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.is_active.is_(True))):
                row.is_active = False
        db.add(
            MaintenanceWindow(
                title=title.strip(),
                message=message.strip(),
                is_active=active,
                created_by=user_id,
                created_at=_utcnow(),
            )
        )
        db.commit()


def clear_maintenance() -> None:
    from database import MaintenanceWindow

    with SessionLocal() as db:
        for row in db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.is_active.is_(True))):
            row.is_active = False
        db.commit()


def add_announcement(*, user_id: int, title: str, body: str) -> None:
    from database import Announcement

    with SessionLocal() as db:
        db.add(
            Announcement(
                title=title.strip(),
                body=body.strip(),
                is_active=True,
                created_by=user_id,
                created_at=_utcnow(),
            )
        )
        db.commit()


def submit_feedback(
    *,
    user_id: int,
    title: str,
    body: str,
    category: str = "improvement",
    project_id: int | None = None,
) -> int:
    from database import FeatureFeedback, User

    with SessionLocal() as db:
        fb = FeatureFeedback(
            user_id=user_id,
            project_id=project_id,
            category=category or "improvement",
            title=title.strip()[:200],
            body=body.strip(),
            status="open",
            created_at=_utcnow(),
        )
        db.add(fb)
        db.flush()
        fid = fb.id
        recipients = list(
            db.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    User.role.in_(("superadmin", "admin", "manager")),
                )
            ).all()
        )
        submitter = db.get(User, user_id)
        db.commit()

    # Best-effort email notify (SMTP may be down)
    try:
        from email_service import branded_email, send_html_email

        name = getattr(submitter, "full_name", None) or f"user#{user_id}"
        html = branded_email(
            f"New {category}: {title.strip()[:80]}",
            f"<p><b>From:</b> {name}</p><pre>{body.strip()[:2000]}</pre>",
        )
        for u in recipients:
            if not getattr(u, "email", None) or u.id == user_id:
                continue
            try:
                send_html_email(u.email, f"[JSL] {category}: {title.strip()[:60]}", html)
            except Exception:
                logger.exception("feedback email to %s failed", u.email)
    except Exception:
        logger.exception("feedback notify skipped")

    return fid


def list_feedback(limit: int = 50) -> list[dict]:
    from database import FeatureFeedback, User

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(FeatureFeedback).order_by(FeatureFeedback.created_at.desc()).limit(limit)
            ).all()
        )
        out = []
        for r in rows:
            u = db.get(User, r.user_id)
            out.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "body": r.body,
                    "category": r.category,
                    "status": r.status,
                    "user": u.full_name if u else r.user_id,
                    "created_at": r.created_at,
                }
            )
        return out
