import sys

from sqlalchemy import func, select, text

from database import Project, SessionLocal, User, engine, init_db


def main():
    init_db()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    with SessionLocal() as db:
        projects = db.scalar(select(func.count(Project.id))) or 0
        users = db.scalar(select(func.count(User.id))) or 0
    print({"database": "ok", "projects": projects, "users": users})
    return 0 if projects and users else 1


if __name__ == "__main__":
    sys.exit(main())
