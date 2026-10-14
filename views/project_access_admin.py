"""Assign library projects to users (managers/users see only assigned)."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from database import Project, SessionLocal, User
from services import project_access


def render_project_access_admin(user) -> None:
    if user.role not in ("superadmin", "admin"):
        st.warning("Admin only.")
        return
    st.subheader("📁 Project access")
    st.caption("Users and managers only see projects assigned here. Admins and superadmins see all.")

    with SessionLocal() as db:
        users = list(
            db.scalars(
                select(User)
                .where(User.is_active.is_(True), User.role.in_(("user", "manager")))
                .order_by(User.username)
            ).all()
        )
        projects = list(
            db.scalars(
                select(Project)
                .where(Project.is_deleted == False)  # noqa: E712
                .order_by(Project.sort_order)
            ).all()
        )

    if not users:
        st.info("No users/managers to assign.")
        return
    if not projects:
        st.info("No projects yet.")
        return

    u = st.selectbox("User", users, format_func=lambda x: f"{x.username} ({x.role})")
    current = sorted(project_access.assigned_project_ids(u.id))
    selected = st.multiselect(
        "Assigned projects",
        options=[p.id for p in projects],
        default=[i for i in current if i in {p.id for p in projects}],
        format_func=lambda pid: next(p.name for p in projects if p.id == pid),
    )
    if st.button("Save assignments", type="primary"):
        project_access.set_user_projects(u.id, selected)
        st.success("Saved.")
