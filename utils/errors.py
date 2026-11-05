"""Error handling helpers: never show raw exception text to users, never swallow silently."""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger("app.errors")


def safe_message(exc: BaseException, fallback: str = "Something went wrong. Please try again.") -> str:
    """Return text that is safe to show in the UI.

    Validation-style exceptions (ValueError and its subclasses such as ContentError,
    AvatarError, RateLimitExceeded, JiraError) carry messages written for users and are
    shown. Anything else is logged with a short reference code and replaced by ``fallback``.
    """
    if isinstance(exc, (ValueError, PermissionError)) or type(exc).__name__ in {"JiraError", "ConfluenceError", "RateLimitExceeded"}:
        return str(exc)[:300]
    ref = uuid.uuid4().hex[:8]
    logger.error("Unexpected error [%s]", ref, exc_info=exc)
    return f"{fallback} (ref {ref})"


def log_ignored(where: str = "") -> None:
    """Use inside ``except Exception:`` blocks that intentionally continue: records the error."""
    logger.warning("Ignored error in %s", where or "unknown", exc_info=True)
