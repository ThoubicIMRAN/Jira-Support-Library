"""Input validators."""
from __future__ import annotations

import re

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
# At least 8 chars, 1 upper, 1 lower, 1 digit (special optional but encouraged)
_PASSWORD = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,128}$"
)


def valid_password(value: str | None) -> bool:
    """Enterprise baseline: 8–128 chars, upper, lower, digit."""
    if not value or len(value) < 8 or len(value) > 128:
        return False
    return bool(_PASSWORD.match(value))


def password_policy_message() -> str:
    return (
        "Password must be 8–128 characters and include at least one uppercase letter, "
        "one lowercase letter, and one digit."
    )


def valid_hex_color(value: str | None) -> bool:
    return bool(value and _HEX.match(value.strip()))


def clean_key(value: str | None) -> str:
    return (value or "").strip().upper().replace(" ", "")
