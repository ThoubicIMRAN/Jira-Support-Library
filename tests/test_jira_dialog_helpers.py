"""Characterization tests for Jira action dialog pure helpers.

Locks validation and sanitisation behaviour. Pure helpers live in
services/jira_dialog_helpers.py (Phase B). Streamlit is stubbed only for
view-module smoke checks.
"""

from __future__ import annotations

import base64
import sys
import types

import pytest

from services import jira_dialog_helpers as h
from services.jira_client import JiraError


# ---------------------------------------------------------------------------
# safe_text / sanitisation
# ---------------------------------------------------------------------------
def test_safe_text_strips_control_and_markdown_soup():
    assert h.safe_text("a[b](c)<d>`e`\x00\x01") == "abcde"
    assert h.safe_text(None) == ""
    assert len(h.safe_text("x" * 500)) == 400


def test_safe_wiki_user_accepts_valid_and_rejects_invalid():
    assert h.safe_wiki_user("a.rao") == "a.rao"
    assert h.safe_wiki_user("  user_1@x  ") == "user_1@x"
    assert h.safe_wiki_user("") is None
    assert h.safe_wiki_user("bad name") is None
    assert h.safe_wiki_user("a" * 65) is None


def test_safe_filename_strips_path_and_controls():
    assert h.safe_filename(r"C:\tmp\photo.png") == "photo.png"
    assert h.safe_filename("../x\x00y.log") == "xy.log"
    assert h.safe_filename("") == "file"


def test_safe_conf_url():
    assert h.safe_conf_url("https://wiki.example/page") == "https://wiki.example/page"
    assert h.safe_conf_url("ftp://no") is None
    assert h.safe_conf_url("  ") is None


# ---------------------------------------------------------------------------
# issue key / prefix lock
# ---------------------------------------------------------------------------
def test_assert_allowed_requires_linked_prefix():
    project = types.SimpleNamespace(id=None, key="")
    with pytest.raises(JiraError, match="Link this library project"):
        h.assert_issue_allowed("ABC-1", project)


def test_assert_allowed_rejects_wrong_prefix():
    project = types.SimpleNamespace(id=None, key="PROJ")
    with pytest.raises(JiraError, match="Only \\*\\*PROJ-\\*\\*\\*"):
        h.assert_issue_allowed("OTHER-99", project)


def test_assert_allowed_accepts_matching_prefix():
    project = types.SimpleNamespace(id=None, key="PROJ")
    h.assert_issue_allowed("PROJ-42", project)  # no raise


def test_assert_allowed_rejects_malformed_key():
    project = types.SimpleNamespace(id=None, key="PROJ")
    with pytest.raises(JiraError, match="Invalid issue key"):
        h.assert_issue_allowed("1BAD-99", project)


# ---------------------------------------------------------------------------
# prepare_attachment_files
# ---------------------------------------------------------------------------
class _FakeUpload:
    def __init__(self, name: str, data: bytes, mime: str = "image/png"):
        self.name = name
        self.type = mime
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def test_prepare_files_accepts_valid_png():
    data = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    files, problems = h.prepare_attachment_files(
        [_FakeUpload("shot.png", data, "image/png")], "", "PROJ-1"
    )
    assert not problems
    assert len(files) == 1
    assert files[0][0] == "shot.png"
    assert files[0][1] == data


def test_prepare_files_rejects_bad_extension_and_oversize():
    big = b"x" * (h.MAX_ATTACH_BYTES + 1)
    files, problems = h.prepare_attachment_files(
        [
            _FakeUpload("x.exe", b"MZ", "application/octet-stream"),
            _FakeUpload("huge.png", big, "image/png"),
        ],
        "",
        "PROJ-1",
    )
    assert files == []
    assert any("unsupported extension" in p for p in problems)
    assert any("larger than" in p for p in problems)


def test_prepare_files_paste_valid_and_invalid():
    raw = b"\x89PNG\r\n\x1a\n" + b"1" * 20
    b64 = base64.b64encode(raw).decode()
    good = f"data:image/png;base64,{b64}"
    files, problems = h.prepare_attachment_files([], good, "PROJ-1")
    assert not problems
    assert len(files) == 1
    assert files[0][0].startswith("paste_PROJ-1")
    assert files[0][1] == raw

    files2, problems2 = h.prepare_attachment_files(
        [], "data:image/png;base64,!!!", "PROJ-1"
    )
    assert files2 == []
    assert any("Paste:" in p for p in problems2)


def test_prepare_files_paste_too_large():
    raw = b"0" * (h.MAX_PASTE_BYTES + 10)
    b64 = base64.b64encode(raw).decode()
    paste = f"data:image/png;base64,{b64}"
    files, problems = h.prepare_attachment_files([], paste, "PROJ-1")
    assert files == []
    assert any("larger than 8 MB" in p for p in problems)


# ---------------------------------------------------------------------------
# watcher collection
# ---------------------------------------------------------------------------
def test_collect_watcher_ids_dedupes_and_caps():
    ids = h.collect_watcher_ids(
        watch_assignee=True,
        assignee_username="assignee.user",
        extra_as_watchers=True,
        extra_mentions="a.rao, a.rao, @b.lee, bad name",
        auto_watch_from_body=["c.pat", "a.rao"],
    )
    assert ids[0] == "assignee.user"
    assert ids.count("a.rao") == 1
    assert "b.lee" in ids
    assert "c.pat" in ids
    assert "bad name" not in ids
    assert len(ids) <= h.MAX_EXTRA_USERS


def test_collect_watcher_ids_empty_when_flags_off():
    ids = h.collect_watcher_ids(
        watch_assignee=False,
        assignee_username="assignee.user",
        extra_as_watchers=False,
        extra_mentions="a.rao",
        auto_watch_from_body=["c.pat"],
    )
    assert ids == []


# ---------------------------------------------------------------------------
# View-module thin wrappers still importable (Phase B compatibility)
# ---------------------------------------------------------------------------
def test_view_module_reexports_helpers():
    if "streamlit" not in sys.modules:
        _st = types.ModuleType("streamlit")
        _st.dialog = lambda *a, **k: lambda f: f
        _st.session_state = {}
        sys.modules["streamlit"] = _st
    import views.jira_action_dialog as dlg

    assert dlg._sk("42", "idem") == "jira_dlg_42_idem"
    assert dlg._safe_text("a[b]") == "ab"
    assert dlg._MAX_EXTRA_USERS == h.MAX_EXTRA_USERS
