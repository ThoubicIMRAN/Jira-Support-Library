"""Home - project library overview: page title, sort control and project cards."""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from auth import allowed
from components.cards import (
    empty_state,
    page_header,
    project_card,
    safe_color,
    section_header,
)
from database import Category, Project, Response, SessionLocal
from services.project_access import visible_project_ids
from services.workspace_service import pinned_project_ids, toggle_pin
from services.audit_service import record as audit
from utils.layout import card_columns
from utils.navigation import PAGE_PROJECT, goto
from utils.validators import clean_key, valid_hex_color

logger = logging.getLogger(__name__)

# label -> sort key over (project, category_count, response_count) rows
SORTS: dict[str, Callable[[Sequence], Any]] = {
    "Manual order": lambda r: (r[0].sort_order, r[0].id),
    "Name (A to Z)": lambda r: ((r[0].name or "").lower(), r[0].id),
    "Most responses": lambda r: (-_as_int(r[2]), (r[0].name or "").lower()),
    "Most categories": lambda r: (-_as_int(r[1]), (r[0].name or "").lower()),
}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _matches(project: Project, term: str) -> bool:
    if not term:
        return True
    haystack = " ".join(
        filter(None, (project.name, project.description, project.key))
    ).lower()
    return term in haystack


def _order(rows: Sequence, pins: set[int], sort_label: str) -> list:
    """Pinned libraries first, then the chosen sort."""
    key = SORTS.get(sort_label, SORTS["Manual order"])
    return sorted(rows, key=lambda row: (row[0].id not in pins, key(row)))


def _load_project_rows() -> list:
    """Projects with category/response counts in a single round-trip."""
    cat_counts = (
        select(Category.project_id.label("pid"), func.count(Category.id).label("n"))
        .group_by(Category.project_id)
        .subquery()
    )
    resp_counts = (
        select(Category.project_id.label("pid"), func.count(Response.id).label("n"))
        .join(Response, Response.category_id == Category.id)
        .group_by(Category.project_id)
        .subquery()
    )
    statement = (
        select(
            Project, func.coalesce(cat_counts.c.n, 0), func.coalesce(resp_counts.c.n, 0)
        )
        .outerjoin(cat_counts, cat_counts.c.pid == Project.id)
        .outerjoin(resp_counts, resp_counts.c.pid == Project.id)
        .where(Project.is_deleted == False)  # noqa: E712
        .order_by(Project.sort_order, Project.id)
    )
    with SessionLocal() as db:
        return list(db.execute(statement).all())


@st.dialog("Edit project")
def _edit_project(user_id: int, project_id: int) -> None:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            st.error("Project not found.")
            return
        with st.form(f"edit_project_{project_id}"):
            name = st.text_input("Name", value=project.name or "")
            key = st.text_input("Key", value=getattr(project, "key", "") or "")
            description = st.text_area("Description", value=project.description or "")
            color = st.color_picker(
                "Colour", safe_color(getattr(project, "color", "#0c46ce"))
            )
            submitted = st.form_submit_button("Save", type="primary", width="stretch")
        if not submitted:
            return
        name = name.strip()
        key = clean_key(key)
        if not name or not key or not valid_hex_color(color):
            st.error("Enter a name, project key, and valid colour.")
            return
        project.name = name
        project.key = key
        project.description = description.strip()
        project.color = color
        audit(db, user_id, "update", "project", project.id, name)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            st.error("That project key is already in use.")
            return
        except Exception:
            db.rollback()
            logger.exception("Could not edit project %s", project_id)
            st.error("Could not update the project. Please try again.")
            return
    st.rerun()


@st.dialog("Archive project")
def _archive_project(user_id: int, project_id: int) -> None:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            st.error("Project not found.")
            return
        st.warning("Archive this project? Its categories and responses will be kept.")
        if st.button("Archive project", type="primary", width="stretch"):
            project.is_deleted = True
            audit(db, user_id, "archive", "project", project.id, project.name)
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Could not archive project %s", project_id)
                st.error("Could not archive the project. Please try again.")
                return
    st.rerun()


def _render_cards(
    rows: Sequence,
    pins: set[int],
    user_id: int,
    role: str,
    key_prefix: str,
) -> None:
    count = card_columns()  # the user's Personal Settings choice
    columns = st.columns(count, gap="medium")
    can_manage = role in {"admin", "owner", "manager"} or allowed(
        role, "manage_content"
    )
    for index, (project, n_cat, n_resp) in enumerate(rows):
        with columns[index % count]:
            opened, pin_clicked, edit_clicked, archive_clicked = project_card(
                project,
                pinned=project.id in pins,
                can_manage=can_manage,
                key_prefix=key_prefix,
            )
        if opened:
            goto(PAGE_PROJECT, project_id=project.id)
        if pin_clicked:
            try:
                toggle_pin(user_id, project.id)
            except Exception:  # noqa: BLE001
                logger.exception("Pin toggle failed for project %s", project.id)
                st.error("Could not update the pin. Please try again.")
            else:
                st.rerun()
        if edit_clicked:
            _edit_project(user_id, project.id)
        if archive_clicked:
            _archive_project(user_id, project.id)


def _render_empty(searching: bool, role: str) -> None:
    if searching:
        empty_state(
            None,
            "No libraries match your search",
            "Check the spelling or search by project key.",
        )
    elif allowed(role, "manage_content"):
        empty_state(
            None,
            "No libraries yet",
            "Add one under Admin Settings > Content & users > Projects, then import responses from JSON on the project page.",
        )
    else:
        empty_state(
            None,
            "No libraries assigned to you",
            "Ask an administrator to give your account access to a project library.",
        )


def render(user) -> None:
    term = (st.session_state.get("global_search") or "").strip().lower()

    try:
        rows = _load_project_rows()
    except Exception:  # noqa: BLE001
        logger.exception("Could not load project rows")
        st.error(
            "Could not load libraries. Refresh the page; if it persists, check the Health page."
        )
        return

    visible = visible_project_ids(user.id, user.role)  # None = unrestricted
    if visible is not None:
        rows = [row for row in rows if row[0].id in visible]

    page_header("Project libraries")
    matched = [row for row in rows if _matches(row[0], term)]
    if not matched:
        _render_empty(bool(term), user.role)
        return

    pins = set(pinned_project_ids(user.id))
    title_col, sort_col = st.columns([5, 2], vertical_alignment="center")
    sort_label = sort_col.selectbox(
        "Sort by", list(SORTS), key="home_sort", label_visibility="collapsed"
    )

    ordered = _order(matched, pins, sort_label)
    if pins and not term:
        pinned_rows = [row for row in ordered if row[0].id in pins]
        all_rows = [row for row in ordered if row[0].id not in pins]

        with title_col:
            section_header("Pinned", count=len(pinned_rows))
        _render_cards(pinned_rows, pins, user.id, user.role, "pin")

        if all_rows:
            all_title_col, _ = st.columns([5, 2], vertical_alignment="center")
            with all_title_col:
                section_header("All libraries", count=len(all_rows))
            _render_cards(all_rows, pins, user.id, user.role, "all")
    else:
        with title_col:
            section_header("All libraries", count=len(matched))
        _render_cards(ordered, pins, user.id, user.role, "all")
