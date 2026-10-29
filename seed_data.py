"""Optional library seed. Disabled unless ALLOW_SEED_DATA=true."""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import func, select

from database import Category, Project, Response, SessionLocal

logger = logging.getLogger(__name__)


def _seed_allowed() -> bool:
    return os.getenv("ALLOW_SEED_DATA", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def seed_if_empty() -> bool:
    """Seed projects/categories/responses only when allowed and DB is empty."""
    if not _seed_allowed():
        logger.info("Seed skipped (ALLOW_SEED_DATA is not true)")
        return False

    path = Path(__file__).parent / "data" / "seed_data.json"
    if not path.is_file():
        logger.info("No data/seed_data.json — nothing to seed")
        return False

    data = json.loads(path.read_text(encoding="utf-8"))
    projects = data.get("projects") or []
    if not projects:
        logger.info("seed_data.json is empty — nothing to seed")
        return False

    with SessionLocal() as db:
        if db.scalar(select(func.count(Project.id))):
            return False
        for pd in projects:
            p = Project(
                key=pd["key"],
                name=pd["name"],
                description=pd.get("description") or "",
                icon=pd.get("icon") or "📁",
                color=pd.get("color") or "#2563eb",
                sort_order=int(pd.get("sort_order") or 0),
            )
            db.add(p)
            db.flush()
            for cd in pd.get("categories") or []:
                c = Category(
                    project_id=p.id,
                    name=cd["name"],
                    sort_order=int(cd.get("sort_order") or 0),
                )
                db.add(c)
                db.flush()
                for rd in cd.get("responses") or []:
                    rid = "r_" + uuid.uuid4().hex[:16]
                    db.add(
                        Response(
                            id=rid,
                            category_id=c.id,
                            title=rd["title"],
                            badge=rd.get("badge"),
                            preview=rd.get("preview"),
                            response_body=rd["response_body"],
                            sort_order=int(rd.get("sort_order") or 0),
                        )
                    )
        db.commit()
        return True
