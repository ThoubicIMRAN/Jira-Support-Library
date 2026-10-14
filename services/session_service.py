import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from utils.timeutil import as_utc
from database import SessionLocal, AppSession
from utils.security import token_hash
from config import SESSION_TIMEOUT_MINUTES, SESSION_ABSOLUTE_HOURS

TOUCH_INTERVAL_SECONDS = 60


def utcnow():
    return datetime.now(timezone.utc)


def create_session(user_id, auth_method="local"):
    raw = secrets.token_urlsafe(40)
    now = utcnow()
    with SessionLocal() as db:
        db.add(
            AppSession(
                user_id=user_id,
                token_hash=token_hash(raw),
                auth_method=auth_method,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=SESSION_ABSOLUTE_HOURS),
            )
        )
        db.commit()
    return raw


def validate_session(raw):
    """Return user_id if the session is valid, else None.

    Idle timeout: SESSION_TIMEOUT_MINUTES == 0 means *no* idle timeout
    (only the absolute expires_at applies). Any positive value is minutes
    of inactivity after which the session is treated as expired.
    """
    if not raw:
        return None
    now = utcnow()
    with SessionLocal() as db:
        row = db.scalar(
            select(AppSession).where(AppSession.token_hash == token_hash(raw))
        )
        if not row or row.revoked_at:
            return None
        expires = as_utc(row.expires_at)
        if expires <= now:
            return None

        last_seen = as_utc(row.last_seen_at)

        # 0 = disable idle timeout; only absolute expiry applies
        if SESSION_TIMEOUT_MINUTES > 0:
            if last_seen + timedelta(minutes=SESSION_TIMEOUT_MINUTES) <= now:
                return None

        # Avoid a database write on every Streamlit widget rerun
        if (now - last_seen).total_seconds() >= TOUCH_INTERVAL_SECONDS:
            row.last_seen_at = now
            db.commit()
        return row.user_id


def revoke_session(raw):
    if not raw:
        return
    with SessionLocal() as db:
        row = db.scalar(
            select(AppSession).where(AppSession.token_hash == token_hash(raw))
        )
        if row:
            row.revoked_at = utcnow()
            db.commit()


def revoke_user_sessions(user_id, except_hash=None):
    with SessionLocal() as db:
        rows = db.scalars(
            select(AppSession).where(
                AppSession.user_id == user_id, AppSession.revoked_at.is_(None)
            )
        ).all()
        for row in rows:
            if not except_hash or row.token_hash != except_hash:
                row.revoked_at = utcnow()
        db.commit()
        return len(rows)
