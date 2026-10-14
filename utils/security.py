"""Cryptographic helpers for token generation and secret storage.

Tokens:
    token_urlsafe() -> str   : URL-safe random string (32 bytes entropy)
    token_hash(t)   -> str   : SHA-256 hex digest; store this, not the token

Secrets (Fernet):
    encrypt_secret(s) -> str : returns "" for empty input, else ASCII token
    decrypt_secret(t) -> str : returns "" for empty input, raises on tamper

Key resolution (in order):
    1. FERNET_KEY env var          — preferred
    2. APP_SECRET_KEY env var      — derivation fallback (SHA-256 → base64)
    3. Refuse to run with no key   — prevents silent encryption under a default
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import warnings
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

__all__ = [
    "token_urlsafe",
    "token_hash",
    "encrypt_secret",
    "decrypt_secret",
]


DECRYPT_ERROR = (
    "Unable to decrypt stored secret. Verify FERNET_KEY / APP_SECRET_KEY."
)


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def token_urlsafe() -> str:
    """Return a URL-safe random token (32 bytes of entropy)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Return the SHA-256 hex digest of `token`.

    Use this as a lookup key in the DB — never store the raw token.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Fernet key resolution
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = os.getenv("FERNET_KEY", "").strip()
    if raw:
        return Fernet(raw.encode("ascii"))

    from config import APP_ENV, APP_SECRET_KEY

    secret = (APP_SECRET_KEY or "").strip()
    if not secret:
        raise RuntimeError(
            "Neither FERNET_KEY nor APP_SECRET_KEY is set. Refusing to "
            "encrypt or decrypt with a default key."
        )

    if APP_ENV == "production":
        warnings.warn(
            "FERNET_KEY is not set in production — deriving a key from "
            "APP_SECRET_KEY. Rotating APP_SECRET_KEY will invalidate every "
            "stored secret.",
            stacklevel=2,
        )

    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


# --------------------------------------------------------------------------- #
# Secret encryption
# --------------------------------------------------------------------------- #
def encrypt_secret(value: str | None) -> str:
    """Encrypt `value` and return an ASCII Fernet token.

    Empty input returns an empty string so callers can distinguish
    "no secret set" from "secret set to empty string".
    """
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    """Decrypt a Fernet token produced by `encrypt_secret`.

    Empty input returns an empty string. Raises `ValueError` on tampered,
    truncated, or non-ASCII tokens.
    """
    if not value:
        return ""

    try:
        token = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Ciphertext is not valid ASCII.") from exc

    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(DECRYPT_ERROR) from exc