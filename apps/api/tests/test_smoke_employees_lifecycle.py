"""qiepai · ❷-6 smoke test — digital employee lifecycle + readiness + persona.

Run with::

    cd /Users/luobo/code/work/qiepai
    source .venv/bin/activate
    python -m pytest apps/api/tests/test_smoke_employees_lifecycle.py -q --no-header

Scenarios covered (one test per scenario for clear failure isolation):

1. Create employee (no persona) + 5 CRUD endpoints.
2. Publish state machine happy path: ``draft → configuring → ready → published``.
3. Readiness gate blocks ``ready`` until p0/p1 set + sync_state != error/drifted.
4. Sync_state ``error`` / ``drifted`` blocks the move to ``ready`` / ``published``.
5. Persona 1:1 collision: POST a second employee with the same persona_id → 409.
6. Persona swap via PATCH: assign a new persona → 200; old persona reusable.
7. revision_number UNIQUE: two POSTs get revision_number 1 and 2 in order.
8. List / get / delete endpoints return the right shapes + cascade revisions.
9. Tasks router — CRUD + state machine + decision_id soft reference.
10. Tasks router — DELETE physically removes the row.

The DB / migration fixtures are borrowed from the ❷-5 decisions test
(``test_decisions_router.py``); we re-use the same per-test temp DB
pattern so the smoke test stays order-independent.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.qiepai import employees as employees_routes
from apps.api.routes.qiepai import tasks as tasks_routes
from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai import migration_runner, seed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qiepai_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh per-test temp DB + bootstrap schema + seed."""
    db_file = tmp_path / "qiepai-smoke.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    asyncio.run(migration_runner.run_pending_migrations())
    asyncio.run(seed.seed_initial_metrics())
    return db_file


@pytest.fixture
def client(qiepai_db_path: Path) -> TestClient:
    """Mount both routers under /qiepai like the real app."""
    app = FastAPI()
    app.include_router(employees_routes.router, prefix="/qiepai")
    app.include_router(tasks_routes.router, prefix="/qiepai")
    return TestClient(app)


