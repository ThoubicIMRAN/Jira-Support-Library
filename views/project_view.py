"""Project view — categories, response cards, CRUD, import/export.

Copy uses Streamlit's native ``st.code`` clipboard icon (no custom button).
All writes go through ``services.content_service`` which enforces RBAC,
validates input, uses one transaction and writes the audit trail.
"""
from __future__ import annotations

import json
import logging
from typing import Sequence

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from auth import allowed
from config import JIRA_BASE_URL, JIRA_ENABLED
from components.cards import (
    empty_state, page_header, preview_text, response_card_header, safe_key,
)
from database import Category, Project, SessionLocal
from services.content_service import (
    ContentError, create_response, delete_response, duplicate_response,
    export_project_payload, import_project_payload, update_response,
)
from services.workspace_service import designation_overrides, favorite_ids, toggle_favorite
from utils.layout import card_columns, flash, show_flash
from utils.navigation import PAGE_HOME, goto
from utils.personalization import PLACEHOLDER_HELP, personalize
from services.jira_text import ensure_signature_placeholders
from views.jira_action_dialog import jira_action_dialog
from services.project_access import can_view_project
from services.stale import is_stale, stale_label
from views.bulk_jira import bulk_comment_dialog
from views.jira_panel import render_jira_panel

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def _load_project_context(project_id: int):
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project or project.is_deleted:
            return None, []
        categories = list(
            db.scalars(
                select(Category)
                .where(Category.project_id == project_id)
                .options(selectinload(Category.responses))
                .order_by(Category.sort_order, Category.id)
            ).all()
        )
        db.expunge_all()
        return project, categories


def _category_options(project_id: int) -> dict[str, int]:
    """Labels for selects: top-level as name; children as 'Parent / Child'."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Category).where(Category.project_id == project_id).order_by(Category.sort_order, Category.id)
        ).all()
    by_id = {r.id: r for r in rows}
    out: dict[str, int] = {}
    for r in rows:
        if r.parent_id:
            parent = by_id.get(r.parent_id)
            label = f"{parent.name} / {r.name}" if parent else r.name
        else:
            # Prefer selecting leaves; still allow parent if it may hold responses
            label = r.name
        # Unique labels
        base = label
        n = 2
        while label in out and out[label] != r.id:
            label = f"{base} ({n})"
            n += 1
        out[label] = r.id
    return out


def _category_filter_options(project_id: int) -> list[tuple[str, int | None]]:
    """Sidebar filter: (label, category_id|None for all)."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Category).where(Category.project_id == project_id).order_by(Category.sort_order, Category.id)
        ).all()
    opts: list[tuple[str, int | None]] = [("All categories", None)]
    for r in rows:
        if r.parent_id is None:
            opts.append((r.name, r.id))
            for ch in rows:
                if ch.parent_id == r.id:
                    opts.append((f"  └ {ch.name}", ch.id))
    return opts



def _save_error(exc: Exception) -> None:
    if isinstance(exc, ContentError):
        st.error(str(exc))
    else:
        st.error("Could not save the change. Please try again.")


# --------------------------------------------------------------------------- #
# Dialogs
# --------------------------------------------------------------------------- #
@st.dialog("Add response", width="large")
def add_response_dialog(user_id: int, role: str, project_id: int) -> None:
    names = _category_options(project_id)
    if not names:
        st.warning("Create a category before adding responses.")
        return
    with st.form("add_response_form"):
        cat_name = st.selectbox("Category", list(names))
        title = st.text_input("Title", max_chars=200)
        c1, c2 = st.columns([1, 3])
        badge = c1.text_input("Badge", max_chars=40)
        preview = c2.text_input("Preview", max_chars=300)
        st.caption(
            "Greeting: **@R** (reporter). Signature: **@NAME** and **@DESIGNATION** "
            "(your profile — do not type your name into the template)."
        )
        _default_body = (
            "Hello @R,\n\n"
            "Your request has been processed.\n\n"
            "Thank you for your cooperation.\n\n"
            "Best regards,\n"
            "@NAME\n"
            "@DESIGNATION\n"
        )
        body = st.text_area(
            "Response body",
            value=_default_body,
            height=260,
            help=PLACEHOLDER_HELP,
        )
        submitted = st.form_submit_button("Save response", type="primary", width="stretch")
    if submitted:
        try:
            body = ensure_signature_placeholders(body or "")
            create_response(user_id, role, names[cat_name], title, badge, preview, body)
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, ContentError):
                logger.exception("Add response failed")
            _save_error(exc)
        else:
            flash("Response added.")
            st.rerun()


