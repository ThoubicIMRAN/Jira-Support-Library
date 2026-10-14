import json

import pytest
from sqlalchemy import select

from database import Project, SessionLocal
from services import content_service as cs


def _project_id():
    with SessionLocal() as db:
        return db.scalar(select(Project.id).order_by(Project.id))


def _category_id(pid):
    from database import Category
    with SessionLocal() as db:
        return db.scalar(select(Category.id).where(Category.project_id == pid).order_by(Category.id))


def test_crud_roundtrip_and_audit():
    cid = _category_id(_project_id())
    rid = cs.create_response(1, "superadmin", cid, "T", "B", "P", "Body")
    cs.update_response(1, "superadmin", rid, cid, "T2", "B", "P", "Body2")
    cs.delete_response(1, "superadmin", rid)
    from database import AuditLog, Response
    with SessionLocal() as db:
        assert db.get(Response, rid) is None
        actions = {a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity_id == rid)).all()}
    assert {"create", "update", "delete"} <= actions


def test_rbac_enforced_in_service_layer():
    cid = _category_id(_project_id())
    with pytest.raises(cs.ContentError):
        cs.create_response(2, "viewer", cid, "T", "", "", "Body")
    with pytest.raises(cs.ContentError):
        cs.delete_response(2, "user", "does-not-matter")


def test_validation():
    cid = _category_id(_project_id())
    with pytest.raises(cs.ContentError):
        cs.create_response(1, "superadmin", cid, "", "", "", "Body")
    with pytest.raises(cs.ContentError):
        cs.create_response(1, "superadmin", cid, "x" * 500, "", "", "Body")


def test_export_import_round_trip():
    pid = _project_id()
    payload = json.loads(json.dumps(cs.export_project_payload(pid)))
    before = sum(len(c["responses"]) for c in payload["categories"])
    assert before > 0
    assert cs.import_project_payload(pid, payload, 1) == before  # ids regenerated, nothing collides


def test_import_accepts_legacy_export_and_rejects_garbage():
    pid = _project_id()
    legacy = {"project": "X", "data": {"Legacy cat": [{"id": "a1", "title": "t", "response": "b"}]}}
    assert cs.import_project_payload(pid, legacy, 1) == 1
    for bad in ([], {"nope": 1}, {"categories": [{"name": "", "responses": []}]},
                {"categories": [{"name": "c", "responses": [{"title": "", "response_body": ""}]}]}):
        with pytest.raises(cs.ContentError):
            cs.import_project_payload(pid, bad, 1)


def test_move_project_with_duplicate_sort_orders():
    from database import Project as P
    with SessionLocal() as db:
        for p in db.scalars(select(P)).all():
            p.sort_order = 0
        db.commit()
    ids = []
    with SessionLocal() as db:
        ids = [p.id for p in db.scalars(select(P).where(P.is_deleted == False).order_by(P.sort_order, P.id)).all()]  # noqa: E712
    assert cs.move_project(ids[0], 1, 1) is True
    with SessionLocal() as db:
        order = [p.id for p in db.scalars(select(P).where(P.is_deleted == False).order_by(P.sort_order, P.id)).all()]  # noqa: E712
    assert order[1] == ids[0]
