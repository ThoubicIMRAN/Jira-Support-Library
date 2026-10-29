import streamlit as st

from components.cards import page_header
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from database import SessionLocal, Project, Category, User, AuditLog, Response, ResponseTag, ResponseTagLink
from auth import allowed, hash_password
from services.account_service import admin_set_password, admin_update_user, delete_user, unlock_login
from config import ROLES
from utils.validators import valid_hex_color, clean_key, valid_password
from services.content_service import move_project, move_category
from services.audit_service import query_audit, audit_csv
from services.workspace_service import usage_summary


def log(db, user_id, action, entity_type, entity_id, details=''):
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=str(entity_id), details=details))


@st.dialog('Edit project')
def edit_project(user_id, project_id):
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        with st.form('edit_project'):
            name = st.text_input('Name', row.name); description = st.text_area('Description', row.description)
            icon = st.text_input('Icon', row.icon); color = st.text_input('Color', row.color)
            save = st.form_submit_button('Save', type='primary', width='stretch')
        if save:
            if not name.strip() or not valid_hex_color(color): st.error('Enter a name and valid #RRGGBB color.'); return
            row.name = name.strip(); row.description = description.strip(); row.icon = icon.strip() or '📁'; row.color = color
            log(db, user_id, 'update', 'project', row.id); db.commit(); st.rerun()


@st.dialog('Archive project')
def archive_project(user_id, project_id):
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        st.warning(f'Archive “{row.name}”? Its categories and responses will be retained.')
        if st.button('Archive project', type='primary', width='stretch'):
            row.is_deleted = True; log(db, user_id, 'archive', 'project', row.id); db.commit(); st.rerun()


@st.dialog('Rename category')
def rename_category(user_id, category_id):
    with SessionLocal() as db:
        row = db.get(Category, category_id)
        with st.form('rename_category'):
            name = st.text_input('Category name', row.name)
            save = st.form_submit_button('Rename', type='primary', width='stretch')
        if save:
            if not name.strip(): st.error('Category name is required.'); return
            row.name = name.strip(); log(db, user_id, 'rename', 'category', row.id)
            try: db.commit(); st.rerun()
            except IntegrityError: db.rollback(); st.error('A category with this name already exists.')


@st.dialog('Delete category')
def update_category(user_id, category_id, *, name: str | None = None, parent_id=None, sort_order: int | None = None, clear_parent: bool = False):
    with SessionLocal() as db:
        row = db.get(Category, category_id)
        if not row:
            return
        if name is not None and name.strip():
            row.name = name.strip()
        if clear_parent:
            row.parent_id = None
        elif parent_id is not None:
            if int(parent_id) == int(category_id):
                st.error("Category cannot be its own parent.")
                return
            row.parent_id = int(parent_id) if parent_id else None
        if sort_order is not None:
            row.sort_order = int(sort_order)
        log(db, user_id, 'update', 'category', row.id, row.name)
        db.commit()
        st.rerun()


def delete_category(user_id, category_id):

    with SessionLocal() as db:
        row = db.get(Category, category_id)
        count = len(row.responses)
        if count: st.error(f'This category contains {count} responses. Move or delete them before deleting the category.'); return
        st.warning(f'Delete empty category “{row.name}”?')
        if st.button('Delete category', type='primary', width='stretch'):
            log(db, user_id, 'delete', 'category', row.id); db.delete(row); db.commit(); st.rerun()


