"""Regression tests for the security audit and the Jira attachment HTTP 415 bug."""
import ast
import io
import re
import subprocess
from pathlib import Path

import pytest
import requests
from sqlalchemy import select

from conftest import PASSWORD
from database import AuditLog, Category, Project, Response, SessionLocal, User
from services import ai_service, content_service as cs, jira_service as js, rate_limit
from utils.errors import safe_message

ROOT = Path(__file__).resolve().parents[1]


def _user(name: str, role: str) -> int:
    from auth import hash_password

    with SessionLocal() as db:
        row = db.scalar(select(User).where(User.username == name))
        if not row:
            row = User(username=name, full_name=name, role=role, password_hash=hash_password(PASSWORD), must_change_password=False)
            db.add(row)
            db.commit()
            db.refresh(row)
        return row.id


# ------------------------------------------------------------------ HTTP 415 attachments
def test_attachment_upload_is_multipart_not_json(monkeypatch):
    """The session default Content-Type: application/json made Jira answer 415."""
    from services.jira_client import JiraClient

    seen = {}

    def fake_send(self, request, **kwargs):
        seen["content_type"] = request.headers.get("Content-Type", "")
        seen["token"] = request.headers.get("X-Atlassian-Token")
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b'[{"id": "1", "filename": "a.png"}]'
        return resp

    monkeypatch.setattr(requests.Session, "send", fake_send)
    client = JiraClient(base_url="https://jira.example.com", product="cloud", email="a@b.co", secret="token")
    out = client.add_attachment("PROJ-1", "a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    assert seen["content_type"].startswith("multipart/form-data; boundary=")
    assert seen["token"] == "no-check"
    assert out.get("id") == "1"


def test_json_requests_still_send_json(monkeypatch):
    from services.jira_client import JiraClient

    seen = {}

    def fake_send(self, request, **kwargs):
        seen["ct"] = request.headers.get("Content-Type")
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b"{}"
        return resp

    monkeypatch.setattr(requests.Session, "send", fake_send)
    client = JiraClient(base_url="https://jira.example.com", product="cloud", email="a@b.co", secret="token")
    client.add_worklog("PROJ-1", time_spent="15m")
    assert seen["ct"] == "application/json"


# ------------------------------------------------------------------ H2 authorisation in services
def test_privileged_account_functions_check_the_actor():
    from services import account_service as acc

    target = _user("audit_target", "user")
    actor = _user("audit_admin", "admin")
    for role in ("user", "manager", "admin", None):
        with pytest.raises(PermissionError):
            acc.admin_set_password(target, "Valid-Pass-123", actor, role)
        with pytest.raises(PermissionError):
            acc.delete_user(target, actor, role)
    for role in ("user", "manager"):
        with pytest.raises(PermissionError):
            acc.unlock_account("audit_target", role)
    assert acc.unlock_account("audit_target", "admin") >= 0


def test_avatar_actor_must_be_self_or_superadmin():
    from services.avatar_service import AvatarError, set_avatar

    victim = _user("audit_victim", "user")
    attacker = _user("audit_attacker", "admin")
    with pytest.raises(AvatarError):
        set_avatar(victim, _png(), "image/png", actor_id=attacker, actor_role="admin")


# ------------------------------------------------------------------ H3 rate limiting
RATE_LIMITED = {
    "services/jira_service.py": ["add_comment", "add_attachment", "log_work", "transition_issue", "add_watchers"],
    "services/bulk_comment.py": ["post_bulk_comment"],
    "services/account_service.py": ["admin_set_password", "delete_user"],
    "services/ai_service.py": ["generate_from_ticket"],
    "services/content_service.py": ["create_response", "update_response", "delete_response", "create_category", "import_project_payload"],
}


@pytest.mark.parametrize("path,names", RATE_LIMITED.items())
def test_every_sensitive_write_is_rate_limited(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in names:
        calls = [c.func.id for c in ast.walk(funcs[name]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        assert any(c.startswith("limit_") for c in calls), f"{path}:{name} has no rate limit"


def test_rate_limiter_blocks_and_is_user_safe(monkeypatch):
    monkeypatch.setattr(rate_limit, "_rate_limits_disabled", lambda: False)
    rate_limit.clear_rate_limit("admin:424242")
    for _ in range(30):
        rate_limit.limit_admin_action(424242)
    with pytest.raises(rate_limit.RateLimitExceeded) as exc:
        rate_limit.limit_admin_action(424242)
    assert isinstance(exc.value, ValueError) and "Too many" in safe_message(exc.value)
    rate_limit.clear_rate_limit("admin:424242")


# ------------------------------------------------------------------ M1 avatar validation
def _png(w=300, h=200) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 80, 200)).save(buf, format="PNG")
    return buf.getvalue()


def test_avatar_is_reencoded_to_a_small_square_png():
    from PIL import Image

    from services.avatar_service import get_avatar, set_avatar

    uid = _user("audit_avatar", "user")
    set_avatar(uid, _png(), "image/jpeg", actor_id=uid, actor_role="user")   # wrong MIME is ignored
    data, mime = get_avatar(uid)
    img = Image.open(io.BytesIO(data))
    assert mime == "image/png" and img.format == "PNG" and img.size == (256, 256)


@pytest.mark.parametrize("payload", [b"GIF89a" + b"0" * 40, b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", b"not an image", b"\x89PNG\r\n\x1a\n broken"])
def test_avatar_rejects_non_images_even_with_an_image_mime(payload):
    from services.avatar_service import AvatarError, set_avatar

    uid = _user("audit_avatar2", "user")
    with pytest.raises(AvatarError):
        set_avatar(uid, payload, "image/png", actor_id=uid, actor_role="user")


# ------------------------------------------------------------------ M4 JQL
def test_jql_literals_are_escaped_and_identifiers_validated(monkeypatch):
    seen = {}

    class FakeClient:
        def search_issues(self, jql, max_results=5):
            seen["jql"] = jql
            return []

    monkeypatch.setattr(js, "get_client_for_user", lambda uid: FakeClient())
    js.find_similar_open_issues(1, {"key": "PROJ-5", "project_key": "PROJ", "summary": 'login a\\b"c broken'})
    assert '\\"' in seen["jql"] and "\\\\" in seen["jql"]
    seen.clear()
    assert js.find_similar_open_issues(1, {"key": "PROJ-5", "project_key": 'X" OR "1"="1', "summary": "long summary words"}) == []
    assert "jql" not in seen


# ------------------------------------------------------------------ M5 embeddings
def test_one_ticket_load_cannot_trigger_unbounded_embedding_calls(monkeypatch):
    from services import similarity_search as ss

    with SessionLocal() as db:
        p = Project(key="EMBT", name="Embed test", description="", icon="x", color="#000000", sort_order=99)
        db.add(p)
        db.flush()
        c = Category(project_id=p.id, name="Embed cat", sort_order=0)
        db.add(c)
        db.flush()
        for i in range(30):
            db.add(Response(id=f"emb_{i}", category_id=c.id, title=f"R{i}", response_body=f"body {i}", sort_order=i))
        db.commit()
        pid = p.id
    calls = {"n": 0}
    monkeypatch.setattr(ai_service, "embed", lambda text: [1.0, 0.0])

    def counting(db, resp):
        calls["n"] += 1
        return [1.0, 0.0]

    monkeypatch.setattr(ai_service, "ensure_embedding", counting)
    ss.find_top_matches(pid, "query", limit=3, threshold=0.0)
    assert calls["n"] <= ss.MAX_NEW_EMBEDDINGS


# ------------------------------------------------------------------ M7 audit
def test_category_creation_is_audited():
    uid = _user("audit_cat_admin", "admin")
    with SessionLocal() as db:
        pid = db.scalar(select(Project.id).order_by(Project.id))
    cid = cs.create_category(uid, "admin", pid, "Audited category")
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.entity_type == "category", AuditLog.entity_id == str(cid)))
    assert row is not None and row.action == "create"


# ------------------------------------------------------------------ M2/M3 error handling
def test_safe_message_hides_unexpected_errors_and_keeps_validation_errors():
    assert safe_message(ValueError("Title is required.")) == "Title is required."
    shown = safe_message(RuntimeError("secret internal detail https://jira.corp/x"))
    assert "secret" not in shown and "ref " in shown


def test_no_silent_except_pass_and_no_raw_exception_text_in_ui():
    offenders = []
    for folder in ("views", "services", "components"):
        for path in (ROOT / folder).rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} except/pass")
            for i, line in enumerate(src.splitlines(), 1):
                if re.search(r"st\.(error|warning)\(str\((exc|e)\)\)|st\.(error|warning)\(f[\"'].*\{(exc|e)\}", line):
                    offenders.append(f"{path.relative_to(ROOT)}:{i} raw exception text")
    assert not offenders, offenders


# ------------------------------------------------------------------ B1/B3/B5 repository hygiene
def test_every_module_imports():
    """A module referenced but missing (or a broken import) must fail CI, not fail silently at runtime."""
    import importlib

    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    failed = []
    for f in files:
        if f.startswith(("alembic/", "tests/", "scripts/")) or f == "app.py":
            continue
        try:
            importlib.import_module(f[:-3].replace("/", "."))
        except Exception as exc:  # noqa: BLE001
            failed.append((f, type(exc).__name__, str(exc)[:80]))
    assert not failed, failed


def test_lazy_service_imports_point_to_real_modules():
    missing = set()
    for path in list((ROOT / "views").rglob("*.py")) + list((ROOT / "services").rglob("*.py")):
        for m in re.finditer(r"from services\.([a-z_]+) import", path.read_text(encoding="utf-8")):
            if not (ROOT / "services" / f"{m.group(1)}.py").exists():
                missing.add(f"{path.relative_to(ROOT)} -> services/{m.group(1)}.py")
    assert not missing, missing


def test_no_patch_scripts_or_encoded_code_blobs_are_committed():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in files if re.search(r"(APPLY|SYNC|PATCH)[A-Za-z_]*\.py$", f)]
    assert not [f for f in files if f in ("ci-docker.yml", "dependabot.yml")], "workflow files belong in .github/"
    for f in files:
        if f.endswith(".py"):
            assert not re.search(r"[A-Za-z0-9+/=]{1500,}", (ROOT / f).read_text(encoding="utf-8")), f"encoded blob in {f}"
