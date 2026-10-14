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