def render(user, *, embedded: bool = False):
    if not allowed(user.role, 'manage_content'):
        st.error('Access denied.'); return
    if not embedded:
        page_header('⚙️ Administration')
    project_tab, category_tab, user_tab, access_tab, trash_tab, tag_tab, analytics_tab = st.tabs(['Projects','Categories','Users','Project access','Project trash','Tags','Usage Analytics'])
    with project_tab:
        with SessionLocal() as db:
            projects = db.scalars(select(Project).where(Project.is_deleted == False).order_by(Project.sort_order, Project.id)).all()
            with st.expander('➕ Add project'):
                with st.form('add_project'):
                    c1, c2 = st.columns(2); name = c1.text_input('Name'); key = c2.text_input('Key')
                    description = st.text_area('Description'); icon = st.text_input('Icon', '📁'); color = st.text_input('Color', '#3b82f6')
                    add = st.form_submit_button('Create project', type='primary')
                if add:
                    if not name.strip() or not valid_hex_color(color): st.error('Name and valid #RRGGBB color are required.')
                    else:
                        row = Project(key=clean_key(key or name), name=name.strip(), description=description.strip(), icon=icon or '📁', color=color, sort_order=len(projects))
                        db.add(row)
                        try: log(db, user.id, 'create', 'project', row.id, name); db.commit(); st.rerun()
                        except IntegrityError: db.rollback(); st.error('Project key already exists.')
            for index, project in enumerate(projects):
                cols = st.columns([6, 1, 1, 1, 1])
                cols[0].write(f'{project.icon} **{project.name}** · `{project.key}`')
                if cols[1].button('↑', key=f'project_up_{project.id}', disabled=index == 0): move_project(project.id, -1, user.id); st.rerun()
                if cols[2].button('↓', key=f'project_down_{project.id}', disabled=index == len(projects)-1): move_project(project.id, 1, user.id); st.rerun()
                if cols[3].button('✏️', key=f'project_edit_{project.id}'): edit_project(user.id, project.id)
                if cols[4].button('🗑️', key=f'project_archive_{project.id}'): archive_project(user.id, project.id)
    with category_tab:
        with SessionLocal() as db:
            projects = db.scalars(select(Project).where(Project.is_deleted == False).order_by(Project.sort_order)).all()
            if not projects: st.info('Create a project first.')
            else:
                project_id = st.selectbox('Project', [p.id for p in projects], format_func=lambda value: next(p.name for p in projects if p.id == value))
                categories = db.scalars(select(Category).where(Category.project_id == project_id).order_by(Category.sort_order, Category.id)).all()
                with st.form('add_category'):
                    name = st.text_input('New category / sub-category name')
                    _parents = [c for c in categories if not getattr(c, 'parent_id', None)]
                    parent_choice = st.selectbox(
                        'Parent (optional)',
                        options=[0] + [p.id for p in _parents],
                        format_func=lambda i: '— Top-level —' if i == 0 else next((p.name for p in _parents if p.id == i), str(i)),
                        key=f'new_cat_parent_{project_id}',
                    )
                    add = st.form_submit_button('Add category')
                if add and name.strip():
                    row = Category(project_id=project_id, name=name.strip(), sort_order=len(categories), parent_id=(parent_choice or None)); db.add(row)
                    try: db.commit(); st.rerun()
                    except IntegrityError: db.rollback(); st.error('Category already exists.')
                for index, category in enumerate(categories):
                    cols = st.columns([6, 1, 1, 1, 1])
                    cols[0].write(f'📁 **{category.name}** · {len(category.responses)} responses')
                    if cols[1].button('↑', key=f'category_up_{category.id}', disabled=index == 0): move_category(category.id, -1, user.id); st.rerun()
                    if cols[2].button('↓', key=f'category_down_{category.id}', disabled=index == len(categories)-1): move_category(category.id, 1, user.id); st.rerun()
                    if cols[3].button('✏️', key=f'category_edit_{category.id}'): rename_category(user.id, category.id)
                    if cols[4].button('🗑️', key=f'category_delete_{category.id}'): delete_category(user.id, category.id)
                    with st.expander(f"Edit · {category.name}", expanded=False):
                        with st.form(f"cat_edit_{category.id}"):
                            nn = st.text_input("Name", value=category.name)
                            so = st.number_input("Sort order", value=int(getattr(category, "sort_order", 0) or 0), step=1)
                            parents = [c for c in categories if c.id != category.id and not getattr(c, "parent_id", None)]
                            pmap = {0: "(top-level)"} | {c.id: c.name for c in parents}
                            cur_p = int(getattr(category, "parent_id", None) or 0)
                            if cur_p not in pmap:
                                cur_p = 0
                            pid = st.selectbox(
                                "Parent category",
                                list(pmap.keys()),
                                index=list(pmap.keys()).index(cur_p) if cur_p in pmap else 0,
                                format_func=lambda i: pmap[i],
                            )
                            if st.form_submit_button("Save category"):
                                update_category(
                                    user.id, category.id,
                                    name=nn, parent_id=pid or None,
                                    sort_order=int(so), clear_parent=(pid == 0),
                                )

    with user_tab:
        st.markdown("##### User management")
        st.caption("Superadmin can create users, change roles, reset passwords, and delete accounts.")
        with SessionLocal() as db:
            if user.role == 'superadmin':
                with st.expander('➕ Create local user', expanded=False):
                    with st.form('create_user'):
                        c1, c2 = st.columns(2)
                        username = c1.text_input('Username')
                        email = c2.text_input('Email')
                        full_name = st.text_input('Full name')
                        designation = st.text_input('Designation', 'Support Engineer')
                        role = st.selectbox('Role', ROLES, index=min(3, len(ROLES) - 1))
                        password = st.text_input('Temporary password', type='password')
                        create = st.form_submit_button('Create user', type='primary')
                    if create:
                        if not username.strip() or not full_name.strip() or not valid_password(password):
                            st.error('Username, full name and an 8-character password are required.')
                        else:
                            db.add(User(
                                username=username.strip(),
                                email=email.strip() or None,
                                full_name=full_name.strip(),
                                designation=designation.strip() or 'Support Engineer',
                                role=role,
                                password_hash=hash_password(password),
                                must_change_password=True,
                            ))
                            try:
                                db.commit()
                                st.success('User created.')
                                st.rerun()
                            except IntegrityError:
                                db.rollback()
                                st.error('Username or email already exists.')

            users = list(db.scalars(select(User).order_by(User.username)).all())
            for account in users:
                is_self = account.id == user.id
                can_manage = user.role == 'superadmin' and not is_self
                with st.container(border=True):
                    top = st.columns([3, 2, 1, 1])
                    top[0].markdown(
                        f"**{account.full_name}**  \n`{account.username}` · {account.email or '—'}"
                    )
                    role_opts = list(ROLES)
                    try:
                        role_idx = role_opts.index(account.role)
                    except ValueError:
                        role_idx = 0
                    new_role = top[1].selectbox(
                        'Role',
                        role_opts,
                        index=role_idx,
                        key=f'role_{account.id}',
                        label_visibility='collapsed',
                        disabled=not can_manage,
                    )
                    active = top[2].toggle(
                        'Active',
                        account.is_active,
                        key=f'active_{account.id}',
                        disabled=not can_manage,
                    )
                    if top[3].button('Save role', key=f'user_save_{account.id}', disabled=not can_manage, width='stretch'):
                        try:
                            admin_update_user(
                                user.id, account.id,
                                role=new_role, is_active=active,
                            )
                            st.toast('User updated.')
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

                    if can_manage:
                        with st.expander(f"Edit profile · {account.username}", expanded=False):
                            with st.form(f"edit_user_{account.id}"):
                                en = st.text_input("Full name", value=account.full_name or "")
                                em = st.text_input("Email", value=account.email or "")
                                ed = st.text_input("Designation", value=account.designation or "")
                                if st.form_submit_button("Save profile", type="primary"):
                                    try:
                                        admin_update_user(
                                            user.id, account.id,
                                            full_name=en, email=em, designation=ed,
                                        )
                                        st.success("Profile saved.")
                                        st.rerun()
                                    except ValueError as exc:
                                        st.error(str(exc))
                            from services.avatar_service import set_avatar, render_avatar_image, AvatarError
                            render_avatar_image(account, width=48)
                            aup = st.file_uploader(
                                "Set avatar", type=["png", "jpg", "jpeg", "webp"],
                                key=f"adm_av_{account.id}",
                            )
                            if st.button("Save avatar", key=f"adm_av_save_{account.id}") and aup:
                                try:
                                    set_avatar(account.id, aup.getvalue(), aup.type or "image/png")
                                    st.success("Avatar updated.")
                                    st.rerun()
                                except AvatarError as exc:
                                    st.error(str(exc))

                    if can_manage:
                        locked = False
                        try:
                            from services.security_policy import is_locked
                            locked = is_locked(account.username)
                        except Exception:
                            pass
                        if locked:
                            st.warning(f"🔒 **{account.username}** is temporarily locked (too many failed logins).")
                            if st.button("Unlock account", key=f"unlock_{account.id}", type="primary"):
                                n = unlock_login(account.username)
                                st.success(f"Unlocked. Cleared {n} login attempt record(s).")
                                st.rerun()

                        with st.form(f"pw_form_{account.id}"):
                            st.caption("Set a temporary password (user must change it after sign-in).")
                            new_pw = st.text_input(
                                "New password",
                                type="password",
                                key=f"pw_{account.id}",
                                placeholder="Min 8 characters",
                            )
                            pw_go = st.form_submit_button("Reset password", type="primary")
                        if pw_go:
                            try:
                                admin_set_password(account.id, new_pw or "", user.id)
                                unlock_login(account.username)
                                st.success(
                                    f"Password set for **{account.username}**. "
                                    "Account unlocked; user must change password on next login."
                                )
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                            except Exception as exc:
                                st.error(f"Password reset failed: {exc}")

                        if st.button("🗑️ Delete user", key=f"user_del_{account.id}"):
                            st.session_state[f"confirm_del_user_{account.id}"] = True
                        if st.session_state.get(f"confirm_del_user_{account.id}"):
                            st.warning(
                                f"Delete **{account.username}**? "
                                "Audit logs are kept (user field cleared). Sessions and personal data are removed."
                            )
                            d1, d2 = st.columns(2)
                            if d1.button("Confirm delete", key=f"user_del_yes_{account.id}", type="primary"):
                                try:
                                    delete_user(account.id, user.id)
                                    st.session_state.pop(f"confirm_del_user_{account.id}", None)
                                    st.success("User deleted. Audit history preserved.")
                                    st.rerun()
                                except ValueError as exc:
                                    st.error(str(exc))
                                except Exception as exc:
                                    st.error(f"Delete failed: {exc}")
                            if d2.button("Cancel", key=f"user_del_no_{account.id}"):
                                st.session_state.pop(f"confirm_del_user_{account.id}", None)
                                st.rerun()
                    elif is_self:
                        st.caption('You cannot modify or delete your own superadmin account here.')

    with tag_tab:
        with SessionLocal() as db:
            tags=db.scalars(select(ResponseTag).order_by(ResponseTag.name)).all()
            with st.form('create_tag'):
                t1,t2=st.columns([4,1]); tag_name=t1.text_input('Tag name'); tag_color=t2.color_picker('Color','#0c46ce')
                create_tag=st.form_submit_button('Create tag',type='primary',width='content')
            if create_tag and tag_name.strip():
                db.add(ResponseTag(name=tag_name.strip(),color=tag_color))
                try: db.commit(); st.rerun()
                except IntegrityError: db.rollback(); st.error('Tag already exists.')
            responses=db.scalars(select(Response).order_by(Response.title)).all()
            if tags and responses:
                response_id=st.selectbox('Response',[r.id for r in responses],format_func=lambda value:next(r.title for r in responses if r.id==value))
                assigned=set(db.scalars(select(ResponseTagLink.tag_id).where(ResponseTagLink.response_id==response_id)).all())
                selected=st.multiselect('Assigned tags',[t.id for t in tags],default=list(assigned),format_func=lambda value:next(t.name for t in tags if t.id==value))
                if st.button('Save response tags',width='content'):
                    db.execute(delete(ResponseTagLink).where(ResponseTagLink.response_id==response_id))
                    db.add_all([ResponseTagLink(response_id=response_id,tag_id=tag_id) for tag_id in selected]); db.commit(); st.rerun()
            for tag_item in tags:
                c1,c2=st.columns([7,1]); c1.markdown(f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{tag_item.color}"></span> **{tag_item.name}**',unsafe_allow_html=True)
                if c2.button('Delete',key=f'delete_tag_{tag_item.id}',width='stretch'):
                    db.delete(tag_item); db.commit(); st.rerun()

    with access_tab:
        from views.project_access_admin import render_project_access_admin
        render_project_access_admin(user)
    with trash_tab:
        st.subheader("Project trash")
        st.caption("Restore or permanently manage archived projects.")
        with SessionLocal() as db:
            trashed = list(db.scalars(select(Project).where(Project.is_deleted == True).order_by(Project.name)).all())
            if not trashed:
                st.info("No archived projects.")
            else:
                for p in trashed:
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"{p.icon} **{p.name}** (`{p.key}`)")
                    if c2.button("Restore", key=f"restore_proj_{p.id}"):
                        p.is_deleted = False
                        db.commit()
                        st.rerun()

    with analytics_tab:
        st.subheader('Response usage summary')
        st.caption('Favorites, unfavorites, and explicitly recorded views. Native clipboard actions are not tracked by the browser.')
        st.dataframe(usage_summary(100),width='stretch',hide_index=True)