@st.dialog("Edit response", width="large")
def edit_response_dialog(user_id: int, role: str, project_id: int, row) -> None:
    names = _category_options(project_id)
    labels = list(names)
    current = next((n for n, i in names.items() if i == row.category_id), labels[0] if labels else None)
    with st.form("edit_response_form"):
        cat_name = st.selectbox("Category", labels, index=labels.index(current) if current in labels else 0)
        title = st.text_input("Title", row.title or "", max_chars=200)
        c1, c2 = st.columns([1, 3])
        badge = c1.text_input("Badge", row.badge or "", max_chars=40)
        preview = c2.text_input("Preview", row.preview or "", max_chars=300)
        body = st.text_area("Response body", row.response_body or "", height=260, help=PLACEHOLDER_HELP)
        st.caption("Keep **@NAME** / **@DESIGNATION** in the signature — they are filled from your profile.")
        submitted = st.form_submit_button("Update response", type="primary", width="stretch")
    if submitted:
        try:
            update_response(user_id, role, row.id, names[cat_name], title, badge, preview, ensure_signature_placeholders(body or ""))
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, ContentError):
                logger.exception("Update response failed")
            _save_error(exc)
        else:
            flash("Response updated.")
            st.rerun()


@st.dialog("Delete response")
def delete_response_dialog(user_id: int, role: str, response_id: str, title: str) -> None:
    st.write(f"Delete **{title}**? This cannot be undone.")
    left, right = st.columns(2)
    if left.button("Cancel", width="stretch"):
        st.rerun()
    if right.button("Delete", type="primary", width="stretch"):
        try:
            delete_response(user_id, role, response_id)
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, ContentError):
                logger.exception("Delete response failed")
            _save_error(exc)
        else:
            flash("Response deleted.", "🗑️")
            st.rerun()


# --------------------------------------------------------------------------- #
# Response card
# --------------------------------------------------------------------------- #
def _fmt_date(value) -> str:
    return value.strftime("%b %d, %Y") if value else "Recently"


def _toggle_favorite(user_id: int, response_id: str) -> None:
    try:
        toggle_favorite(user_id, response_id)
    except Exception:  # noqa: BLE001
        logger.exception("Favorite toggle failed")
        st.error("Could not update the favorite.")
    else:
        st.rerun()


def _render_response_card(user, project: Project, category: Category, row, favorites: set, overrides: dict, index: int) -> None:
    body = personalize(row.response_body, user, project.id, overrides)
    card_key = f"rcard_{safe_key(row.id)}"
    can_dupe, can_edit, can_delete = (allowed(user.role, p) for p in ("duplicate", "edit", "delete"))
    is_fav = row.id in favorites

    with st.container(key=card_key):
        response_card_header(
            container_key=card_key, index=index, title=row.title, badge=row.badge,
            color=project.color, subtitle=(
                f"Updated {_fmt_date(row.updated_at)}"
                + (f" · ⚠️ {stale_label(row.updated_at)}" if is_stale(row.updated_at) else "")
            ),
        )
        preview_text(row.preview)
        st.code(body, language=None, wrap_lines=True)  # native copy icon

        with st.container(key=f"rfoot_{safe_key(row.id)}"):
            jira_on = JIRA_ENABLED and bool(JIRA_BASE_URL)
            cols = st.columns(1 + jira_on + can_dupe + can_edit + can_delete, gap="small")
            slot = iter(cols)
            if jira_on and next(slot).button("🎫", key=f"jira_{row.id}", width="stretch", help="Jira: comment, log time, transition"):
                jira_action_dialog(user, project, body, response_id=str(row.id))
            if next(slot).button("★" if is_fav else "☆", key=f"fav_{row.id}", width="stretch",
                                 help="Remove from favorites" if is_fav else "Add to favorites"):
                _toggle_favorite(user.id, row.id)
            if can_dupe and next(slot).button("⧉", key=f"dupe_{row.id}", width="stretch", help="Duplicate"):
                try:
                    duplicate_response(row.id, user.id, user.role)
                except Exception:  # noqa: BLE001
                    logger.exception("Duplicate failed")
                    st.error("Could not duplicate the response.")
                else:
                    flash("Response duplicated.")
                    st.rerun()
            if can_edit and next(slot).button("✏️", key=f"edit_{row.id}", width="stretch", help="Edit"):
                edit_response_dialog(user.id, user.role, project.id, row)
            if can_delete and next(slot).button("🗑️", key=f"del_{row.id}", width="stretch", help="Delete"):
                delete_response_dialog(user.id, user.role, row.id, row.title)


