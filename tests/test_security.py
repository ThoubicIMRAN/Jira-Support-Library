import os
import subprocess
import sys
from pathlib import Path

from conftest import PASSWORD

ROOT = Path(__file__).resolve().parents[1]


def test_password_hash_and_verify():
    from auth import hash_password, verify_password

    h = hash_password(PASSWORD)
    assert (
        h != PASSWORD
        and verify_password(PASSWORD, h)
        and not verify_password("nope", h)
    )


def test_secret_encrypt_roundtrip():
    from utils.security import decrypt_secret, encrypt_secret

    assert decrypt_secret(encrypt_secret("smtp-pass")) == "smtp-pass"


def test_production_refuses_default_secret():
    env = {
        **os.environ,
        "APP_ENV": "production",
        "APP_SECRET_KEY": "",
        "FERNET_KEY": "",
    }
    out = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0


def test_no_password_is_printed_or_logged():
    source = (ROOT / "auth.py").read_text(encoding="utf-8")
    assert "print(" not in source
    assert "logger.info(f" not in source


def test_session_lifecycle():
    from services.session_service import (
        create_session,
        revoke_session,
        validate_session,
    )

    token = create_session(1, "local")
    assert validate_session(token) == 1
    revoke_session(token)
    assert validate_session(token) is None


def test_role_permissions():
    from auth import allowed

    assert allowed("superadmin", "delete") and not allowed("viewer", "create")


def test_navigation_pages_are_routable():
    from utils.navigation import PAGE_SECURITY_ADMIN, VALID_PAGES

    assert PAGE_SECURITY_ADMIN in VALID_PAGES and PAGE_SECURITY_ADMIN == "security"


def _session_lifetime(raw):
    from sqlalchemy import select

    from database import AppSession, SessionLocal
    from utils.security import token_hash
    from utils.timeutil import as_utc

    with SessionLocal() as db:
        row = db.scalar(select(AppSession).where(AppSession.token_hash == token_hash(raw)))
        return as_utc(row.expires_at) - as_utc(row.created_at)


def test_remember_me_session_lives_longer_and_both_validate():
    from datetime import timedelta

    from sqlalchemy import select

    from config import REMEMBER_ME_DAYS, SESSION_ABSOLUTE_HOURS
    from database import SessionLocal, User
    from services.session_service import create_session, validate_session

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == "admin"))
    normal, remembered = create_session(uid), create_session(uid, remember=True)
    assert _session_lifetime(normal) == timedelta(hours=SESSION_ABSOLUTE_HOURS)
    assert _session_lifetime(remembered) == timedelta(days=REMEMBER_ME_DAYS)
    assert validate_session(normal) == uid and validate_session(remembered) == uid


def test_remember_me_idle_timeout_applies_only_to_remembered_sessions(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from database import AppSession, SessionLocal, User
    from services import session_service
    from utils.security import token_hash

    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == "admin"))
    remembered = session_service.create_session(uid, remember=True)
    with SessionLocal() as db:
        row = db.scalar(select(AppSession).where(AppSession.token_hash == token_hash(remembered)))
        row.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()
    def make_idle():  # a valid check "touches" the session, so age it again before each check
        with SessionLocal() as db:
            row = db.scalar(select(AppSession).where(AppSession.token_hash == token_hash(remembered)))
            row.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=30)
            db.commit()

    monkeypatch.setattr(session_service, "REMEMBER_ME_IDLE_TIMEOUT_MINUTES", 0)
    assert session_service.validate_session(remembered) == uid  # 0 = no idle timeout
    make_idle()
    monkeypatch.setattr(session_service, "REMEMBER_ME_IDLE_TIMEOUT_MINUTES", 10)
    assert session_service.validate_session(remembered) is None


def test_passkeys_switch_off_in_production_with_a_localhost_rp_id(monkeypatch):
    import importlib

    from services import passkey_service

    monkeypatch.setattr("config.IS_PRODUCTION", True)
    monkeypatch.setenv("WEBAUTHN_ENABLED", "true")
    monkeypatch.delenv("WEBAUTHN_RP_ID", raising=False)
    try:
        assert importlib.reload(passkey_service).WEBAUTHN_ENABLED is False
        monkeypatch.setenv("WEBAUTHN_RP_ID", "support.example.com")
        assert importlib.reload(passkey_service).WEBAUTHN_ENABLED is True
    finally:
        monkeypatch.undo()
        importlib.reload(passkey_service)
