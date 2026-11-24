"""Admin tools: projects, categories, users, project access, trash, tags, usage analytics and the audit browser.

Which tabs a person sees depends on their role (``auth.PERMISSIONS``). Only the selected tab is rendered.
Users: admins can view the list; only superadmins can create, edit, reset passwords or delete (services enforce it too).
"""

from __future__ import annotations

import html

import streamlit as st
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from auth import allowed, hash_password
from components.cards import page_header
from config import ROLES
from database import (
    AuditLog,
    Category,
    Project,
    Response,
    ResponseTag,
    ResponseTagLink,
    SessionLocal,
    User,
)
from services.account_service import (
    admin_set_password,
    admin_update_user,
    delete_user,
    unlock_account,
    unlock_login,
)
from services.audit_service import audit_csv, query_audit
from services.audit_service import record as audit
from services.avatar_service import AvatarError, render_avatar_image, set_avatar
from services.content_service import move_category, move_project
from services.workspace_service import usage_summary
from utils.errors import log_ignored, safe_message
from utils.validators import clean_key, valid_hex_color, valid_password

DEFAULT_ICON = "📁"
DEFAULT_COLOR = "#3b82f6"


# ============================================================================ dialogs
@st.dialog("Edit project")
def edit_project(user_id: int, project_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        if row is None:
            st.error("Project not found.")
            return
        with st.form("edit_project"):
            name = st.text_input("Name", row.name)
            description = st.text_area("Description", row.description or "")
            icon = st.text_input("Icon", row.icon or "")
            color = st.text_input("Colour", row.color or DEFAULT_COLOR)
            save = st.form_submit_button("Save", type="primary", width="stretch")
        if not save:
            return
        if not name.strip() or not valid_hex_color(color):
            st.error("Enter a name and a valid #RRGGBB colour.")
            return
        row.name, row.description = name.strip(), description.strip()
        row.icon, row.color = icon.strip() or DEFAULT_ICON, color
        audit(db, user_id, "update", "project", row.id, row.name)
        db.commit()
    st.rerun()


@st.dialog("Archive project")
def archive_project(user_id: int, project_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        if row is None:
            st.error("Project not found.")
            return
        st.warning(
            f"Archive “{row.name}”? Its categories and responses are kept, and you can restore it from Project trash."
        )
        if st.button("Archive project", type="primary", width="stretch"):
            row.is_deleted = True
            audit(db, user_id, "archive", "project", row.id, row.name)
            db.commit()
            st.rerun()


@st.dialog("Edit category")
def edit_category(user_id: int, category_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(Category, category_id)
        if row is None:
            st.error("Category not found.")
            return
        has_children = bool(
            db.scalar(
                select(func.count(Category.id)).where(Category.parent_id == row.id)
            )
        )
        parents = db.scalars(
            select(Category)
            .where(
                Category.project_id == row.project_id,
                Category.id != row.id,
                Category.parent_id.is_(None),
            )
            .order_by(Category.sort_order, Category.id)
        ).all()
        parent_names = {0: "Top level"} | {p.id: p.name for p in parents}
        options = list(parent_names)
        with st.form("edit_category"):
            name = st.text_input("Name", row.name)
            parent = st.selectbox(
                "Parent category",
                options,
                index=options.index(row.parent_id) if row.parent_id in options else 0,
                format_func=parent_names.get,
                disabled=has_children,
                help="A category that has sub-categories must stay at the top level."
                if has_children
                else None,
            )
            save = st.form_submit_button("Save", type="primary", width="stretch")
        if not save:
            return
        if not name.strip():
            st.error("Category name is required.")
            return
        row.name = name.strip()
        if not has_children:
            row.parent_id = parent or None
        audit(db, user_id, "update", "category", row.id, row.name)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            st.error("A category with this name already exists.")
            return
    st.rerun()


@st.dialog("Delete category")
def delete_category(user_id: int, category_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(Category, category_id)
        if row is None:
            st.error("Category not found.")
            return
        responses = (
            db.scalar(
                select(func.count(Response.id)).where(Response.category_id == row.id)
            )
            or 0
        )
        children = (
            db.scalar(
                select(func.count(Category.id)).where(Category.parent_id == row.id)
            )
            or 0
        )
        if responses or children:
            st.error(
                f"“{row.name}” still holds {responses} response(s) and {children} sub-categor{'y' if children == 1 else 'ies'}. Move or delete them first."
            )
            return
        st.warning(f"Delete the empty category “{row.name}”?")
        if st.button("Delete category", type="primary", width="stretch"):
            audit(db, user_id, "delete", "category", row.id, row.name)
            db.delete(row)
            db.commit()
            st.rerun()


# ============================================================================ shared row
def _action_row(
    label: str,
    *,
    kind: str,
    item_id: int,
    index: int,
    total: int,
    user,
    move,
    edit,
    remove,
    remove_help: str,
) -> None:
    """One list row: label plus move up / move down / edit / remove."""
    cols = st.columns([6, 1, 1, 1, 1], vertical_alignment="center")
    cols[0].markdown(label)
    if cols[1].button(
        "",
        key=f"{kind}_up_{item_id}",
        icon=":material/arrow_upward:",
        help="Move up",
        disabled=index == 0,
    ):
        move(item_id, -1, user.id)
        st.rerun()
    if cols[2].button(
        "",
        key=f"{kind}_down_{item_id}",
        icon=":material/arrow_downward:",
        help="Move down",
        disabled=index == total - 1,
    ):
        move(item_id, 1, user.id)
        st.rerun()
    if cols[3].button(
        "", key=f"{kind}_edit_{item_id}", icon=":material/edit:", help="Edit"
    ):
        edit(user.id, item_id)
    if cols[4].button(
        "", key=f"{kind}_remove_{item_id}", icon=":material/delete:", help=remove_help
    ):
        remove(user.id, item_id)


# ============================================================================ tabs
def _projects_tab(user) -> None:
    with SessionLocal() as db:
        projects = db.scalars(
            select(Project)
            .where(Project.is_deleted.is_(False))
            .order_by(Project.sort_order, Project.id)
        ).all()

    with st.expander("Add project", icon=":material/add:"):
        with st.form("add_project", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name")
            key = c2.text_input(
                "Key", help="Short unique code, for example ATOA. Defaults to the name."
            )
            description = st.text_area("Description")
            c3, c4 = st.columns(2)
            icon = c3.text_input("Icon", DEFAULT_ICON)
            color = c4.text_input("Colour", DEFAULT_COLOR)
            add = st.form_submit_button("Create project", type="primary")
        if add:
            if not name.strip() or not valid_hex_color(color):
                st.error("A name and a valid #RRGGBB colour are required.")
            else:
                with SessionLocal() as db:
                    row = Project(
                        key=clean_key(key or name),
                        name=name.strip(),
                        description=description.strip(),
                        icon=icon.strip() or DEFAULT_ICON,
                        color=color,
                        sort_order=len(projects),
                    )
                    db.add(row)
                    try:
                        db.flush()  # assigns row.id so the audit row is correct
                        audit(db, user.id, "create", "project", row.id, row.name)
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        st.error("A project with this key already exists.")
                        return
                st.rerun()

    if not projects:
        st.info("No projects yet.")
    for index, project in enumerate(projects):
        _action_row(
            f"**{project.name}**  `{project.key}`",
            kind="project",
            item_id=project.id,
            index=index,
            total=len(projects),
            user=user,
            move=move_project,
            edit=edit_project,
            remove=archive_project,
            remove_help="Archive project",
        )


def _categories_tab(user) -> None:
    with SessionLocal() as db:
        project_names = dict(
            db.execute(
                select(Project.id, Project.name)
                .where(Project.is_deleted.is_(False))
                .order_by(Project.sort_order, Project.id)
            ).all()
        )
    if not project_names:
        st.info("Create a project first.")
        return

    project_id = st.selectbox(
        "Project",
        list(project_names),
        format_func=project_names.get,
        key="admin_cat_project",
    )
    with SessionLocal() as db:
        categories = db.scalars(
            select(Category)
            .where(Category.project_id == project_id)
            .order_by(Category.sort_order, Category.id)
        ).all()
        counts = dict(
            db.execute(  # one grouped query instead of one lazy load per category
                select(Category.id, func.count(Response.id))
                .outerjoin(Response, Response.category_id == Category.id)
                .where(Category.project_id == project_id)
                .group_by(Category.id)
            ).all()
        )

    parent_names = {0: "Top level"} | {
        c.id: c.name for c in categories if not c.parent_id
    }
    with st.form("add_category", clear_on_submit=True):
        name = st.text_input("New category or sub-category")
        parent = st.selectbox(
            "Parent (optional)", list(parent_names), format_func=parent_names.get
        )
        add = st.form_submit_button("Add category")
    if add:
        if not name.strip():
            st.error("Enter a category name.")
        else:
            with SessionLocal() as db:
                row = Category(
                    project_id=project_id,
                    name=name.strip(),
                    parent_id=parent or None,
                    sort_order=len(categories),
                )
                db.add(row)
                try:
                    db.flush()
                    audit(db, user.id, "create", "category", row.id, row.name)
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    st.error("That category already exists.")
                    return
            st.rerun()

    if not categories:
        st.info("This project has no categories yet.")
    for index, category in enumerate(categories):
        prefix = "↳ " if category.parent_id else ""
        _action_row(
            f"{prefix}**{category.name}**  ·  {counts.get(category.id, 0)} responses",
            kind="category",
            item_id=category.id,
            index=index,
            total=len(categories),
            user=user,
            move=move_category,
            edit=edit_category,
            remove=delete_category,
            remove_help="Delete category",
        )


def _tags_tab(user) -> None:
    with SessionLocal() as db:
        tags = db.scalars(select(ResponseTag).order_by(ResponseTag.name)).all()
        responses = dict(
            db.execute(
                select(Response.id, Response.title).order_by(Response.title)
            ).all()
        )

    with st.form("create_tag", clear_on_submit=True):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        name = c1.text_input("Tag name")
        color = c2.color_picker("Colour", "#0c46ce")
        create = st.form_submit_button("Create tag", type="primary")
    if create:
        if not name.strip():
            st.error("Enter a tag name.")
        else:
            with SessionLocal() as db:
                db.add(ResponseTag(name=name.strip(), color=color))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    st.error("That tag already exists.")
                    return
            st.rerun()

    if tags and responses:
        st.markdown("##### Tags on a response")
        tag_names = {t.id: t.name for t in tags}
        response_id = st.selectbox(
            "Response", list(responses), format_func=responses.get, key="tag_response"
        )
        with SessionLocal() as db:
            assigned = list(
                db.scalars(
                    select(ResponseTagLink.tag_id).where(
                        ResponseTagLink.response_id == response_id
                    )
                )
            )
        selected = st.multiselect(
            "Assigned tags",
            list(tag_names),
            default=assigned,
            format_func=tag_names.get,
            key=f"tag_pick_{response_id}",
        )
        if st.button("Save response tags", key="tag_save"):
            with SessionLocal() as db:
                db.execute(
                    delete(ResponseTagLink).where(
                        ResponseTagLink.response_id == response_id
                    )
                )
                db.add_all(
                    [
                        ResponseTagLink(response_id=response_id, tag_id=t)
                        for t in selected
                    ]
                )
                audit(
                    db,
                    user.id,
                    "update",
                    "response_tags",
                    response_id,
                    ", ".join(tag_names[t] for t in selected),
                )
                db.commit()
            st.toast("Tags saved.")

    st.markdown("##### All tags")
    for tag in tags:
        c1, c2 = st.columns([7, 1], vertical_alignment="center")
        swatch = (
            tag.color if valid_hex_color(tag.color or "") else "#999999"
        )  # validated: it goes into HTML
        c1.markdown(
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{swatch};margin-right:8px"></span>'
            f"<b>{html.escape(tag.name)}</b>",  # escaped: tag names are user input
            unsafe_allow_html=True,
        )
        if c2.button(
            "Delete",
            key=f"delete_tag_{tag.id}",
            icon=":material/delete:",
            width="stretch",
        ):
            with SessionLocal() as db:
                db.execute(
                    delete(ResponseTagLink).where(ResponseTagLink.tag_id == tag.id)
                )
                db.execute(delete(ResponseTag).where(ResponseTag.id == tag.id))
                audit(db, user.id, "delete", "tag", tag.id, tag.name)
                db.commit()
            st.rerun()


def _trash_tab(user) -> None:
    st.caption("Archived projects. Restore one to bring it back to the library.")
    with SessionLocal() as db:
        trashed = db.scalars(
            select(Project).where(Project.is_deleted.is_(True)).order_by(Project.name)
        ).all()
    if not trashed:
        st.info("No archived projects.")
    for project in trashed:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        c1.markdown(f"**{project.name}**  `{project.key}`")
        if c2.button(
            "Restore",
            key=f"restore_proj_{project.id}",
            icon=":material/restore:",
            width="stretch",
        ):
            with SessionLocal() as db:
                row = db.get(Project, project.id)
                row.is_deleted = False
                audit(db, user.id, "restore", "project", row.id, row.name)
                db.commit()
            st.rerun()


# ============================================================================ users
def _users_tab(user) -> None:
    if not allowed(user.role, "view_users"):
        st.warning("Admin access required.")
        return

    editable = allowed(user.role, "manage_users")
    st.caption(
        "Superadmins can create users, change roles, reset passwords and delete accounts. "
        "Admins can view the list."
    )
    if editable:
        _create_user(user)

    with SessionLocal() as db:
        accounts = list(db.scalars(select(User).order_by(User.username)).all())
    for account in accounts:
        _user_card(user, account, can_manage=editable and account.id != user.id)


# ----------------------------------------------------------------------------- create
def _create_user(actor) -> None:
    roles = list(ROLES)
    default_role = roles.index("user") if "user" in roles else len(roles) - 1
    with st.expander("Create local user", icon=":material/person_add:"):
        with st.form("create_user", clear_on_submit=True):
            c1, c2 = st.columns(2)
            username = c1.text_input("Username")
            email = c2.text_input("Email")
            full_name = st.text_input("Full name")
            designation = st.text_input("Designation", "Support Engineer")
            role = st.selectbox("Role", roles, index=default_role)
            password = st.text_input("Temporary password", type="password")
            create = st.form_submit_button("Create user", type="primary")
        if not create:
            return
        if (
            not username.strip()
            or not full_name.strip()
            or not valid_password(password)
        ):
            st.error(
                "Username, full name and a valid temporary password (minimum 8 characters) are required."
            )
            return
        with SessionLocal() as db:
            row = User(
                username=username.strip(),
                email=email.strip() or None,
                full_name=full_name.strip(),
                designation=designation.strip() or "Support Engineer",
                role=role,
                password_hash=hash_password(password),
                must_change_password=True,
            )
            db.add(row)
            try:
                db.flush()
                audit(
                    db, actor.id, "create", "user", row.id, f"{row.username} ({role})"
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                st.error("That username or email already exists.")
                return
        st.rerun()


# ----------------------------------------------------------------------------- one account
def _user_card(actor, account: User, *, can_manage: bool) -> None:
    with st.container(border=True):
        head = st.columns([4, 2, 1, 1], vertical_alignment="center")
        head[0].markdown(
            f"**{account.full_name}**  \n`{account.username}` · {account.email or 'No email'}"
        )

        if not can_manage:  # admins, or your own row: read-only
            head[1].markdown(account.role.title())
            head[2].markdown("Active" if account.is_active else "Disabled")
            if account.id == actor.id:
                head[3].caption("You")
            return

        role_options = list(ROLES)
        new_role = head[1].selectbox(
            "Role",
            role_options,
            index=role_options.index(account.role)
            if account.role in role_options
            else 0,
            key=f"role_{account.id}",
            label_visibility="collapsed",
        )
        active = head[2].toggle("Active", account.is_active, key=f"active_{account.id}")
        if head[3].button("Save", key=f"user_save_{account.id}", width="stretch"):
            _run(
                lambda: admin_update_user(
                    actor.id, account.id, role=new_role, is_active=active
                ),
                "User updated.",
            )

        with st.expander(f"Manage {account.username}"):
            _profile_form(actor, account)
            _avatar_form(actor, account)
            _password_form(actor, account)
            _danger_zone(actor, account)


def _run(action, success: str | None = None) -> None:
    """Run a service call; show a safe error or rerun on success."""
    try:
        action()
    except ValueError as exc:
        st.error(safe_message(exc))
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"The action failed: {safe_message(exc)}")
        return
    if success:
        st.toast(success)
    st.rerun()


def _profile_form(actor, account: User) -> None:
    with st.form(f"edit_user_{account.id}"):
        full_name = st.text_input("Full name", account.full_name or "")
        email = st.text_input("Email", account.email or "")
        designation = st.text_input("Designation", account.designation or "")
        saved = st.form_submit_button("Save profile", type="primary")
    if saved:
        _run(
            lambda: admin_update_user(
                actor.id,
                account.id,
                full_name=full_name,
                email=email,
                designation=designation,
            ),
            "Profile saved.",
        )


def _avatar_form(actor, account: User) -> None:
    st.markdown("**Avatar**")
    render_avatar_image(account, width=48)
    upload = st.file_uploader(
        "Set avatar", type=["png", "jpg", "jpeg", "webp"], key=f"adm_av_{account.id}"
    )
    if upload and st.button("Save avatar", key=f"adm_av_save_{account.id}"):
        try:
            set_avatar(
                account.id,
                upload.getvalue(),
                upload.type or "image/png",
                actor_id=actor.id,
                actor_role=getattr(actor, "role", None),
            )
        except AvatarError as exc:
            st.error(safe_message(exc))
            return
        st.toast("Avatar updated.")
        st.rerun()


def _password_form(actor, account: User) -> None:
    locked = False
    try:
        from services.security_policy import is_locked

        locked = is_locked(account.username)
    except Exception:  # noqa: BLE001
        log_ignored(__name__)
    if locked:
        st.warning(
            f"{account.username} is temporarily locked after too many failed sign-ins."
        )
        if st.button("Unlock account", key=f"unlock_{account.id}", type="primary"):
            cleared = unlock_account(account.username, actor.role)
            st.toast(f"Unlocked. Cleared {cleared} login attempt record(s).")
            st.rerun()

    with st.form(f"pw_form_{account.id}"):
        st.caption("Set a temporary password. The user must change it at next sign-in.")
        new_password = st.text_input(
            "New password", type="password", placeholder="Minimum 8 characters"
        )
        reset = st.form_submit_button("Reset password", type="primary")
    if reset:

        def action() -> None:
            admin_set_password(account.id, new_password or "", actor.id, actor.role)
            unlock_login(account.username)

        _run(
            action,
            f"Password set for {account.username}. They must change it at next sign-in.",
        )


def _danger_zone(actor, account: User) -> None:
    if st.button("Delete user", key=f"user_del_{account.id}", icon=":material/delete:"):
        _confirm_delete(actor.id, actor.role, account.id, account.username)


@st.dialog("Delete user")
def _confirm_delete(
    actor_id: int, actor_role: str, account_id: int, username: str
) -> None:
    st.warning(
        f"Delete **{username}**? Audit logs are kept with the user field cleared. "
        "Sessions and personal data are removed. This cannot be undone."
    )
    confirm, cancel = st.columns(2)
    if confirm.button("Delete user", type="primary", width="stretch"):
        _run(
            lambda: delete_user(account_id, actor_id, actor_role),
            "User deleted. Audit history preserved.",
        )
    if cancel.button("Cancel", width="stretch"):
        st.rerun()


def _access_tab(user) -> None:
    from views.project_access_admin import render_project_access_admin

    render_project_access_admin(user)


def _analytics_tab(user) -> None:
    st.caption(
        "Favourites, unfavourites and explicitly recorded views. Browser clipboard actions are not tracked."
    )
    st.dataframe(usage_summary(100), width="stretch", hide_index=True)


# ============================================================================ entry points
def _visible_tabs(role: str) -> dict:
    """Tabs this role may see, in display order."""
    tabs = {"Projects": _projects_tab, "Categories": _categories_tab}
    if allowed(role, "view_users"):
        tabs["Users"] = _users_tab
    if allowed(role, "manage_access"):
        tabs["Project access"] = _access_tab
    tabs["Project trash"] = _trash_tab
    tabs["Tags"] = _tags_tab
    if allowed(role, "view_analytics"):
        tabs["Usage analytics"] = _analytics_tab
    return tabs


def render(user, *, embedded: bool = False) -> None:
    if not allowed(user.role, "manage_content"):
        st.error("Access denied.")
        return
    if not embedded:
        page_header("Administration")

    tabs = _visible_tabs(user.role)
    state_key = "admin_content_section"
    if st.session_state.get(state_key) not in tabs:
        st.session_state.pop(state_key, None)
    first = next(iter(tabs))
    section = (
        st.segmented_control(
            "Section",
            list(tabs),
            default=first,
            key=state_key,
            label_visibility="collapsed",
        )
        or first
    )
    tabs[section](user)


def render_audit_section(user) -> None:
    """Audit log browser (admins and superadmins)."""
    if not allowed(user.role, "view_audit"):
        st.warning("Admin access required.")
        return
    st.subheader("Audit log")
    with SessionLocal() as db:
        usernames = dict(
            db.execute(select(User.id, User.username).order_by(User.username)).all()
        )
        actions = db.scalars(
            select(AuditLog.action).distinct().order_by(AuditLog.action)
        ).all()
        entities = db.scalars(
            select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)
        ).all()

    f1, f2, f3 = st.columns(3)
    action = f1.selectbox("Action", ["All", *actions], key="audit_action")
    entity = f2.selectbox("Entity", ["All", *entities], key="audit_entity")
    selected_user = f3.selectbox(
        "User",
        [None, *usernames],
        format_func=lambda v: "All" if v is None else usernames[v],
        key="audit_user",
    )
    d1, d2, d3 = st.columns(3)
    date_from = d1.date_input("From", value=None, key="audit_from")
    date_to = d2.date_input("To", value=None, key="audit_to")
    limit = d3.number_input(
        "Maximum rows",
        min_value=50,
        max_value=5000,
        value=500,
        step=50,
        key="audit_limit",
    )

    rows = query_audit(
        None if action == "All" else action,
        None if entity == "All" else entity,
        selected_user,
        date_from,
        date_to,
        int(limit),
    )
    st.dataframe(rows, width="stretch", hide_index=True)
    st.download_button(
        "Download audit CSV",
        audit_csv(rows),
        "jira_audit_report.csv",
        "text/csv",
        width="stretch",
    )
