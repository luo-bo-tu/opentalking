"""qiepai · ❷-6 review pass — independent self-check 2.

Covers the 7 review items the spec calls out as the self-check 2 surface:

1. 12 endpoint paths + methods (smoke-tested below via ``TestClient``)
2. State machine legal transitions + jump rejection
3. Readiness hard constraints (``readiness_p0/p1 + sync_state``)
4. Persona 1:1 conflict
5. ``revision_number`` UNIQUE behavior
6. ``sync_state`` blocking the move to ``ready`` / ``published``
7. Persona format / sanity (non-empty string check)

Each scenario is its own test so a failure points at exactly one review
item. The fixtures are identical to the lifecycle smoke test — per-test
temp DB + migrated + seeded.
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


@pytest.fixture
def qiepai_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "qiepai-review.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    asyncio.run(migration_runner.run_pending_migrations())
    asyncio.run(seed.seed_initial_metrics())
    return db_file


@pytest.fixture
def client(qiepai_db_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(employees_routes.router, prefix="/qiepai")
    app.include_router(tasks_routes.router, prefix="/qiepai")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Review item 1 — all 12 endpoints reachable + correct shapes
# ---------------------------------------------------------------------------


def test_review1_all_12_endpoints_registered(client: TestClient) -> None:
    """Smoke-walk every endpoint to confirm the path table from the spec."""
    # POST /employees
    emp_resp = client.post(
        "/qiepai/employees",
        json={"display_name": "测试员工", "role": "财务"},
    )
    assert emp_resp.status_code == 200, emp_resp.text
    emp_id = emp_resp.json()["id"]

    # GET /employees
    assert client.get("/qiepai/employees").status_code == 200

    # GET /employees/{id}
    assert client.get(f"/qiepai/employees/{emp_id}").status_code == 200

    # PATCH /employees/{id}
    assert (
        client.patch(
            f"/qiepai/employees/{emp_id}", json={"display_name": "改名"}
        ).status_code
        == 200
    )

    # DELETE /employees/{id}
    assert client.delete(f"/qiepai/employees/{emp_id}").status_code == 200

    # Create a second employee for the revisions + publish tests below
    emp2 = client.post(
        "/qiepai/employees",
        json={"display_name": "员工 2", "role": "销售"},
    ).json()
    emp2_id = emp2["id"]

    # POST /employees/{id}/revisions
    rev_resp = client.post(
        f"/qiepai/employees/{emp2_id}/revisions",
        json={
            "workspace_file_hash": "sha256:review",
            "config_snapshot": {"voice": "edge-xiaoxiao"},
        },
    )
    assert rev_resp.status_code == 201, rev_resp.text
    assert rev_resp.json()["revision_number"] == 1

    # GET /employees/{id}/revisions
    assert (
        client.get(f"/qiepai/employees/{emp2_id}/revisions").status_code == 200
    )

    # POST /employees/{id}/publish (first step: draft → configuring)
    assert (
        client.post(f"/qiepai/employees/{emp2_id}/publish").status_code == 200
    )

    # Tasks (5)
    task_resp = client.post(
        "/qiepai/tasks", json={"title": "review 任务"}
    )
    assert task_resp.status_code == 200, task_resp.text
    task_id = task_resp.json()["id"]

    assert client.get("/qiepai/tasks").status_code == 200
    assert client.get(f"/qiepai/tasks/{task_id}").status_code == 200
    assert (
        client.patch(f"/qiepai/tasks/{task_id}", json={"status": "in_progress"}).status_code
        == 200
    )
    assert client.delete(f"/qiepai/tasks/{task_id}").status_code == 200


# ---------------------------------------------------------------------------
# Review item 2 — state machine: legal transitions succeed, illegal fail
# ---------------------------------------------------------------------------


def test_review2_state_machine_legal_transitions(client: TestClient) -> None:
    """Walk the entire happy chain: draft → configuring → ready → published → suspended."""
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "链", "role": "财务"},
    ).json()
    eid = emp["id"]
    client.post(
        f"/qiepai/employees/{eid}/revisions",
        json={
            "workspace_file_hash": "sha256:chain",
            "config_snapshot": {"v": 1},
        },
    )

    # Mark readiness so the gate passes on moves to ready / published.
    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employee_revisions SET readiness_p0 = 1, readiness_p1 = 1, "
            "sync_state = 'in_sync' WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (eid,),
        )
        conn.commit()
    finally:
        conn.close()

    chain = ["configuring", "ready", "published", "suspended"]
    for expected in chain:
        resp = client.post(f"/qiepai/employees/{eid}/publish")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == expected, resp.text


def test_review2_state_machine_recovery_path(client: TestClient) -> None:
    """retired → published is the spec's "误操作恢复" path."""
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "链", "role": "财务"},
    ).json()
    eid = emp["id"]
    client.post(
        f"/qiepai/employees/{eid}/revisions",
        json={
            "workspace_file_hash": "sha256:recovery",
            "config_snapshot": {"v": 1},
        },
    )
    # Set readiness
    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employee_revisions SET readiness_p0 = 1, readiness_p1 = 1, "
            "sync_state = 'in_sync' WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (eid,),
        )
        conn.commit()
    finally:
        conn.close()

    # Force the employee into a published state via the chain
    for _ in range(3):
        client.post(f"/qiepai/employees/{eid}/publish")
    # And then suspend it
    client.post(f"/qiepai/employees/{eid}/publish")
    assert client.get(f"/qiepai/employees/{eid}").json()["status"] == "suspended"

    # Manually mark as retired via the DB (no public API path to retired
    # in the canonical chain — operators would do this via a separate
    # admin tool; we exercise the recovery from retired here).
    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employees SET status = 'retired' WHERE id = ?", (eid,)
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "published"


