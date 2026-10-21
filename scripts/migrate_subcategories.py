"""Add categories.parent_id if missing (safe for existing data)."""
from __future__ import annotations

from sqlalchemy import inspect, text

from database import engine


def migrate() -> None:
    insp = inspect(engine)
    if "categories" not in insp.get_table_names():
        print("No categories table yet — create_all will handle it.")
        return
    cols = {c["name"] for c in insp.get_columns("categories")}
    if "parent_id" in cols:
        print("parent_id already present")
        return
    with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            conn.execute(text(
                "ALTER TABLE categories ADD COLUMN parent_id INTEGER "
                "REFERENCES categories(id) ON DELETE CASCADE"
            ))
        else:
            conn.execute(text(
                "ALTER TABLE categories ADD COLUMN parent_id INTEGER NULL "
                "REFERENCES categories(id) ON DELETE CASCADE"
            ))
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_categories_parent_id ON categories (parent_id)"
                ))
            except Exception:
                pass
    print("OK: added categories.parent_id (existing rows = top-level categories)")


if __name__ == "__main__":
    migrate()
