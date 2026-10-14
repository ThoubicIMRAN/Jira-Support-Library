"""Flag library responses that have not been updated recently."""
from __future__ import annotations

from datetime import datetime, timezone

STALE_DAYS_DEFAULT = 90


def is_stale(updated_at, *, days: int = STALE_DAYS_DEFAULT) -> bool:
    if not updated_at:
        return True
    if getattr(updated_at, "tzinfo", None) is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - updated_at
    return age.days >= days


def stale_label(updated_at, *, days: int = STALE_DAYS_DEFAULT) -> str | None:
    if is_stale(updated_at, days=days):
        return f"Stale ({days}d+)"
    return None
