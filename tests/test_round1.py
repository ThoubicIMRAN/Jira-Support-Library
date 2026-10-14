"""Round 1: bulk comment safety, placeholders, Confluence host lock, attachments, project access."""
from conftest import PASSWORD
import pytest
from sqlalchemy import select

from auth import hash_password
from database import BulkPostLog, Category, Project, SessionLocal, User, UserProjectAccess
from services import bulk_comment as bc
from services import jira_service as js
from services.jira_client import JiraError
from utils.personalization import personalize, unresolved_placeholders


@pytest.fixture(scope="module")
def uid():
    with SessionLocal() as db:
        row = db.scalar(select(User).where(User.username == "r1_user"))
        if not row:
            row = User(username="r1_user", full_name="Rita One", designation="Engineer", role="manager",
                       password_hash=hash_password(PASSWORD), must_change_password=False)
            db.add(row); db.commit(); db.refresh(row)
        return row.id


# ---------- B2 placeholders ----------
def test_ticket_placeholders_are_filled():
    out = personalize("Re @TICKET (@SUMMARY) for @R by @NAME", type("U", (), {"full_name": "Rita", "role": "user"})(), None,
                      recipient="Asha", context={"TICKET": "SIT-9", "SUMMARY": "VPN down"})
    assert out == "Re SIT-9 (VPN down) for Asha by Rita"


def test_unset_ticket_placeholders_stay_visible():
    out = personalize("Ticket @TICKET assigned to @ASSIGNEE", type("U", (), {})(), None)
    assert "@TICKET" in out and unresolved_placeholders(out) == ["ASSIGNEE", "TICKET"]


def test_placeholder_does_not_eat_longer_words():
    assert personalize("@RESOLUTION @ROLEPLAY", type("U", (), {})(), None) == "@RESOLUTION @ROLEPLAY"


# ---------- B4 + S2/S3 bulk ----------
@pytest.fixture
def fake_jira(monkeypatch):
    calls = []

    def add_comment(user_id, key, body, *, internal=False):
        calls.append((key, body))
        if key.endswith("-3"):
            raise JiraError("Jira API 404: not found", status=404)
        if key.endswith("-4"):
            raise RuntimeError("secret internal detail")

    monkeypatch.setattr(js, "add_comment", add_comment)
    monkeypatch.setattr(js, "log_work", lambda *a, **k: "15m")
    monkeypatch.setattr(js, "load_issue", lambda uid, key: {"reporter": "Asha", "summary": "S", "assignee": "Bob", "status": "Open"})
    return calls


def test_parse_keys_dedupes_and_reads_urls():
    assert bc.parse_keys("sit-1, SIT-2\nhttps://x.net/browse/sit-1 SIT-3") == ["SIT-1", "SIT-2", "SIT-3"]


def test_cap_and_project_rules(uid, fake_jira):
    with pytest.raises(bc.BulkError):
        bc.post_bulk_comment(uid, [f"SIT-{i}" for i in range(1, 30)], "x", delay=0)
    with pytest.raises(bc.BulkError):
        bc.post_bulk_comment(uid, ["SIT-1", "ABC-2"], "x", delay=0)
    with pytest.raises(bc.BulkError):
        bc.post_bulk_comment(uid, ["ABC-1"], "x", required_prefix="SIT", delay=0)
    with pytest.raises(bc.BulkError):
        bc.post_bulk_comment(uid, ["SIT-1"], "   ", delay=0)
    assert fake_jira == []  # nothing was posted for any rejected request


def test_partial_failure_is_reported_without_leaking_details(uid, fake_jira):
    result = bc.post_bulk_comment(uid, ["SIT-1", "SIT-2", "SIT-3", "SIT-4"], "Hi @R re @TICKET", delay=0)
    assert result["ok"] == ["SIT-1", "SIT-2"]
    failed = dict(result["failed"])
    assert "404" in failed["SIT-3"] and "secret" not in failed["SIT-4"]
    assert ("SIT-1", "Hi Asha re SIT-1") in fake_jira