def _filter_rows(category: Category, term: str) -> list:
    rows = list(category.responses or [])
    if not term:
        return rows
    return [
        r for r in rows
        if term in " ".join(filter(None, [r.title, r.badge, r.preview, r.response_body, category.name])).lower()
    ]


def _render_categories(user, project, categories: Sequence[Category], term: str, category_filter) -> int:
    from components.cards import section_header

    favorites = set(favorite_ids(user.id))
    overrides = designation_overrides(user.id)
    columns_n = card_columns()
    visible = 0
    for category in categories:
        if category_filter:
            if category.id != category_filter and getattr(category, "parent_id", None) != category_filter:
                continue
        rows = _filter_rows(category, term)
        if not rows:
            continue
        visible += len(rows)
        _sec = category.name
        if getattr(category, "parent_id", None):
            try:
                with SessionLocal() as _db:
                    _p = _db.get(Category, category.parent_id)
                    if _p:
                        _sec = f"{_p.name} / {category.name}"
            except Exception:
                pass
        section_header(_sec, len(rows), project.color)
        columns = st.columns(columns_n, gap="medium")
        for index, row in enumerate(rows):
            with columns[index % columns_n]:
                _render_response_card(user, project, category, row, favorites, overrides, index + 1)
    return visible


# --------------------------------------------------------------------------- #
# Toolbar
# --------------------------------------------------------------------------- #
def _render_toolbar(user, project: Project) -> str:
    c_search, c_add, c_bulk, c_export = st.columns([4.4, 1.2, 1.4, 1.2], vertical_alignment="bottom")
    query = c_search.text_input(
        "Search responses", placeholder="🔍  Search title, badge, preview, category or text",
        key="project_search", label_visibility="collapsed",
    )
    if allowed(user.role, "create") and c_add.button("➕ Add", width="stretch", type="primary", key="project_add"):
        add_response_dialog(user.id, user.role, project.id)

    if JIRA_ENABLED and JIRA_BASE_URL and c_bulk.button("📣 Bulk comment", width="stretch", key="project_bulk", help="Post one comment to many Jira tickets"):
        bulk_comment_dialog(user, project)

    payload = export_project_payload(project.id) or {}
    c_export.download_button(
        "📤 Export", data=json.dumps(payload, ensure_ascii=False, indent=2),
        file_name=f"{project.key}_library.json", mime="application/json", width="stretch", key="project_export",
    )

    if allowed(user.role, "import"):
        with st.expander("📥 Import from JSON"):
            uploaded = st.file_uploader("Select a project JSON file", type=["json"], key="project_import_file")
            if uploaded and st.button("Validate and import", type="primary", key="project_import_confirm"):
                try:
                    imported = import_project_payload(project.id, json.loads(uploaded.getvalue()), user.id, user.role)
                except json.JSONDecodeError:
                    st.error("That file is not valid JSON.")
                except Exception as exc:  # noqa: BLE001
                    if not isinstance(exc, ContentError):
                        logger.exception("Import failed")
                    st.error(str(exc) if isinstance(exc, ContentError) else "Import failed. Please try again.")
                else:
                    flash(f"Imported {imported} responses.")
                    st.rerun()
    return (query or "").strip().lower()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def render(user) -> None:
    show_flash()
    project_id = st.session_state.get("project_id")
    project, categories = _load_project_context(int(project_id)) if project_id else (None, [])

    # Drop stale category filter from another project
    _cf = st.session_state.get("category_filter")
    if _cf and categories and _cf not in {c.id for c in categories}:
        st.session_state.pop("category_filter", None)
    if project and not can_view_project(user, project.id):
        project = None  # same message as a missing project: do not reveal that it exists
    if not project:
        empty_state("📁", "Project not found", "It may have been archived or you have not selected one.")
        if st.button("← Back to Home", key="project_missing_home"):
            goto(PAGE_HOME, clear_project=True)
        return

    if st.button("← Back to Home", key="project_back_home", type="tertiary"):
        goto(PAGE_HOME, clear_project=True)

    page_header(project.name, project.description or None, icon=project.icon or "📁")
    total = sum(len(c.responses or []) for c in categories)
    st.markdown(
        f'<span class="jsl-chip">{len(categories)} categories</span> '
        f'<span class="jsl-chip">{total} responses</span>',
        unsafe_allow_html=True,
    )

    render_jira_panel(user, project)
    term = _render_toolbar(user, project)
    visible = _render_categories(user, project, categories, term, st.session_state.get("category_filter"))
    if visible == 0:
        empty_state("🗂️", "No responses match your filters", "Clear the search box or pick another category.")
