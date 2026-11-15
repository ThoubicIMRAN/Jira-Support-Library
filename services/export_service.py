"""Export helpers (library / queue CSV)."""
from __future__ import annotations

import csv
import io
from typing import Iterable

from sqlalchemy import select

from database import Category, Project, Response, SessionLocal


def export_project_responses_csv(project_id: int) -> str:
    """Return CSV text for all responses in a project."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["project_key", "project_name", "category", "response_id", "title", "badge", "preview", "body"])
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project:
            return buf.getvalue()
        categories = db.scalars(
            select(Category).where(Category.project_id == project_id).order_by(Category.sort_order, Category.id)
        ).all()
        for cat in categories:
            responses = db.scalars(
                select(Response).where(Response.category_id == cat.id).order_by(Response.sort_order, Response.id)
            ).all()
            for r in responses:
                writer.writerow([
                    project.key or "",
                    project.name or "",
                    cat.name or "",
                    r.id,
                    r.title or "",
                    r.badge or "",
                    r.preview or "",
                    (r.response_body or "").replace("\r\n", "\n"),
                ])
    return buf.getvalue()


def export_rows_csv(headers: list[str], rows: Iterable[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()
