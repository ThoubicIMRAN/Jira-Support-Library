"""Thumbs up/down feedback on library suggestions shown in the Jira dialog."""
from __future__ import annotations

import logging
from typing import Literal

from database import SessionLocal
from services.audit_service import write_audit

logger = logging.getLogger(__name__)

Vote = Literal["up", "down"]


def record_vote(
    user_id: int,
    response_id: str,
    issue_key: str,
    vote: Vote,
) -> None:
    """Persist a suggestion ranking vote for later ranking boosts."""
    if vote not in ("up", "down"):
        raise ValueError("vote must be 'up' or 'down'")
    try:
        write_audit(
            user_id=user_id,
            action=f"suggestion_{vote}",
            entity_type="response",
            entity_id=str(response_id),
            details=f"issue={issue_key}",
        )
    except TypeError:
        # Older write_audit signatures
        try:
            with SessionLocal() as db:
                from database import AuditLog

                db.add(
                    AuditLog(
                        user_id=user_id,
                        action=f"suggestion_{vote}",
                        entity_type="response",
                        entity_id=str(response_id),
                        details=f"issue={issue_key}",
                    )
                )
                db.commit()
        except Exception:
            logger.exception(
                "Could not store suggestion vote user=%s response=%s vote=%s",
                user_id,
                response_id,
                vote,
            )
            raise
    logger.info(
        "suggestion vote user=%s response=%s issue=%s vote=%s",
        user_id,
        response_id,
        issue_key,
        vote,
    )
