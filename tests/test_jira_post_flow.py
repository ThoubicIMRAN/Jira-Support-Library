"""Jira dialog actions: idempotent comments, retry-safe steps, safe errors, file checks."""
import types

import pytest
from sqlalchemy import select

from conftest import PASSWORD
from database import AuditLog, SessionLocal, User
from services import jira_post_flow as flow
from services import jira_service as js
from services.jira_client import JiraError


class FakeClient:
    """Records calls; ``fail`` maps a method name to an exception to raise (once if listed in ``once``)."""

    def __init__(self, fail=None, once=()):
        self.calls, self.fail, self.once = [], fail or {}, set(once)

    def _go(self, name, *args, **kw):
        self.calls.append((name, args, kw))
        exc = self.fail.get(name)
        if exc is not None:
            if name in self.once:
                self.fail.pop(name)
            raise exc
        return {}

    def add_comment(self, key, body, *a, **k): return self._go("add_comment", key, body, **k)
    def add_watcher(self, key, ident): return self._go("add_watcher", key, ident)
    def add_attachment(self, key, name, data, mime=None): return self._go("add_attachment", key, name)
    def add_worklog(self, key, **k): return self._go("add_worklog", key, **k)
    def do_transition(self, key, tid): return self._go("do_transition", key, tid)
    def list_transitions(self, key): return [{"id": "11", "name": "To Do"}, {"id": "21", "name": "Doing"}, {"id": "31", "name": "Done"}]

    def names(self): return [c[0] for c in self.calls]


@pytest.fixture
def uid():
    from auth import hash_password

    with SessionLocal() as db:
        row = db.scalar(select(User).where(User.username == "flow_user"))
        if not row:
            row = User(username="flow_user", full_name="Flow", role="user", password_hash=hash_password(PASSWORD), must_change_password=False)
            db.add(row)
            db.commit()
            db.refresh(row)
        return row.id


def _use(monkeypatch, client):
    monkeypatch.setattr(js, "get_client_for_user", lambda user_id: client)
    js._RECENT_COMMENTS.clear()


def _run(uid, done, **kw):
    base = dict(comment="Hello", internal=False, idempotency_key="k1", done=done)
    base.update(kw)
    return flow.run_post_steps(uid, "PROJ-1", **base)


# --------------------------------------------------------------------- add_comment idempotency
def test_add_comment_accepts_an_idempotency_key_and_posts_once(uid, monkeypatch):
    client = FakeClient()
    _use(monkeypatch, client)
    assert js.add_comment(uid, "PROJ-1", "Hi", idempotency_key="abc") is True
    assert js.add_comment(uid, "PROJ-1", "Hi", idempotency_key="abc") is False       # duplicate click
    assert client.names().count("add_comment") == 1
    assert js.add_comment(uid, "PROJ-1", "Hi", idempotency_key="other") is True       # new key posts


def test_a_failed_comment_can_be_retried_with_the_same_key(uid, monkeypatch):
    client = FakeClient(fail={"add_comment": JiraError("boom")}, once={"add_comment"})
    _use(monkeypatch, client)
    with pytest.raises(JiraError):
        js.add_comment(uid, "PROJ-1", "Hi", idempotency_key="retry")
    assert js.add_comment(uid, "PROJ-1", "Hi", idempotency_key="retry") is True       # key was not burned
    assert client.names().count("add_comment") == 2


def test_comment_without_key_is_never_deduplicated(uid, monkeypatch):
    client = FakeClient()
    _use(monkeypatch, client)
    js.add_comment(uid, "PROJ-1", "same")
    js.add_comment(uid, "PROJ-1", "same")
    assert client.names().count("add_comment") == 2


# --------------------------------------------------------------------- step runner
def test_all_steps_run_in_a_fixed_order(uid, monkeypatch):
    client = FakeClient()
    _use(monkeypatch, client)
    out = _run(uid, set(), watchers=["a.rao", "@b.lee"], files=[("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image/png")], time_raw="15m",
               chain=[("11", "To Do"), ("21", "Doing")])
    assert out.ok and not out.errors
    assert client.names() == ["add_comment", "add_watcher", "add_watcher", "add_attachment", "add_worklog",
                              "do_transition", "do_transition"]


def test_partial_failure_retry_does_not_repeat_finished_steps(uid, monkeypatch):
    client = FakeClient(fail={"add_worklog": JiraError("Time tracking is disabled")}, once={"add_worklog"})
    _use(monkeypatch, client)
    done = set()
    first = _run(uid, done, time_raw="15m", chain=[("11", "To Do")])
    assert any("Time" in e for e in first.errors) and "comment" in done and "time" not in done
    second = _run(uid, done, time_raw="15m", chain=[("11", "To Do")])
    assert not second.errors
    assert client.names().count("add_comment") == 1            # no second comment
    assert client.names().count("add_worklog") == 2            # only the failed step retried
    assert client.names().count("do_transition") == 1          # transition ran once, not twice


