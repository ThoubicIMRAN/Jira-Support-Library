import os
from conftest import PASSWORD
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_password_hash_and_verify():
    from auth import hash_password, verify_password
    h = hash_password(PASSWORD)
    assert h != PASSWORD and verify_password(PASSWORD, h) and not verify_password("nope", h)


def test_secret_encrypt_roundtrip():
    from utils.security import decrypt_secret, encrypt_secret
    assert decrypt_secret(encrypt_secret("smtp-pass")) == "smtp-pass"


def test_production_refuses_default_secret():
    env = {**os.environ, "APP_ENV": "production", "APP_SECRET_KEY": "", "FERNET_KEY": ""}
    out = subprocess.run([sys.executable, "-c", "import config"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.returncode != 0


def test_no_password_is_printed_or_logged():
    source = (ROOT / "auth.py").read_text(encoding="utf-8")
    assert "print(" not in source
    assert "logger.info(f" not in source


def test_session_lifecycle():
    from services.session_service import create_session, revoke_session, validate_session
    token = create_session(1, "local")
    assert validate_session(token) == 1
    revoke_session(token)
    assert validate_session(token) is None


def test_role_permissions():
    from auth import allowed
    assert allowed("superadmin", "delete") and not allowed("viewer", "create")


def test_navigation_pages_are_routable():
    from utils.navigation import VALID_PAGES, PAGE_SECURITY_ADMIN
    assert PAGE_SECURITY_ADMIN in VALID_PAGES and PAGE_SECURITY_ADMIN == "security"
