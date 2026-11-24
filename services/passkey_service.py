"""WebAuthn / Passkey support (YubiKey, Bitwarden, platform authenticators, etc.)."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from config import APP_URL, IS_PRODUCTION
from database import SessionLocal, User, UserAuthIdentity, WebAuthnCredential
from services.audit_service import record as audit

logger = logging.getLogger(__name__)

# Relying Party settings must match the application's public HTTPS origin.
WEBAUTHN_ENABLED = os.getenv("WEBAUTHN_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
RP_ID = os.getenv("WEBAUTHN_RP_ID", "localhost")
RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Jira Support Library")

# In production a localhost relying-party ID can never match the real site, so enrollment and
# sign-in would silently fail. Turn passkeys off (and say so) until WEBAUTHN_RP_ID is configured.
if WEBAUTHN_ENABLED and IS_PRODUCTION and RP_ID.strip().lower() in {"", "localhost", "your-application-domain"}:
    logger.error(
        "Passkeys disabled: set WEBAUTHN_RP_ID (public hostname) and WEBAUTHN_ORIGIN, "
        "or set WEBAUTHN_ENABLED=false to silence this."
    )
    WEBAUTHN_ENABLED = False


def _origin_value(configured_origin: str | None, app_url: str | None) -> str:
    """Resolve WebAuthn's origin, excluding any reverse-proxy path."""
    candidate = (configured_origin or "").strip() or app_url or "http://localhost:8501"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return candidate.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


ORIGIN = _origin_value(os.getenv("WEBAUTHN_ORIGIN"), APP_URL)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _from_b64url(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _transports(values: object) -> list[AuthenticatorTransport]:
    """Keep only standards-supported transport hints from untrusted input."""
    if not isinstance(values, list):
        return []
    supported = {transport.value: transport for transport in AuthenticatorTransport}
    return [
        supported[value]
        for value in values
        if isinstance(value, str) and value in supported
    ]


def _require_enabled() -> None:
    if not WEBAUTHN_ENABLED:
        raise RuntimeError("Passkey sign-in is disabled.")


# ── Registration (user adds a YubiKey / Bitwarden passkey) ───────────────────


def start_registration(user_id: int, username: str, display_name: str) -> dict:
    """Return PublicKeyCredentialCreationOptions as JSON-serialisable dict."""
    _require_enabled()
    with SessionLocal() as db:
        existing_credentials = db.scalars(
            select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
        ).all()
    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(user_id).encode(),
        user_name=username,
        user_display_name=display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(
                id=_from_b64url(row.credential_id),
                transports=_transports((row.transports or "").split(",")),
            )
            for row in existing_credentials
        ],
    )
    # Store challenge temporarily (in session or Redis in production)
    challenge = _b64url(options.challenge)
    return {
        "options": json.loads(options_to_json(options)),
        "challenge": challenge,
    }


def finish_registration(
    user_id: int,
    credential: dict,
    expected_challenge: str,
    device_name: str = "Passkey",
) -> bool:
    """Verify and store the new credential."""
    _require_enabled()
    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=_from_b64url(expected_challenge),
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
        )
    except Exception:
        logger.exception("Passkey registration verification failed")
        return False

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return False
        credential_id = _b64url(verification.credential_id)
        row = WebAuthnCredential(
            user_id=user_id,
            credential_id=credential_id,
            public_key=_b64url(verification.credential_public_key),
            sign_count=verification.sign_count,
            transports=",".join(
                transport.value
                for transport in _transports(credential.get("transports"))
            ),
            device_name=(device_name or "Passkey").strip()[:128] or "Passkey",
        )
        db.add(row)
        audit(db, user_id, "create", "passkey", credential_id, row.device_name)
        db.commit()
    return True


def list_passkeys(user_id: int) -> list[dict]:
    """Return user-visible passkey metadata, never credential key material."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user_id)
            .order_by(
                WebAuthnCredential.created_at.desc(), WebAuthnCredential.id.desc()
            )
        ).all()
        return [
            {
                "id": row.id,
                "name": row.device_name or "Passkey",
                "created_at": row.created_at,
            }
            for row in rows
        ]


def remove_passkey(user_id: int, passkey_id: int) -> bool:
    """Remove one of the user's passkeys without deleting their last sign-in method."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        row = db.scalar(
            select(WebAuthnCredential).where(
                WebAuthnCredential.id == passkey_id,
                WebAuthnCredential.user_id == user_id,
            )
        )
        if user is None or row is None:
            return False

        passkey_count = (
            db.scalar(
                select(func.count(WebAuthnCredential.id)).where(
                    WebAuthnCredential.user_id == user_id
                )
            )
            or 0
        )
        identity_count = (
            db.scalar(
                select(func.count(UserAuthIdentity.id)).where(
                    UserAuthIdentity.user_id == user_id
                )
            )
            or 0
        )
        if not user.password_hash and not identity_count and passkey_count <= 1:
            raise ValueError(
                "Set a password or link another sign-in method before removing this passkey."
            )

        audit(
            db,
            user_id,
            "delete",
            "passkey",
            row.credential_id,
            row.device_name or "Passkey",
        )
        db.delete(row)
        db.commit()
        return True


# ── Authentication (login with Passkey) ───────────────────────────────────────


def start_authentication(username: str | None = None) -> dict:
    """Return PublicKeyCredentialRequestOptions."""
    _require_enabled()
    allow_credentials = []
    if username:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username.strip()))
            if user:
                creds = db.scalars(
                    select(WebAuthnCredential).where(
                        WebAuthnCredential.user_id == user.id
                    )
                ).all()
                allow_credentials = [
                    PublicKeyCredentialDescriptor(
                        id=_from_b64url(c.credential_id),
                        transports=_transports((c.transports or "").split(",")),
                    )
                    for c in creds
                ]

    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials or None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    challenge = _b64url(options.challenge)
    return {
        "options": json.loads(options_to_json(options)),
        "challenge": challenge,
    }


def finish_authentication(credential: dict, expected_challenge: str) -> Optional[User]:
    """Verify assertion and return the User on success."""
    _require_enabled()
    cred_id = credential.get("id")
    if not cred_id:
        return None

    with SessionLocal() as db:
        row = db.scalar(
            select(WebAuthnCredential).where(
                WebAuthnCredential.credential_id == cred_id
            )
        )
        if not row:
            return None

        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=_from_b64url(expected_challenge),
                expected_rp_id=RP_ID,
                expected_origin=ORIGIN,
                credential_public_key=_from_b64url(row.public_key),
                credential_current_sign_count=row.sign_count,
            )
        except Exception:
            logger.exception("Passkey authentication verification failed")
            return None

        user = db.get(User, row.user_id)
        if user is None or not user.is_active:
            return None

        row.sign_count = verification.new_sign_count
        row.last_used_at = datetime.now(timezone.utc)
        user.last_login = datetime.now(timezone.utc)
        audit(db, user.id, "login", "user", user.id, "passkey")
        db.commit()
        return user