def test_status_chain_stops_at_the_first_failure_and_resumes_there(uid, monkeypatch):
    client = FakeClient(fail={"do_transition": JiraError("not allowed")}, once={"do_transition"})
    _use(monkeypatch, client)
    done = set()
    chain = [("11", "To Do"), ("21", "Doing"), ("31", "Done")]
    first = _run(uid, done, chain=chain)
    assert len(first.errors) == 1 and client.names().count("do_transition") == 1   # stopped at step 1
    second = _run(uid, done, chain=chain)
    assert not second.errors
    assert client.names().count("do_transition") == 4          # 1 failed + 3 successful, none repeated
    assert {"transition:0:11", "transition:1:21", "transition:2:31"} <= done


def test_unexpected_errors_never_leak_internal_details(uid, monkeypatch):
    client = FakeClient(fail={"add_comment": RuntimeError("secret https://jira.corp.example token=abc")})
    _use(monkeypatch, client)
    out = _run(uid, set())
    joined = " ".join(out.errors)
    assert out.errors and "secret" not in joined and "token=abc" not in joined


def test_jira_validation_messages_are_shown_to_the_user(uid, monkeypatch):
    client = FakeClient(fail={"add_comment": JiraError("Jira API 403: no permission to comment")})
    _use(monkeypatch, client)
    out = _run(uid, set())
    assert any("403" in e for e in out.errors)


# --------------------------------------------------------------------- resolution notes
def test_draft_resolution_notes_honours_use_ai(monkeypatch):
    from services import ai_service, resolution_notes_service as rn

    monkeypatch.setattr(rn, "fetch_page_for_user", lambda uid, url: {"title": "VPN fix", "excerpt": "Reset the profile.", "link": "https://wiki.example/x"})

    def boom():
        raise AssertionError("AI must not be contacted when use_ai=False")

    monkeypatch.setattr(ai_service, "ollama_available", boom)
    text = rn.draft_resolution_notes(user_id=1, confluence_url="https://wiki.example/x", ticket_key="PROJ-1", ticket_summary="VPN", use_ai=False)
    assert "https://wiki.example/x" in text


# --------------------------------------------------------------------- dialog helpers
def _upload(name, data, mime):
    return types.SimpleNamespace(name=name, type=mime, getvalue=lambda: data)


def test_prepare_files_accepts_good_files_and_reports_bad_ones():
    from views.jira_action_dialog import _prepare_files

    files, problems = _prepare_files([_upload("ok.png", b"x" * 10, "image/png"), _upload("bad.exe", b"MZ", "application/x-msdownload"),
                                      _upload("big.pdf", b"x" * (11 * 1024 * 1024), "application/pdf")], "", "PROJ-1")
    assert [f[0] for f in files] == ["ok.png"]
    assert len(problems) == 2 and any("exe" in p for p in problems) and any("larger" in p for p in problems)


def test_prepare_files_rejects_non_image_paste():
    from views.jira_action_dialog import _prepare_files

    assert _prepare_files([], "data:image/svg+xml;base64,AAAA", "PROJ-1")[1]
    assert _prepare_files([], "data:image/png;base64,@@not-base64@@", "PROJ-1")[1]


def test_dialog_has_no_bulk_posting_and_never_calls_rerun():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "views" / "jira_action_dialog.py").read_text(encoding="utf-8")
    assert "bulk" not in src.lower(), "bulk posting belongs on the project page, not in the single-ticket dialog"
    reruns = [n.lineno for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "rerun"]
    assert not reruns, f"st.rerun() inside a dialog closes it (lines {reruns})"
    assert 'width="medium"' in src


def test_failed_steps_are_not_marked_with_a_tick(uid, monkeypatch):
    _use(monkeypatch, FakeClient(fail={"add_worklog": JiraError("no time tracking")}))
    out = _run(uid, set(), time_raw="15m")
    assert any(r.startswith("✔ Comment") for r in out.results)
    assert out.errors and all(not e.startswith("✔") for e in out.errors)


def test_settings_page_no_longer_references_a_missing_module():
    from pathlib import Path

    assert "snipeit" not in (Path(__file__).resolve().parents[1] / "views" / "settings.py").read_text(encoding="utf-8").lower()


def test_audit_trail_records_the_posted_comment(uid, monkeypatch):
    client = FakeClient()
    _use(monkeypatch, client)
    js.add_comment(uid, "AUD-1", "audited body", idempotency_key="aud")
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.entity_id == "AUD-1", AuditLog.action == "jira_comment"))
    assert row is not None
