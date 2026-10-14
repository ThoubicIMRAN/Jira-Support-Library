"""Test fixtures: every test runs against a throw-away SQLite database."""
import os
import secrets
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="jsl-tests-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_TMP}/test.db",
    APP_ENV="development",
    APP_SECRET_KEY=secrets.token_urlsafe(48),
    BOOTSTRAP_ADMIN_PASSWORD=secrets.token_urlsafe(18),
    TEST_PASSWORD=secrets.token_urlsafe(18),
    SESSION_TIMEOUT_MINUTES="0",
)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from database import init_db  # noqa: E402


PASSWORD = os.environ["TEST_PASSWORD"]
ADMIN_PASSWORD = os.environ["BOOTSTRAP_ADMIN_PASSWORD"]


def build_library():
    """Neutral fixture data created only inside the test database."""
    from database import Category, Project, Response, SessionLocal

    with SessionLocal() as db:
        for pi, (key, name) in enumerate((("ALPHA", "Alpha project"), ("BETA", "Beta project"), ("GAMMA", "Gamma project"))):
            project = Project(key=key, name=name, description=f"{name} (test)", icon="📁", color="#0c46ce", sort_order=pi)
            db.add(project); db.flush()
            for ci in range(2):
                cat = Category(project_id=project.id, name=f"{name} category {ci + 1}", sort_order=ci)
                db.add(cat); db.flush()
                for ri in range(3):
                    db.add(Response(id=f"t_{key}_{ci}_{ri}", category_id=cat.id, title=f"Response {ri + 1}",
                                    badge="TEST", preview="Preview", response_body=f"Hello @R,\n\nBody {ri + 1}\n\nBest regards,\n@NAME", sort_order=ri))
        db.commit()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    init_db()
    from auth import ensure_superadmin

    ensure_superadmin()
    build_library()
