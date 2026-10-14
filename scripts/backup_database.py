"""PostgreSQL backup via pg_dump with retention cleanup.

The connection string is passed to pg_dump through the PGPASSWORD-free
``--dbname`` URI and is never printed or logged.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import BACKUP_DIR, BACKUP_RETENTION_DAYS, DATABASE_URL  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> str:
    if not DATABASE_URL.startswith("postgresql"):
        raise SystemExit("This script targets PostgreSQL. For SQLite, copy the .db file while the app is stopped.")
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise SystemExit("pg_dump is required for PostgreSQL backups.")

    target_dir = Path(BACKUP_DIR).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"jira_library_{stamp}.sql"
    uri = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)

    subprocess.run(
        [pg_dump, "--no-owner", "--no-privileges", "--clean", "-d", uri, "-f", str(target)],
        check=True, capture_output=True, text=True,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=BACKUP_RETENTION_DAYS)
    for item in target_dir.glob("jira_library_*.sql"):
        if datetime.fromtimestamp(item.stat().st_mtime, timezone.utc) < cutoff:
            item.unlink()
    sys.stdout.write(f"{target}\n")
    return str(target)


if __name__ == "__main__":
    main()
