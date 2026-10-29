from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from utils.timeutil import as_utc
from database import SessionLocal, User, PasswordResetToken, UserInvitation, AuditLog
from auth import hash_password
from config import APP_URL, RESET_TOKEN_MINUTES, INVITATION_TOKEN_HOURS
from email_service import send_html_email, branded_email
from utils.security import token_urlsafe, token_hash


def utcnow(): return datetime.now(timezone.utc)


def request_password_reset(email):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower(), User.is_active == True))
        if not user:
            return True
        db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).values(used_at=utcnow()))
        raw = token_urlsafe()
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash(raw), expires_at=utcnow()+timedelta(minutes=RESET_TOKEN_MINUTES)))
        db.commit()
        url=f'{APP_URL}/?reset_token={raw}'
        send_html_email(user.email, 'Reset your Jira Support Library password', branded_email('Password reset', f'<p>Hello {user.full_name},</p><p>This link expires in {RESET_TOKEN_MINUTES} minutes and can be used once.</p>', 'Reset password', url))
        return True


def validate_reset_token(raw):
    with SessionLocal() as db:
        row=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==token_hash(raw), PasswordResetToken.used_at.is_(None)))
        if not row or as_utc(row.expires_at) < utcnow(): return None
        return row.user_id


def consume_reset_token(raw, password):
    with SessionLocal() as db:
        row=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==token_hash(raw), PasswordResetToken.used_at.is_(None)))
        if not row or as_utc(row.expires_at) < utcnow(): return False
        user=db.get(User,row.user_id); user.password_hash=hash_password(password); user.must_change_password=False; row.used_at=utcnow()
        db.add(AuditLog(user_id=user.id,action='password_reset',entity_type='user',entity_id=str(user.id),details='self-service'))
        db.commit(); return True


def create_invitation(email, role, designation, invited_by):
    raw=token_urlsafe()
    with SessionLocal() as db:
        row=UserInvitation(email=email.strip().lower(),role=role,designation=designation.strip() or 'Support Engineer',token_hash=token_hash(raw),expires_at=utcnow()+timedelta(hours=INVITATION_TOKEN_HOURS),invited_by=invited_by)
        db.add(row); db.commit()
    url=f'{APP_URL}/?invite_token={raw}'
    send_html_email(email, 'Invitation to Jira Support Library', branded_email('You are invited', f'<p>You were invited with the <strong>{role}</strong> role.</p><p>This invitation expires in {INVITATION_TOKEN_HOURS} hours.</p>', 'Accept invitation', url))
    return True


def validate_invitation(raw):
    with SessionLocal() as db:
        row=db.scalar(select(UserInvitation).where(UserInvitation.token_hash==token_hash(raw),UserInvitation.accepted_at.is_(None)))
        if not row or as_utc(row.expires_at) < utcnow(): return None
        return {'email':row.email,'role':row.role,'designation':row.designation}


def accept_invitation(raw, username, full_name, password):
    with SessionLocal() as db:
        row=db.scalar(select(UserInvitation).where(UserInvitation.token_hash==token_hash(raw),UserInvitation.accepted_at.is_(None)))
        if not row or as_utc(row.expires_at) < utcnow(): return False
        if db.scalar(select(User).where((User.username==username)|(User.email==row.email))): raise ValueError('Username or email already exists.')
        user=User(username=username,email=row.email,full_name=full_name,designation=row.designation,role=row.role,password_hash=hash_password(password),must_change_password=False)
        db.add(user); row.accepted_at=utcnow(); db.commit(); return True


def register_user(username, full_name, email, password, designation='Support Engineer'):
    """Public self-registration as role=user. Raises ValueError on conflict."""
    username = (username or '').strip()
    full_name = (full_name or '').strip()
    email = (email or '').strip().lower() or None
    designation = (designation or 'Support Engineer').strip() or 'Support Engineer'
    if not username or not full_name:
        raise ValueError('Username and full name are required.')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise ValueError('That username is already taken.')
        if email and db.scalar(select(User).where(User.email == email)):
            raise ValueError('That email is already registered.')
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            designation=designation,
            role='user',
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(AuditLog(
            user_id=user.id,
            action='register',
            entity_type='user',
            entity_id=str(user.id),
            details='self-registration',
        ))
        db.commit()
        return True


def admin_set_password(target_user_id: int, new_password: str, actor_id: int) -> None:
    """Superadmin sets a temporary password; user must change on next login."""
    from utils.validators import valid_password
    if not valid_password(new_password or ""):
        raise ValueError("Password must be at least 8 characters.")
    with SessionLocal() as db:
        target = db.get(User, target_user_id)
        if not target:
            raise ValueError("User not found.")
        if target.id == actor_id:
            raise ValueError("Use Change password for your own account.")
        target.password_hash = hash_password(new_password)
        target.must_change_password = True
        target.is_active = True
        db.add(AuditLog(
            user_id=actor_id,
            action="admin_set_password",
            entity_type="user",
            entity_id=str(target.id),
            details=target.username,
        ))
        db.commit()
    unlock_login(target.username)


def unlock_login(identity: str) -> int:
    """Clear recent failed login attempts so the account is no longer locked."""
    from database import LoginAttempt
    from sqlalchemy import delete as sa_delete
    ident = (identity or "").strip().lower()
    if not ident:
        return 0
    with SessionLocal() as db:
        # Also try username as stored (case variants)
        result = db.execute(
            sa_delete(LoginAttempt).where(LoginAttempt.identity == ident)
        )
        db.commit()
        return result.rowcount or 0


