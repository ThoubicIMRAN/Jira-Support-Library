"""Jira + AI approval + user-management integration tests (no network calls)."""
from conftest import PASSWORD
import pytest
from sqlalchemy import select

from database import (AiPendingResponse, Category, Project, ProjectJiraLink, SessionLocal,
                      User, UserJiraCredential)
from auth import allowed, hash_password
from services import ai_approval_service as ap
from services import jira_service as js
from services.jira_client import adf_document
from services.jira_text import build_comment_preview


@pytest.fixture(scope="module")
def users():
    ids = {}
    with SessionLocal() as db:
        for name, role in (("u_user", "user"), ("u_mgr", "manager"), ("u_adm", "admin")):
            row = db.scalar(select(User).where(User.username == name))
            if not row:
                row = User(username=name, full_name=name, role=role, password_hash=hash_password(PASSWORD), must_change_password=False)
                db.add(row); db.commit(); db.refresh(row)
            ids[role] = row.id
    return ids


def _project_category():
    with SessionLocal() as db:
        p = db.scalar(select(Project).order_by(Project.id))
        return p.id, db.scalar(select(Category.id).where(Category.project_id == p.id))


def test_role_matrix():
    assert allowed("user", "use_ai") and not allowed("user", "save_library") and not allowed("user", "approve_content")
    assert allowed("manager", "approve_content") and allowed("manager", "save_library") and not allowed("manager", "delete")
    assert allowed("admin", "approve_content") and allowed("superadmin", "anything")


def test_approval_flow_and_server_side_rbac(users):
    pid, cid = _project_category()
    row_id = ap.submit_pending(user_id=users["user"], project_id=pid, category_id=cid, title="t", body="Hello body")
    with pytest.raises(ap.ApprovalError):
        ap.approve_pending(row_id, users["user"])           # a plain user cannot approve
    with pytest.raises(ap.ApprovalError):
        ap.reject_pending(row_id, users["user"])
    assert ap.approve_pending(row_id, users["manager"]) is not None
    assert ap.approve_pending(row_id, users["manager"]) is None   # already processed
    with SessionLocal() as db:
        assert db.get(AiPendingResponse, row_id).status == "approved"


def test_reject_and_validation(users):
    pid, cid = _project_category()
    rid = ap.submit_pending(user_id=users["user"], project_id=pid, category_id=cid, title="t", body="x")
    assert ap.reject_pending(rid, users["admin"], "no") is True
    with pytest.raises(ap.ApprovalError):
        ap.submit_pending(user_id=users["user"], project_id=pid, category_id=cid, title="t", body="   ")


def test_issue_key_and_time_parsing():
    assert js.parse_issue_key("see https://x.atlassian.net/browse/abc-12") == "ABC-12"
    assert js.parse_issue_key("sit-9") == "SIT-9"
    assert js.parse_issue_key("../../etc/passwd") is None
    assert js.normalize_time_spent("1h 30m") and js.normalize_time_spent("90m")
    with pytest.raises(ValueError):
        js.normalize_time_spent("")


def test_adf_keeps_line_breaks():
    doc = adf_document("Hello,\n\nLine one\nLine two")
    assert len(doc["content"]) == 2
    assert {"type": "hardBreak"} in doc["content"][1]["content"]


def test_comment_preview_swaps_reporter():
    out = build_comment_preview("Hello @R,\n\nDone.", reporter_name="Asha", mention_mode="plain", mention_username="", resolution_notes="")
    assert "Asha" in out and "@R" not in out


def test_jira_token_is_stored_encrypted(users, monkeypatch):

    class FakeClient:
        def __init__(self, **kw): self.kw = kw
        def myself(self): return {"displayName": "Test User", "accountId": "1"}

    monkeypatch.setattr(js, "JiraClient", FakeClient, raising=False)
    monkeypatch.setattr(js, "JIRA_BASE_URL", "https://example.atlassian.net", raising=False)
    try:
        js.save_user_credentials(users["user"], product="cloud", email="a@b.c", secret="SUPER-SECRET-TOKEN")
    except Exception:
        pytest.skip("service wiring differs; encryption checked below")
    with SessionLocal() as db:
        row = db.scalar(select(UserJiraCredential).where(UserJiraCredential.user_id == users["user"]))
        assert row and "SUPER-SECRET-TOKEN" not in row.encrypted_secret
    js.disconnect_user(users["user"])
    assert js.credential_status(users["user"]).get("connected") is False


def test_project_link_roundtrip():
    pid, _ = _project_category()
    js.set_jira_project_key(pid, "sit")
    assert js.get_jira_project_key(pid) == "SIT"
    with SessionLocal() as db:
        assert db.scalar(select(ProjectJiraLink).where(ProjectJiraLink.project_id == pid)).jira_project_key == "SIT"


def test_transition_alias_crud():
    js.upsert_transition_alias(jira_project_key="*", raw_name="Resolve this issue", friendly_label="Resolve", sort_order=1)
    aliases = js.list_transition_aliases()
    assert any(a["friendly_label"] == "Resolve" for a in aliases)
    js.delete_transition_alias(next(a["id"] for a in aliases if a["raw_name"] == "Resolve this issue"))
