from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from database import (
    AppSession,
    AuditLog,
    LoginAttempt,
    OAuthTransaction,
    PasswordResetToken,
    SessionLocal,
    UserAuthIdentity,
    UserInvitation,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cleanup_expired(retention_days: int = 30) -> dict[str, int]:
    now = utcnow()
    history_cutoff = now - timedelta(days=retention_days)
    with SessionLocal() as db:
        counts: dict[str, int] = {}
        statements = {
            "sessions": delete(AppSession).where(
                (AppSession.expires_at < now) | (AppSession.revoked_at < history_cutoff)
            ),
            "login_attempts": delete(LoginAttempt).where(LoginAttempt.attempted_at < history_cutoff),
            "oauth_transactions": delete(OAuthTransaction).where(
                (OAuthTransaction.expires_at < now) | (OAuthTransaction.consumed_at < history_cutoff)
            ),
            "password_reset_tokens": delete(PasswordResetToken).where(
                (PasswordResetToken.expires_at < now) | (PasswordResetToken.used_at < history_cutoff)
            ),
            "invitations": delete(UserInvitation).where(
                (UserInvitation.expires_at < now) | (UserInvitation.accepted_at < history_cutoff)
            ),
            "user_auth_identities": delete(UserAuthIdentity).where(
                (UserAuthIdentity.last_used_at < history_cutoff) | (UserAuthIdentity.created_at < history_cutoff)
            ),
            "audit_logs": delete(AuditLog).where(AuditLog.created_at < history_cutoff),
        }
        for name, statement in statements.items():
            counts[name] = db.execute(statement).rowcount or 0
        db.commit()
        return counts