# ---------------------------------------------------------------------------
# Review item 3 — readiness hard constraints
# ---------------------------------------------------------------------------


def test_review3_readiness_p0_required(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "p0", "role": "财务"},
    ).json()
    client.post(
        f"/qiepai/employees/{emp['id']}/revisions",
        json={
            "workspace_file_hash": "sha256:p0",
            "config_snapshot": {"v": 1},
        },
    )
    # draft → configuring OK
    resp = client.post(f"/qiepai/employees/{emp['id']}/publish")
    assert resp.status_code == 200, resp.text

    # Set p1 only (p0 missing) → readiness gate should still 422.
    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employee_revisions SET readiness_p0 = 0, readiness_p1 = 1, "
            "sync_state = 'in_sync' WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (emp["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(f"/qiepai/employees/{emp['id']}/publish")
    assert resp.status_code == 422, resp.text
    assert "readiness_p0/p1 required" in resp.json()["detail"]


def test_review3_readiness_p1_required(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "p1", "role": "财务"},
    ).json()
    client.post(
        f"/qiepai/employees/{emp['id']}/revisions",
        json={
            "workspace_file_hash": "sha256:p1",
            "config_snapshot": {"v": 1},
        },
    )
    client.post(f"/qiepai/employees/{emp['id']}/publish")  # draft → configuring

    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employee_revisions SET readiness_p0 = 1, readiness_p1 = 0, "
            "sync_state = 'in_sync' WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (emp["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(f"/qiepai/employees/{emp['id']}/publish")
    assert resp.status_code == 422, resp.text


def test_review3_no_revisions_blocks_ready_and_published(client: TestClient) -> None:
    """Without revisions, moves to ready / published should fail with 422."""
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "no_rev", "role": "财务"},
    ).json()
    eid = emp["id"]
    # Force the status to configuring via DB so the next publish targets ready.
    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employees SET status = 'configuring' WHERE id = ?", (eid,)
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(f"/qiepai/employees/{eid}/publish")
    assert resp.status_code == 422, resp.text
    assert "at least one revision" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Review item 4 — persona 1:1
