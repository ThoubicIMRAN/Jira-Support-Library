"""Helpers for password-reset → sign-in prefill."""
from __future__ import annotations

from sqlalchemy import select

from database import SessionLocal
from utils.security import token_hash


def username_for_reset_token(token: str) -> str:
    """Return username bound to an (already consumed or valid) reset token if possible."""
    from database import PasswordResetToken, User

    if not token:
        return ""
    th = token_hash(token)
    with SessionLocal() as db:
        row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == th))
        if not row:
            return ""
        user = db.get(User, row.user_id)
        return (user.username if user else "") or ""
