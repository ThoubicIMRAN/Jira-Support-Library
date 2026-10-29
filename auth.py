import logging
import os
import secrets
import sys
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from database import SessionLocal, User, AuditLog
from services.security_policy import is_locked, record_attempt
from services.rate_limit import limit_login, RateLimitExceeded
from config import ALLOW_DEFAULT_BOOTSTRAP_ADMIN, APP_ENV, BOOTSTRAP_ADMIN_USERNAME

logger = logging.getLogger(__name__)

PERMISSIONS = {
    "user": {"view", "copy", "export", "use_ai"},
    "manager": {
        "view", "copy", "export", "use_ai", "create", "edit", "duplicate",
        "save_library", "approve_content",
    },
    "admin": {
        "view", "copy", "export", "use_ai", "import", "create", "edit",
        "duplicate", "delete", "manage_content", "save_library", "approve_content",
    },
    "superadmin": {"*"},
}


def hash_password(value):
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def verify_password(value, hashed):
    return bool(hashed) and bcrypt.checkpw(value.encode(), hashed.encode())


def allowed(role, permission):
    return "*" in PERMISSIONS.get(role, set()) or permission in PERMISSIONS.get(
        role, set()
    )


def authenticate(username, password, *, client_ip: str = ""):
    identity = (username or "").strip().lower()
    if not identity:
        return None, "Invalid credentials or inactive account."
    try:
        limit_login(identity, client_ip or "")
    except RateLimitExceeded as exc:
        return None, f"Too many login attempts. Try again in about {exc.retry_after} seconds."
    if is_locked(identity):
        return None, "Account temporarily locked. Try again later."
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username.strip()))
        success = bool(
            user and user.is_active and verify_password(password, user.password_hash)
        )
        record_attempt(identity, success)
        if not success:
            return None, "Invalid credentials or inactive account."
        user.last_login = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                user_id=user.id,
                action="login",
                entity_type="user",
                entity_id=str(user.id),
                details="local",
            )
        )
        db.commit()
        db.refresh(user)
        return user, None


def ensure_superadmin():
    """Create the bootstrap admin on first start."""
    if APP_ENV == "production" and not ALLOW_DEFAULT_BOOTSTRAP_ADMIN:
        return

    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    force_reset = os.getenv("FORCE_RESET_ADMIN_PASSWORD", "").strip().lower() in ("1", "true", "yes", "on")

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == BOOTSTRAP_ADMIN_USERNAME))

        if admin is None:
            generated = False
            if not password:
                if APP_ENV == "production":
                    raise RuntimeError(
                        "BOOTSTRAP_ADMIN_PASSWORD must be set to create the first admin in production."
                    )
                password, generated = secrets.token_urlsafe(16), True
            db.add(
                User(
                    username=BOOTSTRAP_ADMIN_USERNAME,
                    email=None,
                    full_name="System Administrator",
                    designation="Administrator",
                    password_hash=hash_password(password),
                    role="superadmin",
                    must_change_password=True,
                    is_active=True,
                )
            )
            db.commit()
            logger.info(
                "Bootstrap superadmin %r created (must change password on first login)",
                BOOTSTRAP_ADMIN_USERNAME,
            )
            if generated:
                sys.stderr.write(
                    f"\n[dev] Bootstrap admin created. username={BOOTSTRAP_ADMIN_USERNAME} password={password}\n\n"
                )
            return

        if force_reset and password:
            if APP_ENV == "production":
                logger.warning(
                    "FORCE_RESET_ADMIN_PASSWORD ignored in production; use scripts/reset_admin_password.py"
                )
                return
            admin.password_hash = hash_password(password)
            admin.must_change_password = True
            admin.is_active = True
            db.commit()
            logger.warning(
                "Admin password was reset from the environment. Set FORCE_RESET_ADMIN_PASSWORD=false."
            )
