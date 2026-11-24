from __future__ import annotations

import secrets

import pytest

from database import SessionLocal, User, WebAuthnCredential
from services.passkey_service import (
    RP_ID,
    _origin_value,
    list_passkeys,
    remove_passkey,
    start_authentication,
    start_registration,
)


def test_origin_uses_app_url_when_environment_value_is_blank():
    assert (
        _origin_value("  ", "https://support.example.com/app")
        == "https://support.example.com"
    )


def _create_user(*, password_hash: str | None = None) -> tuple[int, int]:
    suffix = secrets.token_hex(6)
    with SessionLocal() as db:
        user = User(
            username=f"passkey-{suffix}",
            full_name="Passkey Test User",
            password_hash=password_hash,
        )
        db.add(user)
        db.flush()
        credential = WebAuthnCredential(
            user_id=user.id,
            credential_id=f"credential-{suffix}",
            public_key="public-key",
            device_name="Test device",
        )
        db.add(credential)
        db.commit()
        return user.id, credential.id


def test_registration_options_require_a_discoverable_passkey():
    user_id, _ = _create_user(password_hash="hashed-password")

    registration = start_registration(user_id, f"user-{user_id}", "Test User")

    assert registration["challenge"]
    assert registration["options"]["rp"]["id"] == RP_ID
    assert (
        registration["options"]["authenticatorSelection"]["residentKey"] == "required"
    )


def test_authentication_options_allow_discoverable_credentials():
    authentication = start_authentication()

    assert authentication["challenge"]
    assert authentication["options"]["rpId"] == RP_ID
    assert authentication["options"].get("allowCredentials") in (None, [])


def test_user_cannot_remove_their_only_sign_in_method():
    user_id, passkey_id = _create_user()

    with pytest.raises(
        ValueError, match="Set a password or link another sign-in method"
    ):
        remove_passkey(user_id, passkey_id)

    assert len(list_passkeys(user_id)) == 1


def test_user_can_remove_passkey_when_password_is_configured():
    user_id, passkey_id = _create_user(password_hash="hashed-password")

    assert remove_passkey(user_id, passkey_id)
    assert list_passkeys(user_id) == []
