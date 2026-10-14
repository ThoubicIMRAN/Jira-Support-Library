"""Project visibility: superadmin/admin see all; user/manager see assigned only."""
from __future__ import annotations

from sqlalchemy import select

from database import SessionLocal


def is_unrestricted(role: str) -> bool:
    return role in ("superadmin", "admin")


def assigned_project_ids(user_id: int) -> set[int]:
    from database import UserProjectAccess

    with SessionLocal() as db:
        return set(
            db.scalars(
                select(UserProjectAccess.project_id).where(
                    UserProjectAccess.user_id == user_id
                )
            ).all()
        )


def visible_project_ids(user_id: int, role: str) -> set[int] | None:
    """None means unrestricted (admin/superadmin); otherwise the assigned project ids."""
    return None if is_unrestricted(role) else assigned_project_ids(user_id)


def can_view_project(user, project_id: int) -> bool:
    if is_unrestricted(getattr(user, "role", "")):
        return True
    return int(project_id) in assigned_project_ids(user.id)


def filter_project_ids(user, project_ids: list[int]) -> list[int]:
    if is_unrestricted(getattr(user, "role", "")):
        return list(project_ids)
    allowed = assigned_project_ids(user.id)
    return [p for p in project_ids if p in allowed]


def set_user_projects(user_id: int, project_ids: list[int]) -> None:
    from database import UserProjectAccess

    with SessionLocal() as db:
        existing = list(
            db.scalars(
                select(UserProjectAccess).where(UserProjectAccess.user_id == user_id)
            ).all()
        )
        for row in existing:
            db.delete(row)
        for pid in project_ids:
            db.add(UserProjectAccess(user_id=user_id, project_id=int(pid)))
        db.commit()


def list_assignments() -> list[dict]:
    from database import Project, User, UserProjectAccess

    with SessionLocal() as db:
        rows = db.execute(
            select(UserProjectAccess.user_id, UserProjectAccess.project_id)
        ).all()
        users = {u.id: u for u in db.scalars(select(User)).all()}
        projects = {p.id: p for p in db.scalars(select(Project)).all()}
        out = []
        for uid, pid in rows:
            out.append(
                {
                    "user_id": uid,
                    "username": getattr(users.get(uid), "username", uid),
                    "project_id": pid,
                    "project": getattr(projects.get(pid), "name", pid),
                }
            )
        return out
