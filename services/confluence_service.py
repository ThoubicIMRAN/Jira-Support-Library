"""Per-user Confluence PAT; base URL from admin env CONFLUENCE_BASE_URL."""
from __future__ import annotations

import logging
from typing import Any

import requests
from sqlalchemy import select

from config import CONFLUENCE_BASE_URL, JIRA_REQUEST_TIMEOUT
from database import SessionLocal
from services.confluence_client import (
    ConfluenceError,
    fetch_page as _fetch_page,
)
from utils.security import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


def _load_row(user_id: int):
    from database import UserConfluenceCredential

    with SessionLocal() as db:
        row = db.scalar(
            select(UserConfluenceCredential).where(
                UserConfluenceCredential.user_id == user_id
            )
        )
        if row:
            db.expunge(row)
        return row


def status(user_id: int) -> dict[str, Any]:
    row = _load_row(user_id)
    base = (CONFLUENCE_BASE_URL or "").rstrip("/")
    return {
        "configured": bool(row and row.encrypted_secret),
        "has_own_token": bool(row and row.encrypted_secret),
        "base_url": base or (row.base_url if row else None),
        "email": row.email if row else None,
        "admin_base_url": base,
    }


def save_credentials(
    user_id: int,
    *,
    email: str | None = None,
    secret: str | None = None,
    base_url: str | None = None,
) -> None:
    """Save user Confluence username + PAT. Base URL comes from env when set."""
    from database import UserConfluenceCredential

    with SessionLocal() as db:
        row = db.scalar(
            select(UserConfluenceCredential).where(
                UserConfluenceCredential.user_id == user_id
            )
        )
        if not row:
            row = UserConfluenceCredential(user_id=user_id)
            db.add(row)
        row.use_jira_credentials = False
        # Prefer admin env; allow override only if env empty
        env_base = (CONFLUENCE_BASE_URL or "").strip().rstrip("/")
        row.base_url = env_base or ((base_url or "").strip().rstrip("/") or None)
        row.email = (email or "").strip() or None
        if secret and secret.strip():
            row.encrypted_secret = encrypt_secret(secret.strip())
        db.commit()


def disconnect(user_id: int) -> None:
    from database import UserConfluenceCredential

    with SessionLocal() as db:
        row = db.scalar(
            select(UserConfluenceCredential).where(
                UserConfluenceCredential.user_id == user_id
            )
        )
        if row:
            db.delete(row)
            db.commit()


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url or "").hostname or "").lower()


def resolve_auth(user_id: int, page_url: str | None = None) -> dict[str, str]:
    """Credentials + the ONLY host we will talk to (CONFLUENCE_BASE_URL).

    The base URL is never taken from user input: a pasted link on another host
    is rejected, so a PAT can never be sent to an arbitrary server (SSRF / token leak).
    """
    base = (CONFLUENCE_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise ConfluenceError("Confluence is not configured. An administrator must set CONFLUENCE_BASE_URL.")
    if page_url and page_url.strip().lower().startswith("http") and _host(page_url) != _host(base):
        raise ConfluenceError("That link is not on the configured Confluence site.")
    row = _load_row(user_id)
    if not row or not row.encrypted_secret:
        raise ConfluenceError(
            "Save your Confluence username + Personal Access Token under "
            "Settings → Jira connection → Confluence."
        )
    return {
        "base_url": base,
        "email": (row.email or "").strip(),
        "secret": decrypt_secret(row.encrypted_secret).strip(),
        "source": "confluence_pat",
    }


def test_connection(user_id: int, page_url: str | None = None) -> dict[str, Any]:
    auth = resolve_auth(user_id, page_url=page_url)
    base = (auth.get("base_url") or "").rstrip("/")
    secret = auth["secret"]
    result: dict[str, Any] = {
        "ok": False,
        "base_url": base,
        "auth_source": auth.get("source"),
        "attempts": [],
    }
    if not base:
        result["error"] = (
            "CONFLUENCE_BASE_URL is not set in the environment (admin). "
            "Example: CONFLUENCE_BASE_URL=https://confluence.example.com"
        )
        return result

    url = f"{base}/rest/api/user/current"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
            timeout=JIRA_REQUEST_TIMEOUT,
        )
        result["attempts"].append(f"Bearer: HTTP {resp.status_code}")
        if resp.status_code == 200:
            result["ok"] = True
            result["worked"] = "Bearer"
            try:
                result["user"] = resp.json()
            except Exception:
                pass
            return result
    except requests.RequestException as exc:
        result["attempts"].append(f"Bearer: network {exc}")

    result["error"] = "Confluence PAT rejected or unreachable. Recreate the token and Save & test."
    return result


def fetch_page_for_user(user_id: int, url_or_id: str) -> dict[str, Any]:
    auth = resolve_auth(user_id, page_url=url_or_id)
    return _fetch_page(
        url_or_id,
        base_url=auth["base_url"],
        email=auth["email"] or None,
        secret=auth["secret"],
    )
