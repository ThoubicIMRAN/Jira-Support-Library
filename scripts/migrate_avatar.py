"""Add avatar_mime / avatar_data to users if missing."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from database import engine

SQL = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_mime VARCHAR(64)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data BYTEA",
]

def main():
    with engine.begin() as conn:
        for s in SQL:
            try:
                conn.execute(text(s))
                print("OK:", s)
            except Exception as exc:
                print("SKIP/ERR:", s, exc)

if __name__ == "__main__":
    main()
