import csv
import io
from datetime import datetime
from sqlalchemy import select
from database import SessionLocal, AuditLog, User

def query_audit(action=None, entity_type=None, user_id=None, date_from=None, date_to=None, limit=500):
    stmt = select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.user_id)
    if action: stmt = stmt.where(AuditLog.action == action)
    if entity_type: stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id: stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from: stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to: stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, datetime.max.time()))
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 5000))
    with SessionLocal() as db:
        rows = db.execute(stmt).all()
    return [
        {'Time': event.created_at, 'User': username or 'System', 'Action': event.action,
         'Entity': event.entity_type, 'ID': event.entity_id, 'Details': event.details}
        for event, username in rows
    ]

def audit_csv(rows):
    output = io.StringIO(); fields = ['Time','User','Action','Entity','ID','Details']
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for row in rows: writer.writerow(row)
    return output.getvalue().encode('utf-8-sig')
