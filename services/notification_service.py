from datetime import datetime, timezone
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from database import SessionLocal, UserNotificationState, Response, Category, Project, User

def utcnow(): return datetime.now(timezone.utc)

def get_state(user_id):
    with SessionLocal() as db:
        row=db.scalar(select(UserNotificationState).where(UserNotificationState.user_id==user_id))
        if not row:
            row=UserNotificationState(user_id=user_id,last_seen_at=utcnow());db.add(row);db.commit();db.refresh(row)
        return {'last_seen_at':row.last_seen_at,'notify_new_responses':row.notify_new_responses,'notify_updated_responses':row.notify_updated_responses}

def notification_items(user_id,limit=100):
    state=get_state(user_id); last_seen=state['last_seen_at']
    with SessionLocal() as db:
        conditions=[]
        if state['notify_new_responses']: conditions.append(Response.created_at>last_seen)
        if state['notify_updated_responses']: conditions.append(Response.updated_at>last_seen)
        if not conditions:return []
        from services.project_access import visible_project_ids
        viewer=db.get(User,user_id)
        visible=None if viewer is None else visible_project_ids(user_id,viewer.role)
        scope=[Project.is_deleted==False,or_(*conditions)]
        if visible is not None: scope.append(Project.id.in_(visible or [-1]))
        rows=db.scalars(select(Response).join(Category).join(Project)
            .options(selectinload(Response.category).selectinload(Category.project))
            .where(*scope)
            .order_by(Response.updated_at.desc()).limit(limit)).all()
    return rows

def unread_count(user_id): return len(notification_items(user_id,200))

def mark_all_read(user_id):
    with SessionLocal() as db:
        row=db.scalar(select(UserNotificationState).where(UserNotificationState.user_id==user_id))
        if not row: row=UserNotificationState(user_id=user_id);db.add(row)
        row.last_seen_at=utcnow();db.commit()

def save_notification_settings(user_id,new_enabled,updated_enabled):
    with SessionLocal() as db:
        row=db.scalar(select(UserNotificationState).where(UserNotificationState.user_id==user_id))
        if not row: row=UserNotificationState(user_id=user_id);db.add(row)
        row.notify_new_responses=new_enabled;row.notify_updated_responses=updated_enabled;db.commit()
