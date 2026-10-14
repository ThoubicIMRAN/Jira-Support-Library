import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import (
    LOGIN_LOCK_MINUTES,
    LOGIN_MAX_FAILURES,
    MS_ALLOWED_TENANT_IDS,
    MS_APP_ROLE_MAP,
    OAUTH_ALLOWED_DOMAINS,
)
from database import LoginAttempt, SessionLocal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_locked(identity: str) -> bool:
    cutoff = utcnow() - timedelta(minutes=LOGIN_LOCK_MINUTES)
    with SessionLocal() as db:
        rows = db.scalars(
            select(LoginAttempt)
            .where(LoginAttempt.identity == identity.lower(), LoginAttempt.attempted_at >= cutoff)
            .order_by(LoginAttempt.attempted_at.desc())
        ).all()
        failures = 0
        for row in rows:
            if row.succeeded:
                break
            failures += 1
        return failures >= LOGIN_MAX_FAILURES


def record_attempt(identity: str, succeeded: bool) -> None:
    with SessionLocal() as db:
        db.add(LoginAttempt(identity=identity.lower(), succeeded=succeeded))
        db.commit()


def email_allowed(email: str) -> bool:
    if not OAUTH_ALLOWED_DOMAINS:
        return True
    domain = (email.rsplit("@", 1)[-1] if "@" in email else "").lower()
    return domain in OAUTH_ALLOWED_DOMAINS


def tenant_allowed(tenant_id: str | None) -> bool:
    return not MS_ALLOWED_TENANT_IDS or (tenant_id or "").lower() in MS_ALLOWED_TENANT_IDS


def mapped_ms_role(claim_roles):
    raw = MS_APP_ROLE_MAP or {}
    mapping = dict(raw) if isinstance(raw, dict) else json.loads(raw or "{}") if isinstance(raw, str) else {}
    rank = {"user": 0, "manager": 1, "admin": 2, "superadmin": 3}
    result = "user"
    for claim in claim_roles or []:
        candidate = mapping.get(claim, "user")
        if rank.get(candidate, 0) > rank[result]:
            result = candidate
    return result

