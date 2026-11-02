"""Semantic top-N library matches (used by Jira suggestions + duplicate warnings)."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import AI_SIMILARITY_THRESHOLD
from database import Category, SessionLocal
from services import ai_service

logger = logging.getLogger(__name__)


def find_top_matches(
    project_id: int,
    query_text: str,
    *,
    limit: int = 5,
    threshold: float | None = None,
) -> list[dict]:
    """Return up to ``limit`` matches above threshold: {id, title, body, score}."""
    threshold = threshold if threshold is not None else AI_SIMILARITY_THRESHOLD
    if not (query_text or "").strip():
        return []
    try:
        query_vec = ai_service.embed(query_text)
    except Exception as exc:
        logger.warning("embed failed for top matches: %s", exc)
        return []

    scored: list[tuple[float, str, str, str]] = []
    with SessionLocal() as db:
        categories = db.scalars(
            select(Category)
            .options(selectinload(Category.responses))
            .where(Category.project_id == project_id)
        ).all()
        for cat in categories:
            for resp in cat.responses:
                try:
                    vec = ai_service.ensure_embedding(db, resp)
                    score = ai_service._cosine(query_vec, vec)
                    if score >= threshold:
                        scored.append((score, resp.id, resp.title, resp.response_body))
                except Exception as exc:
                    logger.warning("Embedding failed for %s: %s", resp.id, exc)

    scored.sort(key=lambda t: t[0], reverse=True)
    return [
        {"id": rid, "title": title, "body": body, "score": float(score)}
        for score, rid, title, body in scored[: max(1, int(limit))]
    ]


def find_near_duplicates(
    project_id: int,
    body: str,
    *,
    threshold: float = 0.85,
    limit: int = 3,
) -> list[dict]:
    return find_top_matches(project_id, body or "", limit=limit, threshold=threshold)