# Phase 8 usage analytics is rendered through the existing admin page tabs.



def render_audit_section(user):
    """Audit log browser (separate Admin section)."""
    if user.role not in ('admin', 'superadmin'):
        st.warning('Admin access required.')
        return
    st.subheader('Audit log')
    with SessionLocal() as db:
        users_for_filter = db.scalars(select(User).order_by(User.username)).all()
        actions = db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()
        entities = db.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)).all()
    f1, f2, f3 = st.columns(3)
    action = f1.selectbox('Action', ['All'] + list(actions), key='audit_action')
    entity = f2.selectbox('Entity', ['All'] + list(entities), key='audit_entity')
    selected_user = f3.selectbox(
        'User',
        [None] + [u.id for u in users_for_filter],
        format_func=lambda value: 'All' if value is None else next(u.username for u in users_for_filter if u.id == value),
        key='audit_user',
    )
    d1, d2, d3 = st.columns(3)
    date_from = d1.date_input('From', value=None, key='audit_from')
    date_to = d2.date_input('To', value=None, key='audit_to')
    limit = d3.number_input('Maximum rows', min_value=50, max_value=5000, value=500, step=50, key='audit_limit')
    audit_rows = query_audit(
        None if action == 'All' else action,
        None if entity == 'All' else entity,
        selected_user,
        date_from,
        date_to,
        int(limit),
    )
    st.dataframe(audit_rows, width='stretch', hide_index=True)
    st.download_button(
        'Download audit CSV',
        audit_csv(audit_rows),
        'jira_audit_report.csv',
        'text/csv',
        width='stretch',
    )
