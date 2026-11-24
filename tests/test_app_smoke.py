"""Render every page through Streamlit's AppTest as admin and as a plain user."""

import pytest
from conftest import ADMIN_PASSWORD, PASSWORD
from sqlalchemy import select
from streamlit.testing.v1 import AppTest

from auth import hash_password
from database import Project, SessionLocal, User

PAGES = [
    "home",
    "project",
    "workspace",
    "profile",
    "settings",
    "notifications",
    "admin",
    "security",
    "ai",
    "admin_settings",
]
APP = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py")


def _login(username, password):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].set_value(username)
    at.text_input[1].set_value(password)
    next(b for b in at.button if b.label == "Continue").click()
    return at.run()


@pytest.fixture(scope="module")
def project_id():
    with SessionLocal() as db:
        a = db.scalar(select(User).where(User.username == "admin"))
        a.must_change_password = False
        if not db.scalar(select(User).where(User.username == "bob")):
            db.add(
                User(
                    username="bob",
                    full_name="Bob",
                    role="user",
                    password_hash=hash_password(PASSWORD),
                    must_change_password=False,
                )
            )
        db.commit()
        return db.scalar(select(Project.id).order_by(Project.id))


def test_login_screen_renders():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and [t.label for t in at.text_input] == [
        "Email *",
        "Password *",
    ]


@pytest.mark.parametrize("who", [("admin", ADMIN_PASSWORD), ("bob", PASSWORD)])
def test_every_page_renders(who, project_id):
    at = _login(*who)
    for page in PAGES:
        at.session_state["page"], at.session_state["project_id"] = page, project_id
        at.run()
        assert not at.exception, (who[0], page, [e.value for e in at.exception])


def test_regular_user_cannot_open_admin_pages(project_id):
    at = _login("bob", PASSWORD)
    for page in ("admin", "security", "admin_settings"):
        at.session_state["page"] = page
        at.run()
        assert at.session_state["page"] == "home"


def test_signup_is_hidden_when_self_registration_is_off(monkeypatch):
    import views.login as login_view

    monkeypatch.setattr(login_view, "ALLOW_SELF_REGISTRATION", False)
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["mode"] = "signup"
    at.run()
    assert not at.exception
    assert any("Self-registration is turned off" in i.value for i in at.info)
    assert not [b for b in at.button if b.label == "Create account"]


def test_signup_creates_a_plain_user_when_enabled(monkeypatch):
    import views.login as login_view

    monkeypatch.setattr(login_view, "ALLOW_SELF_REGISTRATION", True)
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["mode"] = "signup"
    at.run()
    assert not at.exception
    labels = [t.label for t in at.text_input]
    assert labels == ["Email *", "Full name *", "Password *", "Confirm password *"]
    for box, value in zip(at.text_input, ["new.person@example.com", "New Person", PASSWORD, PASSWORD]):
        box.set_value(value)
    next(b for b in at.button if b.label == "Create account").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    with SessionLocal() as db:
        created = db.scalar(select(User).where(User.email == "new.person@example.com"))
    assert created is not None and created.role == "user"
