from __future__ import annotations

import uuid
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from auth import allowed
from database import Category, Project, Response, SessionLocal
from services.content_service import move_category, move_project
from utils.validators import clean_key, valid_hex_color


def render(user) -> None:
    if not allowed(user.role, "manage_content"):
        st.error("You do not have permission to manage content.")
        return

    st.subheader("Content")
    st.caption("Manage the library hierarchy without switching between separate administration pages.")
    tab_project, tab_category, tab_response = st.tabs(["Projects", "Categories", "Responses"])

    with tab_project:
        with SessionLocal() as db:
            projects = db.scalars(
                select(Project)
                .where(Project.is_deleted.is_(False))
                .order_by(Project.sort_order, Project.id)
            ).all()
            project_rows = [
                {
                    "id": p.id, "name": p.name, "key": p.key, "description": p.description,
                    "icon": p.icon, "color": p.color
                }
                for p in projects
            ]
            with st.form("ac_project"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Project name")
                key = c2.text_input("Project key")
                description = st.text_area("Description")
                c3, c4 = st.columns(2)
                icon = c3.text_input("Icon", "📁")
                color = c4.text_input("Color", "#3b82f6")
                add = st.form_submit_button("Create project", type="primary")
            if add:
                if not name.strip() or not valid_hex_color(color):
                    st.error("Project name and valid #RRGGBB color are required.")
                else:
                    row = Project(key=clean_key(key or name), name=name.strip(), description=description.strip(), icon=icon.strip() or "📁", color=color.strip(), sort_order=len(projects))
                    db.add(row)
                    try:
                        db.commit()
                        st.rerun()
                    except IntegrityError:
                        db.rollback()
                        st.error("Project key already exists.")

        for index, project in enumerate(project_rows):
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([5, 1, 1, 1], vertical_alignment="center")
                c1.markdown(f"**{project['icon']} {project['name']}**  \n`{project['key']}` · {project['description'] or 'No description'}")
                if c2.button("↑", key=f"ac_pu_{project['id']}", disabled=index == 0):
                    move_project(project["id"], -1, user.id); st.rerun()
                if c3.button("↓", key=f"ac_pd_{project['id']}", disabled=index == len(project_rows) - 1):
                    move_project(project["id"], 1, user.id); st.rerun()
                if c4.button("Archive", key=f"ac_pa_{project['id']}"):
                    with SessionLocal() as db:
                        row = db.get(Project, project["id"])
                        if row:
                            row.is_deleted = True
                            db.commit()
                    st.rerun()

    with tab_category:
        with SessionLocal() as db:
            projects = db.scalars(
                select(Project).where(Project.is_deleted.is_(False)).order_by(Project.sort_order, Project.id)
            ).all()
            project_options = [(p.id, p.name) for p in projects]
        if not project_options:
            st.info("Create a project first.")
        else:
            project_id = st.selectbox("Project", [p[0] for p in project_options], format_func=lambda x: next(p[1] for p in project_options if p[0] == x), key="ac_category_project")
            with SessionLocal() as db:
                category_rows = db.execute(
                    select(Category.id, Category.name, Category.sort_order, func.count(Response.id).label("response_count"))
                    .outerjoin(Response, Response.category_id == Category.id)
                    .where(Category.project_id == project_id)
                    .group_by(Category.id, Category.name, Category.sort_order)
                    .order_by(Category.sort_order, Category.id)
                ).all()
                with st.form("ac_category"):
                    name = st.text_input("Category name")
                    add = st.form_submit_button("Add category", type="primary")
                if add:
                    if not name.strip():
                        st.error("Category name is required.")
                    else:
                        db.add(Category(project_id=project_id, name=name.strip(), sort_order=len(category_rows)))
                        try:
                            db.commit(); st.rerun()
                        except IntegrityError:
                            db.rollback(); st.error("Category already exists in this project.")

            for index, category in enumerate(category_rows):
                category_id, category_name, _sort_order, response_count = category
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([5, 1, 1, 1])
                    c1.write(f"**{category_name}** · {response_count} responses")
                    if c2.button("↑", key=f"ac_cu_{category_id}", disabled=index == 0):
                        move_category(category_id, -1, user.id); st.rerun()
                    if c3.button("↓", key=f"ac_cd_{category_id}", disabled=index == len(category_rows) - 1):
                        move_category(category_id, 1, user.id); st.rerun()
                    if c4.button("Delete", key=f"ac_cdel_{category_id}"):
                        if response_count:
                            st.warning("Move or delete its responses first.")
                        else:
                            with SessionLocal() as db:
                                row = db.get(Category, category_id)
                                if row:
                                    db.delete(row); db.commit()
                            st.rerun()

    with tab_response:
        with SessionLocal() as db:
            category_rows = db.execute(
                select(Category.id, Category.name, Project.name.label("project_name"))
                .join(Project, Project.id == Category.project_id)
                .where(Project.is_deleted.is_(False))
                .order_by(Project.sort_order, Category.sort_order, Category.id)
            ).all()
        if not category_rows:
            st.info("Create a category first.")
        else:
            labels = {row.id: f"{row.project_name} / {row.name}" for row in category_rows}
            with st.form("ac_response"):
                category_id = st.selectbox("Category", list(labels), format_func=labels.get)
                title = st.text_input("Title")
                body = st.text_area("Response", height=240)
                add = st.form_submit_button("Add response", type="primary")
            if add:
                if not title.strip() or not body.strip():
                    st.error("Title and response are required.")
                else:
                    with SessionLocal() as db:
                        db.add(Response(id="r_" + uuid.uuid4().hex, category_id=category_id, title=title.strip(), response_body=body.strip()))
                        db.commit()
                    st.success("Response added.")
                    st.rerun()
