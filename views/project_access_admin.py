"""Project access: assign library projects to users and managers (admins see everything).

Two ways to work: by user (pick a person, choose their projects, or copy another user's access)
and by project (pick a project, choose which people can open it).
"""

from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from auth import allowed
from database import Project, SessionLocal, User
from services import project_access
from services.audit_service import record as audit

ASSIGNABLE_ROLES = ("user", "manager")
MODE_USER, MODE_PROJECT = "By user", "By project"


def render_project_access_admin(user) -> None:
    if not allowed(user.role, "manage_access"):
        st.warning("Admin access required.")
        return

    st.subheader("Project access")
    st.caption(
        "Users and managers only see the projects assigned here; with none assigned their library is empty. "
        "Admins and superadmins always see all projects."
    )

    people, projects = _load_people_and_projects()
    if not people:
        st.info("There are no active users or managers to assign.")
        return
    if not projects:
        st.info("No projects yet. Add one under Projects first.")
        return

    flash = st.session_state.pop("access_flash", None)  # set by button callbacks
    if flash:
        st.success(flash)

    mode = (
        st.segmented_control(
            "Manage access",
            [MODE_USER, MODE_PROJECT],
            default=MODE_USER,
            key="access_mode",
            label_visibility="collapsed",
        )
        or MODE_USER
    )
    (_by_project if mode == MODE_PROJECT else _by_user)(user, people, projects)


def _load_people_and_projects() -> tuple[dict[int, str], dict[int, str]]:
    with SessionLocal() as db:
        people = {
            u.id: f"{u.username} ({u.role})"
            for u in db.scalars(
                select(User)
                .where(User.is_active.is_(True), User.role.in_(ASSIGNABLE_ROLES))
                .order_by(User.username)
            )
        }
        projects = {
            p.id: p.name
            for p in db.scalars(
                select(Project)
                .where(Project.is_deleted.is_(False))
                .order_by(Project.sort_order, Project.id)
            )
        }
    return people, projects


def _save(
    actor_id: int, person_id: int, project_ids: list[int], people: dict, projects: dict
) -> None:
    """Replace one user's assignments and write the audit row."""
    project_access.set_user_projects(person_id, project_ids)
    names = ", ".join(projects.get(p, str(p)) for p in project_ids) or "none"
    with SessionLocal() as db:
        audit(
            db,
            actor_id,
            "assign",
            "project_access",
            person_id,
            f"{people.get(person_id, person_id)}: {names}",
        )
        db.commit()


# ----------------------------------------------------------------------------- by user
def _copy_access(
    actor_id: int, person_id: int, source_id: int, people: dict, projects: dict
) -> None:
    """Button callback: runs before the rerun, so it may set the multiselect's state."""
    ids = [
        p
        for p in sorted(project_access.assigned_project_ids(source_id))
        if p in projects
    ]
    _save(actor_id, person_id, ids, people, projects)
    st.session_state[f"access_projects_{person_id}"] = ids
    st.session_state["access_flash"] = (
        f"Copied {len(ids)} project(s) from {people[source_id]} to {people[person_id]}."
    )


def _by_user(user, people: dict, projects: dict) -> None:
    # Options are plain ids, not ORM objects: object reprs change on every rerun and reset the widget.
    person_id = st.selectbox(
        "User", list(people), format_func=people.get, key="access_user"
    )
    current = [
        p
        for p in sorted(project_access.assigned_project_ids(person_id))
        if p in projects
    ]
    selected = st.multiselect(
        "Assigned projects",
        list(projects),
        default=current,
        format_func=projects.get,
        key=f"access_projects_{person_id}",
    )
    if st.button("Save assignments", type="primary", key="access_save"):
        _save(user.id, person_id, selected, people, projects)
        st.success(
            f"Saved. {people[person_id]} can now see {len(selected)} project(s)."
        )

    others = {pid: name for pid, name in people.items() if pid != person_id}
    if others:
        with st.expander(
            "Copy access from another user", icon=":material/content_copy:"
        ):
            st.caption(
                "Replaces this user's assignments with the other user's. Useful when onboarding someone to the same team."
            )
            source_id = st.selectbox(
                "Copy from",
                list(others),
                format_func=others.get,
                key=f"access_src_{person_id}",
            )
            st.button(
                "Replace with their access",
                key=f"access_copy_{person_id}",
                on_click=_copy_access,
                args=(user.id, person_id, source_id, people, projects),
            )


# ----------------------------------------------------------------------------- by project
def _by_project(user, people: dict, projects: dict) -> None:
    project_id = st.selectbox(
        "Project", list(projects), format_func=projects.get, key="access_project"
    )
    assigned = {uid: set(project_access.assigned_project_ids(uid)) for uid in people}
    current = [uid for uid, ids in assigned.items() if project_id in ids]
    selected = st.multiselect(
        "People with access",
        list(people),
        default=current,
        format_func=people.get,
        key=f"access_people_{project_id}",
    )
    st.caption(f"{len(selected)} of {len(people)} people selected.")

    if st.button("Save access", type="primary", key="access_project_save"):
        added, removed = set(selected) - set(current), set(current) - set(selected)
        for uid in added | removed:
            ids = set(assigned[uid])  # keeps their other assignments untouched
            ids.add(project_id) if uid in added else ids.discard(project_id)
            _save(user.id, uid, sorted(ids), people, projects)
        st.success(
            f"Saved. {len(added)} added, {len(removed)} removed for {projects[project_id]}."
        )
