import sys
from sqlalchemy import text
from database import init_db, engine, SessionLocal, Project, User
from sqlalchemy import select, func

def main():
    init_db()
    with engine.connect() as conn: conn.execute(text('SELECT 1'))
    with SessionLocal() as db:
        projects = db.scalar(select(func.count(Project.id))) or 0
        users = db.scalar(select(func.count(User.id))) or 0
    print({'database':'ok','projects':projects,'users':users})
    return 0 if projects and users else 1
if __name__ == '__main__': sys.exit(main())