def delete_user(target_user_id: int, actor_id: int) -> None:
    """Delete a user account while preserving audit history.

    - AuditLog.user_id set to NULL (logs kept)
    - Other nullable FKs nulled
    - CASCADE children removed with the user
    - User row deleted
    """
    from sqlalchemy import delete as sa_delete, update as sa_update
    from database import (
        AuditLog,
        LoginAttempt,
        PasswordResetToken,
        UserInvitation,
        UserAuthIdentity,
        AppSession,
        OAuthTransaction,
        UserPreference,
        UserFavorite,
        UserPinnedProject,
        UserRecentResponse,
        UserSavedSearch,
        UserNotificationState,
        UserProjectDesignation,
        UserProjectAccess,
        UserJiraCredential,
        UserConfluenceCredential,
        BulkPostLog,
    )

    if target_user_id == actor_id:
        raise ValueError("You cannot delete your own account.")

    with SessionLocal() as db:
        target = db.get(User, target_user_id)
        if not target:
            raise ValueError("User not found.")
        if target.role == "superadmin":
            # Prevent deleting the last superadmin
            from sqlalchemy import func
            n = db.scalar(
                select(func.count()).select_from(User).where(
                    User.role == "superadmin", User.is_active == True  # noqa: E712
                )
            ) or 0
            if n <= 1:
                raise ValueError("Cannot delete the last active superadmin.")

        username = target.username
        uid = target.id

        # Preserve audit: null out actor references
        db.execute(
            sa_update(AuditLog).where(AuditLog.user_id == uid).values(user_id=None)
        )
        # Null other non-cascade FKs that block delete
        try:
            db.execute(
                sa_update(UserInvitation)
                .where(UserInvitation.invited_by == uid)
                .values(invited_by=None)
            )
        except Exception:
            pass
        try:
            db.execute(
                sa_update(OAuthTransaction)
                .where(OAuthTransaction.link_user_id == uid)
                .values(link_user_id=None)
            )
        except Exception:
            pass
        try:
            from database import Announcement, MaintenanceWindow
            for Model, col in (
                (Announcement, "created_by"),
                (MaintenanceWindow, "created_by"),
            ):
                if hasattr(Model, col):
                    db.execute(
                        sa_update(Model).where(getattr(Model, col) == uid).values(**{col: None})
                    )
        except Exception:
            pass
        try:
            db.execute(
                sa_update(BulkPostLog).where(BulkPostLog.user_id == uid).values(user_id=None)
            )
        except Exception:
            pass

        # Explicit cleanup of identity-related rows (CASCADE should handle, but be safe)
        for Model in (
            PasswordResetToken,
            UserAuthIdentity,
            AppSession,
            UserPreference,
            UserFavorite,
            UserPinnedProject,
            UserRecentResponse,
            UserSavedSearch,
            UserNotificationState,
            UserProjectDesignation,
            UserProjectAccess,
            UserJiraCredential,
            UserConfluenceCredential,
        ):
            try:
                db.execute(sa_delete(Model).where(Model.user_id == uid))
            except Exception:
                pass

        try:
            from database import UserSnipeITCredential
            db.execute(sa_delete(UserSnipeITCredential).where(UserSnipeITCredential.user_id == uid))
        except Exception:
            pass

        # Login attempts by username
        db.execute(sa_delete(LoginAttempt).where(LoginAttempt.identity == username.lower()))

        db.add(AuditLog(
            user_id=actor_id,
            action="delete_user",
            entity_type="user",
            entity_id=str(uid),
            details=f"deleted username={username}",
        ))
        db.delete(target)
        db.commit()


def admin_update_user(
    actor_id: int,
    target_id: int,
    *,
    full_name: str | None = None,
    email: str | None = None,
    designation: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> None:
    """Admin/superadmin updates profile fields for another user (RBAC enforced by caller)."""
    ROLES = {"user", "manager", "admin", "superadmin"}
    with SessionLocal() as db:
        actor = db.get(User, actor_id)
        target = db.get(User, target_id)
        if not actor or not target:
            raise ValueError("User not found.")
        if target_id == actor_id and role is not None and role != target.role:
            raise ValueError("You cannot change your own role here.")
        if full_name is not None:
            full_name = full_name.strip()
            if not full_name:
                raise ValueError("Full name is required.")
            target.full_name = full_name
        if email is not None:
            email = email.strip().lower() or None
            if email:
                other = db.scalar(select(User).where(User.email == email, User.id != target_id))
                if other:
                    raise ValueError("That email is already in use.")
            target.email = email
        if designation is not None:
            target.designation = (designation.strip() or "Support Engineer")[:180]
        if role is not None:
            if role not in ROLES:
                raise ValueError("Invalid role.")
            if actor.role != "superadmin" and role in ("admin", "superadmin"):
                raise ValueError("Only a superadmin can assign privileged roles.")
            if target.role == "superadmin" and role != "superadmin":
                from sqlalchemy import func
                n = db.scalar(
                    select(func.count()).select_from(User).where(
                        User.role == "superadmin", User.is_active == True  # noqa: E712
                    )
                ) or 0
                if n <= 1:
                    raise ValueError("Cannot demote the last active superadmin.")
            target.role = role
        if is_active is not None:
            if target_id == actor_id and not is_active:
                raise ValueError("You cannot deactivate your own account.")
            target.is_active = bool(is_active)
        db.add(AuditLog(
            user_id=actor_id,
            action="admin_update_user",
            entity_type="user",
            entity_id=str(target_id),
            details=target.username,
        ))
        db.commit()