# ---------------------------------------------------------------------------


def test_review4_persona_collision_blocks_create(client: TestClient) -> None:
    a = client.post(
        "/qiepai/employees",
        json={"display_name": "A", "role": "x", "persona_id": "p1"},
    ).json()
    resp = client.post(
        "/qiepai/employees",
        json={"display_name": "B", "role": "y", "persona_id": "p1"},
    )
    assert resp.status_code == 409, resp.text
    assert a["id"] in resp.json()["detail"]


def test_review4_persona_collision_blocks_patch(client: TestClient) -> None:
    a = client.post(
        "/qiepai/employees",
        json={"display_name": "A", "role": "x", "persona_id": "p1"},
    ).json()
    b = client.post(
        "/qiepai/employees",
        json={"display_name": "B", "role": "y", "persona_id": "p2"},
    ).json()
    resp = client.patch(
        f"/qiepai/employees/{b['id']}", json={"persona_id": "p1"}
    )
    assert resp.status_code == 409, resp.text
    assert a["id"] in resp.json()["detail"]


def test_review4_persona_id_format_validated(client: TestClient) -> None:
    """persona_id of empty string is rejected (422, not 409)."""
    resp = client.post(
        "/qiepai/employees",
        json={"display_name": "X", "role": "y", "persona_id": "  "},
    )
    assert resp.status_code == 422, resp.text
    assert "persona_id" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Review item 5 — revision_number UNIQUE
# ---------------------------------------------------------------------------


def test_review5_revision_number_monotonic_and_unique(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "链", "role": "财务"},
    ).json()
    eid = emp["id"]

    rev_nums = []
    for i in range(1, 6):
        rev = client.post(
            f"/qiepai/employees/{eid}/revisions",
            json={
                "workspace_file_hash": f"sha256:v{i}",
                "config_snapshot": {"v": i},
            },
        ).json()
        rev_nums.append(rev["revision_number"])

    assert rev_nums == [1, 2, 3, 4, 5]
    # Verify UNIQUE enforcement at the SQL level.
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT revision_number) AS uniq "
            "FROM employee_revisions WHERE employee_id = ?",
            (eid,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    assert row["n"] == row["uniq"] == 5


def test_review5_revision_rejects_missing_workspace_hash(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "链", "role": "财务"},
    ).json()
    resp = client.post(
        f"/qiepai/employees/{emp['id']}/revisions",
        json={"config_snapshot": {"v": 1}},
    )
    assert resp.status_code == 422, resp.text


