"""Error catalogue contract tests (no Streamlit / DB required)."""

from __future__ import annotations

from utils.errors import (
    ERROR_CATALOGUE,
    format_error,
    lookup_error,
    safe_message,
    user_error,
)


def test_catalogue_has_required_codes():
    required = {
        "JSL-AUTH-001",
        "JSL-AUTH-002",
        "JSL-PERM-001",
        "JSL-JIRA-001",
        "JSL-JIRA-002",
        "JSL-JIRA-003",
        "JSL-JIRA-004",
        "JSL-DATA-001",
        "JSL-FILE-001",
        "JSL-DB-001",
        "JSL-SYS-001",
        "JSL-RATE-001",
    }
    assert required <= set(ERROR_CATALOGUE)


def test_format_error_includes_code_or_ref():
    text = format_error("JSL-PERM-001")
    assert "permission" in text.lower() or "Permission" in text
    assert "JSL-PERM-001" in text or "Ref" in text


def test_user_error_unknown_falls_back_to_sys():
    text = user_error("JSL-DOES-NOT-EXIST")
    assert "JSL-SYS-001" in text or "Unexpected" in text


def test_safe_message_preserves_value_error():
    assert "bad field" in safe_message(ValueError("bad field"))


def test_safe_message_unexpected_hides_detail():
    class Boom(RuntimeError):
        pass

    text = safe_message(Boom("secret internals"))
    assert "secret internals" not in text
    assert "ref" in text.lower()


def test_lookup_error():
    assert lookup_error("JSL-JIRA-001") is not None
    assert lookup_error("nope") is None