def _create_employee(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "display_name": "财务数字员工",
        "role": "财务",
    }
    body.update(overrides)
    resp = client.post("/qiepai/employees", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_revision(
    client: TestClient,
    employee_id: str,
    *,
    workspace_file_hash: str = "sha256:abc",
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "workspace_file_hash": workspace_file_hash,
        "config_snapshot": config_snapshot if config_snapshot is not None else {"voice": "edge-xiaoxiao"},
    }
    resp = client.post(f"/qiepai/employees/{employee_id}/revisions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_revision_readiness(
    client: TestClient, employee_id: str, *, p0: bool, p1: bool, sync_state: str
) -> None:
    """Directly UPDATE the latest revision via the qiepai DB helper."""
    from apps.api.services.qiepai import db as qiepai_db

    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        # SQLite UPDATE doesn't accept ORDER BY + LIMIT — use a subquery to
        # pin the row id first. ``id`` is the PK, so this is exact.
        cur.execute(
            "UPDATE employee_revisions SET readiness_p0 = ?, readiness_p1 = ?, "
            "sync_state = ? WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (1 if p0 else 0, 1 if p1 else 0, sync_state, employee_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. CRUD on a persona-less employee
# ---------------------------------------------------------------------------


def test_employee_crud_no_persona(client: TestClient) -> None:
    created = _create_employee(client)
    assert created["status"] == "draft"
    assert created["display_name"] == "财务数字员工"
    assert created["role"] == "财务"
    assert created["persona_id"] is None
    assert created["current_revision_id"] is None
    eid = created["id"]

    # GET single
    resp = client.get(f"/qiepai/employees/{eid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == eid

    # LIST
    resp = client.get("/qiepai/employees")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(item["id"] == eid for item in body["items"])

    # PATCH display_name + role
    resp = client.patch(
        f"/qiepai/employees/{eid}",
        json={"display_name": "财务小助手", "role": "财务记账"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "财务小助手"
    assert resp.json()["role"] == "财务记账"

    # DELETE
    resp = client.delete(f"/qiepai/employees/{eid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": eid, "deleted": True}

    # GET after delete → 404
    resp = client.get(f"/qiepai/employees/{eid}")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 2. Publish state machine happy path
# ---------------------------------------------------------------------------


def test_publish_state_machine_happy_path(client: TestClient) -> None:
    emp = _create_employee(client)
    eid = emp["id"]
    _create_revision(client, eid)

    # draft → configuring (no readiness gate yet)
    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "configuring"
    assert resp.json()["current_revision_id"] is not None

    # configuring → ready fails (readiness not set yet)
    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 422, resp.text
    assert "readiness_p0/p1 required" in resp.json()["detail"]

    # Mark readiness + sync_state=in_sync, retry
    _set_revision_readiness(client, eid, p0=True, p1=True, sync_state="in_sync")

    # configuring → ready
    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ready"

    # ready → published
    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "published"


# ---------------------------------------------------------------------------
# 3. State machine rejects illegal transition (draft → published)
# ---------------------------------------------------------------------------


def test_publish_state_machine_rejects_skipping(client: TestClient) -> None:
    """Even with readiness set, a fresh draft cannot jump straight to published.

    The chain is enforced as ``draft → configuring → ready → published``;
    a single ``POST /publish`` advances exactly one step.
    """
    emp = _create_employee(client)
    eid = emp["id"]
    _create_revision(client, eid)
    _set_revision_readiness(client, eid, p0=True, p1=True, sync_state="in_sync")

    # First publish: draft → configuring (one step)
    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "configuring"

    # To prove "no skipping": manually try to set status via PATCH (rejected
    # with a 422 pointing the operator at /publish).
    resp = client.patch(f"/qiepai/employees/{eid}", json={"status": "published"})
    assert resp.status_code == 422, resp.text
    assert "publish" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 4. sync_state error / drifted blocks readiness gate
# ---------------------------------------------------------------------------


def test_sync_state_error_blocks_publish_to_ready(client: TestClient) -> None:
    emp = _create_employee(client)
    eid = emp["id"]
    _create_revision(client, eid)
    # advance one step to configuring
    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 200, resp.text
    # mark p0/p1 OK but sync_state=error
    _set_revision_readiness(client, eid, p0=True, p1=True, sync_state="error")

    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 422, resp.text
    assert "sync_state 'error' blocks" in resp.json()["detail"]


def test_sync_state_drifted_blocks_publish_to_ready(client: TestClient) -> None:
    emp = _create_employee(client)
    eid = emp["id"]
    _create_revision(client, eid)
    client.post(f"/qiepai/employees/{eid}/publish")  # draft → configuring
    _set_revision_readiness(client, eid, p0=True, p1=True, sync_state="drifted")

    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 422, resp.text
    assert "sync_state 'drifted' blocks" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Persona 1:1 collision
# ---------------------------------------------------------------------------


def test_persona_one_to_one_collision_on_create(client: TestClient) -> None:
    a = _create_employee(client, display_name="员工A", persona_id="p_helper_1")
    b = _create_employee(
        client, display_name="员工B", persona_id="p_helper_2"
    )  # OK (different persona)

    # Now try to link p_helper_1 to B → 409
    resp = client.patch(f"/qiepai/employees/{b['id']}", json={"persona_id": "p_helper_1"})
    assert resp.status_code == 409, resp.text
    assert "persona already linked to" in resp.json()["detail"]
    assert a["id"] in resp.json()["detail"]


def test_persona_create_conflict(client: TestClient) -> None:
    """POST with an already-linked persona_id → 409."""
    _create_employee(client, display_name="员工A", persona_id="p_helper_1")
    resp = client.post(
        "/qiepai/employees",
        json={"display_name": "员工B", "role": "财务", "persona_id": "p_helper_1"},
    )
    assert resp.status_code == 409, resp.text
    assert "persona already linked to" in resp.json()["detail"]


def test_persona_swap_via_patch(client: TestClient) -> None:
    a = _create_employee(client, display_name="员工A", persona_id="p_helper_1")
    b = _create_employee(client, display_name="员工B", persona_id="p_helper_2")

    # Move A from p_helper_1 → p_helper_3; release p_helper_1; then claim p_helper_1 on B.
    resp = client.patch(f"/qiepai/employees/{a['id']}", json={"persona_id": "p_helper_3"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["persona_id"] == "p_helper_3"

    resp = client.patch(f"/qiepai/employees/{b['id']}", json={"persona_id": "p_helper_1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["persona_id"] == "p_helper_1"


# ---------------------------------------------------------------------------
# 6. revision_number UNIQUE — auto-increment in order
# ---------------------------------------------------------------------------


def test_revision_number_auto_increments_and_unique(client: TestClient) -> None:
    emp = _create_employee(client)
    eid = emp["id"]

    revs = []
    for i in range(1, 4):
        rev = _create_revision(client, eid, workspace_file_hash=f"sha256:v{i}")
        revs.append(rev)

    assert [r["revision_number"] for r in revs] == [1, 2, 3]
    # GET revisions returns newest first
    resp = client.get(f"/qiepai/employees/{eid}/revisions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert [r["revision_number"] for r in body["items"]] == [3, 2, 1]


# ---------------------------------------------------------------------------
# 7. DELETE cascades revisions
# ---------------------------------------------------------------------------


def test_delete_cascades_revisions(client: TestClient) -> None:
    emp = _create_employee(client)
    eid = emp["id"]
    _create_revision(client, eid)
    _create_revision(client, eid, workspace_file_hash="sha256:v2")

    # Delete the employee
    resp = client.delete(f"/qiepai/employees/{eid}")
    assert resp.status_code == 200, resp.text

    # Revisions should also be gone (cascade)
    from apps.api.services.qiepai import db as qiepai_db

    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n FROM employee_revisions WHERE employee_id = ?",
            (eid,),
        )
        n = cur.fetchone()["n"]
    finally:
        conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# 8. Tasks router — CRUD + state machine
# ---------------------------------------------------------------------------


def test_task_crud_and_state_machine(client: TestClient) -> None:
    # Create
    resp = client.post(
        "/qiepai/tasks",
        json={
            "title": "复盘 Q3 应收",
            "description": "拉明细",
            "assignee_id": "user_42",
        },
    )
    assert resp.status_code == 200, resp.text
    task = resp.json()
    assert task["status"] == "todo"
    tid = task["id"]

    # GET single
    resp = client.get(f"/qiepai/tasks/{tid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == tid

    # LIST with filter
    resp = client.get("/qiepai/tasks", params={"status": "todo"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert all(item["status"] == "todo" for item in body["items"])

    # PATCH status todo → in_progress
    resp = client.patch(f"/qiepai/tasks/{tid}", json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"

    # PATCH status in_progress → done
    resp = client.patch(f"/qiepai/tasks/{tid}", json={"status": "done"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"

    # PATCH on terminal state rejects status change (409)
    resp = client.patch(f"/qiepai/tasks/{tid}", json={"status": "in_progress"})
    assert resp.status_code == 409, resp.text
    assert "terminal" in resp.json()["detail"].lower()

    # Description edits still allowed on terminal
    resp = client.patch(
        f"/qiepai/tasks/{tid}", json={"description": "post-hoc note"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "post-hoc note"

    # DELETE (physical)
    resp = client.delete(f"/qiepai/tasks/{tid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": tid, "deleted": True}

    # GET after delete → 404
    resp = client.get(f"/qiepai/tasks/{tid}")
    assert resp.status_code == 404, resp.text


def test_task_invalid_status_filter_returns_422(client: TestClient) -> None:
    resp = client.get("/qiepai/tasks", params={"status": "banana"})
    assert resp.status_code == 422, resp.text


def test_task_create_requires_title(client: TestClient) -> None:
    resp = client.post("/qiepai/tasks", json={"description": "no title"})
    assert resp.status_code == 422, resp.text
    assert "title" in resp.json()["detail"]


def test_task_decision_id_soft_reference(client: TestClient) -> None:
    """decision_id is stored verbatim even if the referenced decision doesn't exist."""
    resp = client.post(
        "/qiepai/tasks",
        json={"title": "task from decision", "decision_id": "dec_does_not_exist"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision_id"] == "dec_does_not_exist"