def test_reporter_swap_loads_each_ticket(uid, fake_jira):
    bc.post_bulk_comment(uid, ["SIT-1"], "Hello @R", delay=0)
    assert ("SIT-1", "Hello Asha") in fake_jira


def test_auth_failure_aborts_the_rest(uid, monkeypatch):
    seen = []
    def deny(user_id, key, body, *, internal=False):
        seen.append(key); raise JiraError("Jira API 401", status=401)
    monkeypatch.setattr(js, "add_comment", deny)
    result = bc.post_bulk_comment(uid, ["SIT-1", "SIT-2", "SIT-3"], "x", delay=0)
    assert seen == ["SIT-1"] and len(result["failed"]) == 3


def test_every_run_is_logged(uid, fake_jira):
    result = bc.post_bulk_comment(uid, ["SIT-1", "SIT-2"], "log me", delay=0)
    mine = bc.list_bulk_logs(uid)
    assert mine[0]["id"] == result["log_id"] and mine[0]["ok"] == 2 and mine[0]["user"] == "r1_user"
    assert any(l["id"] == result["log_id"] for l in bc.list_bulk_logs(None))
    with SessionLocal() as db:
        assert db.get(BulkPostLog, result["log_id"]).body_preview == "log me"


# ---------- S1 Confluence host lock ----------
def test_confluence_never_uses_a_pasted_host(uid, monkeypatch):
    from services import confluence_service as cs
    monkeypatch.setattr(cs, "CONFLUENCE_BASE_URL", "https://wiki.corp.example")
    with pytest.raises(cs.ConfluenceError, match="not on the configured"):
        cs.resolve_auth(uid, page_url="https://evil.example/pages/viewpage.action?pageId=1")
    monkeypatch.setattr(cs, "CONFLUENCE_BASE_URL", "")
    with pytest.raises(cs.ConfluenceError, match="not configured"):
        cs.resolve_auth(uid, page_url="https://evil.example/x")


# ---------- S4 attachments ----------
def test_attachment_validation():
    assert js.validate_attachment("shot.png", b"\x89PNG\r\n" + b"0" * 10) == "shot.png"
    assert js.validate_attachment("../../etc/notes.txt", b"hello") == "notes.txt"
    for name, data in (("run.exe", b"MZ"), ("a.png", b"not a png"), ("big.pdf", b"%PDF" + b"0" * (11 * 1024 * 1024)),
                       ("empty.txt", b""), ("bin.log", b"ab\x00cd")):
        with pytest.raises(ValueError):
            js.validate_attachment(name, data)


# ---------- project access ----------
def _first_project_category():
    with SessionLocal() as db:
        projects = db.scalars(select(Project).order_by(Project.id)).all()
        p1 = projects[0]; p2 = next(p for p in projects[1:] if db.scalar(select(Category.id).where(Category.project_id == p.id)))
        return p1.id, db.scalar(select(Category.id).where(Category.project_id == p2.id)), p2.id


def test_restricted_roles_only_touch_assigned_projects(uid):
    from services import content_service as cs, project_access as pa, workspace_service as ws
    _, cat_other, other_project = _first_project_category()
    with SessionLocal() as db:
        for row in db.scalars(select(UserProjectAccess).where(UserProjectAccess.user_id == uid)).all():
            db.delete(row)
        db.commit()
    assert pa.visible_project_ids(uid, "manager") == set()
    with pytest.raises(cs.ContentError, match="access"):
        cs.create_response(uid, "manager", cat_other, "t", "", "", "body")      # no assignment -> blocked server-side
    pa.set_user_projects(uid, [other_project])
    assert cs.create_response(uid, "manager", cat_other, "t", "", "", "body")  # assigned -> allowed
    assert pa.visible_project_ids(uid, "admin") is None                        # admins unrestricted

    viewer = type("V", (), {"id": uid})()
    assert all(r.category.project_id == other_project for r in ws.global_search("", None, None, None, 200, viewer=viewer))
    pa.set_user_projects(uid, [])
    assert ws.global_search("", None, None, None, 200, viewer=viewer) == []
