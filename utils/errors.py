"""Error handling helpers: never show raw exception text to users, never swallow silently."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

logger = logging.getLogger("app.errors")


def safe_message(
    exc: BaseException, fallback: str = "Something went wrong. Please try again."
) -> str:
    """Return text that is safe to show in the UI.

    Validation-style exceptions (ValueError and its subclasses such as ContentError,
    AvatarError, RateLimitExceeded, JiraError) carry messages written for users and are
    shown. Anything else is logged with a short reference code and replaced by ``fallback``.
    """
    if isinstance(exc, (ValueError, PermissionError)) or type(exc).__name__ in {
        "JiraError",
        "ConfluenceError",
        "RateLimitExceeded",
    }:
        return str(exc)[:300]
    ref = uuid.uuid4().hex[:8]
    logger.error("Unexpected error [%s]", ref, exc_info=exc)
    return f"{fallback} (ref {ref})"


def log_ignored(where: str = "") -> None:
    """Use inside ``except Exception:`` blocks that intentionally continue: records the error."""
    logger.warning("Ignored error in %s", where or "unknown", exc_info=True)


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    severity: str  # warning | error | critical
    message: str  # safe, user-facing text


ERROR_CATALOGUE: dict[str, ErrorInfo] = {
    e.code: e
    for e in (
        ErrorInfo("JSL-AUTH-001", "error", "Sign-in failed. Check your credentials and try again."),
        ErrorInfo("JSL-AUTH-002", "warning", "Your session expired or was revoked. Please sign in again."),
        ErrorInfo("JSL-AUTH-003", "error", "This account is inactive. Contact your administrator."),
        ErrorInfo("JSL-PERM-001", "error", "You do not have permission to do this."),
        ErrorInfo("JSL-JIRA-001", "error", "Jira is not connected. Add your Jira connection in Personal Settings."),
        ErrorInfo("JSL-JIRA-002", "error", "The Jira request failed. Please try again."),
        ErrorInfo("JSL-JIRA-003", "error", "That issue was not found or is not allowed for this library."),
        ErrorInfo("JSL-JIRA-004", "error", "Could not update the Jira issue."),
        ErrorInfo("JSL-DATA-001", "error", "Some of the input is invalid. Check it and try again."),
        ErrorInfo("JSL-FILE-001", "error", "That file type or file is not supported."),
        ErrorInfo("JSL-DB-001", "critical", "A database error occurred. Please try again shortly."),
        ErrorInfo("JSL-SYS-001", "critical", "Unexpected application error. Please try again."),
        ErrorInfo("JSL-RATE-001", "warning", "Too many attempts. Wait a moment and try again."),
    )
}
_FALLBACK_CODE = "JSL-SYS-001"


def lookup_error(code: str) -> ErrorInfo | None:
    """Return the catalogue entry for ``code``, or None if it is unknown."""
    return ERROR_CATALOGUE.get(code)


def format_error(code: str, ref: str | None = None) -> str:
    """User text with the code (and an optional correlation ``ref``) for support."""
    info = lookup_error(code) or ERROR_CATALOGUE[_FALLBACK_CODE]
    suffix = f" (Ref {ref})" if ref else ""
    return f"{info.message} [{info.code}]{suffix}"


def user_error(code: str, ref: str | None = None) -> str:
    """Like ``format_error`` but unknown codes fall back to JSL-SYS-001."""
    return format_error(code if code in ERROR_CATALOGUE else _FALLBACK_CODE, ref)
