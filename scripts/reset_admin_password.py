"""Reset admin password from BOOTSTRAP_ADMIN_PASSWORD (or argv).

Usage (Docker):
  docker compose exec app python scripts/reset_admin_password.py
  docker compose exec app python scripts/reset_admin_password.py 'YourNewPass1!'
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from auth import hash_password  # noqa: E402
from database import SessionLocal, User, init_db  # noqa: E402


def main() -> None:
    init_db()
    password = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    password = password or os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if not password:
        print("Provide a password as argument or set BOOTSTRAP_ADMIN_PASSWORD")
        sys.exit(1)

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            admin = User(
                username="admin",
                full_name="System Administrator",
                designation="Administrator",
                role="superadmin",
                is_active=True,
            )
            db.add(admin)
        admin.password_hash = hash_password(password)
        admin.must_change_password = True
        admin.is_active = True
        db.commit()
    print("OK — username=admin password updated. must_change_password=True")


if __name__ == "__main__":
    main()
