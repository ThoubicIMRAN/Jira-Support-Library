from datetime import datetime, timezone
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload
from database import (User, SessionLocal, UserFavorite, UserPinnedProject, UserRecentResponse,
                      ResponseUsageEvent, Response, Category, Project, UserSavedSearch, ResponseTag, ResponseTagLink,
                      UserProjectDesignation)

def utcnow(): return datetime.now(timezone.utc)

def favorite_ids(user_id):
    with SessionLocal() as db:
        return set(db.scalars(select(UserFavorite.response_id).where(UserFavorite.user_id==user_id)).all())

def toggle_favorite(user_id,response_id):
    with SessionLocal() as db:
        row=db.scalar(select(UserFavorite).where(UserFavorite.user_id==user_id,UserFavorite.response_id==response_id))
        if row:
            db.delete(row); state=False
        else:
            db.add(UserFavorite(user_id=user_id,response_id=response_id)); state=True
        db.add(ResponseUsageEvent(user_id=user_id,response_id=response_id,action='favorite' if state else 'unfavorite'))
        db.commit(); return state

def designation_overrides(user_id):
    """{project_id: designation} the user configured on their profile."""
    with SessionLocal() as db:
        rows=db.execute(select(UserProjectDesignation.project_id,UserProjectDesignation.designation).where(UserProjectDesignation.user_id==user_id)).all()
    return {project_id:designation for project_id,designation in rows}

def pinned_project_ids(user_id):
    with SessionLocal() as db:
        return set(db.scalars(select(UserPinnedProject.project_id).where(UserPinnedProject.user_id==user_id)).all())

def toggle_pin(user_id,project_id):
    with SessionLocal() as db:
        row=db.scalar(select(UserPinnedProject).where(UserPinnedProject.user_id==user_id,UserPinnedProject.project_id==project_id))
        if row: db.delete(row); state=False
        else: db.add(UserPinnedProject(user_id=user_id,project_id=project_id)); state=True
        db.commit(); return state

def record_view(user_id,response_id):
    with SessionLocal() as db:
        row=db.scalar(select(UserRecentResponse).where(UserRecentResponse.user_id==user_id,UserRecentResponse.response_id==response_id))
        if row: row.viewed_at=utcnow(); row.view_count+=1
        else: db.add(UserRecentResponse(user_id=user_id,response_id=response_id,viewed_at=utcnow(),view_count=1))
        db.add(ResponseUsageEvent(user_id=user_id,response_id=response_id,action='view'))
        db.commit()

def _viewer_projects(user_id):
    from services.project_access import visible_project_ids
    with SessionLocal() as db:
        user=db.get(User,user_id)
    return None if user is None else visible_project_ids(user_id,user.role)

def response_records(user_id,mode='favorites',limit=50):
    visible=_viewer_projects(user_id)
    with SessionLocal() as db:
        if mode=='favorites':
            ids=select(UserFavorite.response_id).where(UserFavorite.user_id==user_id).order_by(UserFavorite.created_at.desc()).limit(limit)
        else:
            ids=select(UserRecentResponse.response_id).where(UserRecentResponse.user_id==user_id).order_by(UserRecentResponse.viewed_at.desc()).limit(limit)
        statement=(select(Response).join(Category).options(selectinload(Response.category).selectinload(Category.project)).where(Response.id.in_(ids)))
        if visible is not None: statement=statement.where(Category.project_id.in_(visible or [-1]))
        return db.scalars(statement).all()

def global_search(term,project_id=None,category_id=None,tag=None,limit=100,viewer=None):
    search=f'%{term.strip().lower()}%'
    with SessionLocal() as db:
        stmt=(select(Response).join(Category).join(Project).options(selectinload(Response.category).selectinload(Category.project))
              .where(Project.is_deleted==False))
        if term.strip():
            haystack=func.lower(Response.title+' '+func.coalesce(Response.preview,'')+' '+Response.response_body+' '+Category.name+' '+Project.name)
            stmt=stmt.where(haystack.like(search))
        if viewer is not None:
            visible=_viewer_projects(viewer.id)
            if visible is not None: stmt=stmt.where(Project.id.in_(visible or [-1]))
        if project_id: stmt=stmt.where(Project.id==project_id)
        if category_id: stmt=stmt.where(Category.id==category_id)
        if tag:
            stmt=stmt.join(ResponseTagLink,ResponseTagLink.response_id==Response.id).join(ResponseTag,ResponseTag.id==ResponseTagLink.tag_id).where(ResponseTag.name==tag)
        return db.scalars(stmt.order_by(Project.sort_order,Category.sort_order,Response.sort_order).limit(limit)).all()

def usage_summary(limit=20):
    with SessionLocal() as db:
        rows=db.execute(select(Response.title,Project.name,ResponseUsageEvent.action,func.count(ResponseUsageEvent.id))
            .join(Response,Response.id==ResponseUsageEvent.response_id).join(Category,Category.id==Response.category_id).join(Project,Project.id==Category.project_id)
            .group_by(Response.id,Response.title,Project.name,ResponseUsageEvent.action)
            .order_by(func.count(ResponseUsageEvent.id).desc()).limit(limit)).all()
        return [{'Response':r[0],'Project':r[1],'Action':r[2],'Count':r[3]} for r in rows]

def project_filter_options():
    with SessionLocal() as db:
        projects=db.scalars(select(Project).where(Project.is_deleted==False).order_by(Project.sort_order)).all()
        categories=db.scalars(select(Category).order_by(Category.project_id,Category.sort_order)).all()
        tags=db.scalars(select(ResponseTag).order_by(ResponseTag.name)).all()
        return projects,categories,tags

def saved_searches(user_id):
    with SessionLocal() as db:
        return db.scalars(select(UserSavedSearch).where(UserSavedSearch.user_id==user_id).order_by(UserSavedSearch.name)).all()

def save_search(user_id,name,query,project_id=None,category_id=None,tag=None):
    name=name.strip();
    if not name: raise ValueError('Saved search name is required.')
    with SessionLocal() as db:
        row=db.scalar(select(UserSavedSearch).where(UserSavedSearch.user_id==user_id,UserSavedSearch.name==name))
        if not row: row=UserSavedSearch(user_id=user_id,name=name); db.add(row)
        row.query=query.strip(); row.project_id=project_id; row.category_id=category_id; row.tag=tag or None
        db.commit()

def delete_saved_search(user_id,search_id):
    with SessionLocal() as db:
        db.execute(delete(UserSavedSearch).where(UserSavedSearch.id==search_id,UserSavedSearch.user_id==user_id)); db.commit()

def response_tag_names(response_ids):
    if not response_ids:return {}
    with SessionLocal() as db:
        rows=db.execute(select(ResponseTagLink.response_id,ResponseTag.name).join(ResponseTag,ResponseTag.id==ResponseTagLink.tag_id).where(ResponseTagLink.response_id.in_(response_ids))).all()
    result={}
    for response_id,name in rows: result.setdefault(response_id,[]).append(name)
    return result