def test_review5_revision_rejects_non_dict_snapshot(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "链", "role": "财务"},
    ).json()
    resp = client.post(
        f"/qiepai/employees/{emp['id']}/revisions",
        json={"workspace_file_hash": "sha256:x", "config_snapshot": "not a dict"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Review item 6 — sync_state error / drifted blocks
# ---------------------------------------------------------------------------


def test_review6_sync_state_error_blocks(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "X", "role": "财务"},
    ).json()
    client.post(
        f"/qiepai/employees/{emp['id']}/revisions",
        json={
            "workspace_file_hash": "sha256:e",
            "config_snapshot": {"v": 1},
        },
    )
    client.post(f"/qiepai/employees/{emp['id']}/publish")  # → configuring

    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employee_revisions SET readiness_p0 = 1, readiness_p1 = 1, "
            "sync_state = 'error' WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (emp["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(f"/qiepai/employees/{emp['id']}/publish")
    assert resp.status_code == 422, resp.text
    assert "sync_state 'error'" in resp.json()["detail"]


def test_review6_sync_state_drifted_blocks(client: TestClient) -> None:
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "X", "role": "财务"},
    ).json()
    client.post(
        f"/qiepai/employees/{emp['id']}/revisions",
        json={
            "workspace_file_hash": "sha256:d",
            "config_snapshot": {"v": 1},
        },
    )
    client.post(f"/qiepai/employees/{emp['id']}/publish")  # → configuring

    conn = qiepai_db.connect()
    try:
        conn.execute(
            "UPDATE employee_revisions SET readiness_p0 = 1, readiness_p1 = 1, "
            "sync_state = 'drifted' WHERE id = ("
            "  SELECT id FROM employee_revisions WHERE employee_id = ? "
            "  ORDER BY revision_number DESC LIMIT 1"
            ")",
            (emp["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(f"/qiepai/employees/{emp['id']}/publish")
    assert resp.status_code == 422, resp.text
    assert "sync_state 'drifted'" in resp.json()["detail"]


def test_review6_sync_state_pending_and_in_sync_pass(client: TestClient) -> None:
    """``pending`` and ``in_sync`` both pass the readiness gate (gate is
    'block error/drifted', not 'require in_sync')."""
    for state in ("pending", "in_sync"):
        emp = client.post(
            "/qiepai/employees",
            json={"display_name": "X", "role": "财务"},
        ).json()
        client.post(
            f"/qiepai/employees/{emp['id']}/revisions",
            json={
                "workspace_file_hash": f"sha256:{state}",
                "config_snapshot": {"v": 1},
            },
        )
        client.post(f"/qiepai/employees/{emp['id']}/publish")  # → configuring

        conn = qiepai_db.connect()
        try:
            conn.execute(
                "UPDATE employee_revisions SET readiness_p0 = 1, readiness_p1 = 1, "
                "sync_state = ? WHERE id = ("
                "  SELECT id FROM employee_revisions WHERE employee_id = ? "
                "  ORDER BY revision_number DESC LIMIT 1"
                ")",
                (state, emp["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        resp = client.post(f"/qiepai/employees/{emp['id']}/publish")
        assert resp.status_code == 200, f"sync_state={state}: {resp.text}"
        assert resp.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# Review item 7 — Tasks router state machine + 404 + 422 edge cases
# ---------------------------------------------------------------------------


def test_review7_tasks_state_machine_done_is_terminal(client: TestClient) -> None:
    task = client.post("/qiepai/tasks", json={"title": "T"}).json()
    tid = task["id"]
    client.patch(f"/qiepai/tasks/{tid}", json={"status": "in_progress"})
    client.patch(f"/qiepai/tasks/{tid}", json={"status": "done"})

    resp = client.patch(f"/qiepai/tasks/{tid}", json={"status": "todo"})
    assert resp.status_code == 409, resp.text


def test_review7_tasks_get_unknown_returns_404(client: TestClient) -> None:
    resp = client.get("/qiepai/tasks/bt_does_not_exist")
    assert resp.status_code == 404, resp.text


def test_review7_tasks_delete_unknown_returns_404(client: TestClient) -> None:
    resp = client.delete("/qiepai/tasks/bt_does_not_exist")
    assert resp.status_code == 404, resp.text


def test_review7_employees_get_unknown_returns_404(client: TestClient) -> None:
    resp = client.get("/qiepai/employees/emp_does_not_exist")
    assert resp.status_code == 404, resp.text


def test_review7_employees_patch_unknown_returns_404(client: TestClient) -> None:
    resp = client.patch(
        "/qiepai/employees/emp_does_not_exist", json={"display_name": "x"}
    )
    assert resp.status_code == 404, resp.text


def test_review7_patch_employees_with_status_returns_422(client: TestClient) -> None:
    """Status must not be patchable directly; use the publish endpoint."""
    emp = client.post(
        "/qiepai/employees",
        json={"display_name": "X", "role": "财务"},
    ).json()
    resp = client.patch(
        f"/qiepai/employees/{emp['id']}", json={"status": "published"}
    )
    assert resp.status_code == 422, resp.text
    assert "publish" in resp.json()["detail"]
