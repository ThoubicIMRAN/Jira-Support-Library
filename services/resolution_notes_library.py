"""Searchable library of approved resolution notes (with optional Confluence link)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)


class ResolutionNote(Base):
    __tablename__ = "resolution_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(240), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    confluence_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _ensure_table() -> None:
    try:
        ResolutionNote.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        logger.exception("Could not ensure resolution_notes table")


def list_notes(project_id: int | None) -> list[dict]:
    """Return notes for a library project (newest first)."""
    _ensure_table()
    with SessionLocal() as db:
        q = select(ResolutionNote).order_by(ResolutionNote.id.desc()).limit(100)
        if project_id is not None:
            q = q.where(ResolutionNote.project_id == int(project_id))
        rows = db.scalars(q).all()
        return [
            {
                "id": r.id,
                "title": r.title or f"Note #{r.id}",
                "notes": r.notes or "",
                "confluence_url": r.confluence_url or "",
            }
            for r in rows
        ]


def save_note(
    *,
    project_id: int | None,
    title: str,
    notes: str,
    confluence_url: str | None = None,
    user_id: int | None = None,
) -> int:
    """Save a resolution note; returns new id."""
    _ensure_table()
    body = (notes or "").strip()
    if not body:
        raise ValueError("Resolution notes cannot be empty")
    with SessionLocal() as db:
        row = ResolutionNote(
            project_id=int(project_id) if project_id is not None else None,
            title=(title or "Resolution note").strip()[:240],
            notes=body,
            confluence_url=(confluence_url or "").strip() or None,
            created_by=user_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("resolution note saved id=%s project=%s", row.id, project_id)
        return int(row.id)
