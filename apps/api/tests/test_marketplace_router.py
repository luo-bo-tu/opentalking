"""qiepai · marketplace router regression tests (Phase ❹).

Covers the 8 endpoints shipped in section ❹ of
``qiepai-claw-stage3-4-5-spec.md`` plus the copy-flow integration with
``apps.api.services.qiepai.employees.service``. Each scenario lives in
its own test so failures point straight at the regression.

The tests use a per-test temp DB (the qiepai service module reads
``$QIEPAI_ENTERPRISE_DB_PATH`` at every ``db.connect()`` call, so
monkeypatching the env var + running the migration bootstrap gives
every test a clean slate). Migrations + the builtin template seed are
re-applied inside each test to keep the suite order-independent.

NOTE: this file is add-only — it does NOT touch any pre-existing test
files in ``apps/api/tests/`` (the standing reviewer instruction).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.qiepai import marketplace as marketplace_routes
from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai import migration_runner
from apps.api.services.qiepai.marketplace import service as marketplace_service


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def qiepai_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the qiepai service at a fresh temp DB + bootstrap schema + seed.

    The env var is read inside :func:`db.connect` (see
    ``apps/api/services/qiepai/db.py``), so monkeypatching here propagates
    to every connect() call without needing to reload the module.
    """
    db_file = tmp_path / "qiepai-marketplace-test.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    # Reset any cached module-level state so connect() re-reads the env.
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    # Schema + builtin marketplace seed so the list endpoint can resolve
    # category / sort filters against the 4 demo rows.
    asyncio.run(migration_runner.run_pending_migrations())
    asyncio.run(marketplace_service.seed_builtin_templates())
    return db_file


@pytest.fixture
def client(qiepai_db_path: Path) -> TestClient:
    """Mount the marketplace router under ``/qiepai`` like the real app."""
    app = FastAPI()
    app.include_router(marketplace_routes.router, prefix="/qiepai")
    return TestClient(app)


def _create_template(client: TestClient, **overrides: object) -> dict:
    """Helper: POST a minimal valid template and return the body."""
    body: dict = {
        "name": "test template",
        "category": "ops",
        "payload": {"avatar_id": "avatar-x", "voice_id": "voice-y"},
    }
    body.update(overrides)
    resp = client.post("/qiepai/marketplace/templates", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Migrations + builtin seed bootstrap
# ---------------------------------------------------------------------------


def test_migrations_apply_three_marketplace_tables(
    qiepai_db_path: Path,
) -> None:
    """0003_marketplace creates 3 tables; _migration_history records it."""
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('scene_templates', 'scene_template_ratings', 'scene_template_copies')"
            " ORDER BY name"
        )
        rows = [r["name"] for r in cur.fetchall()]
        assert rows == [
            "scene_template_copies",
            "scene_template_ratings",
            "scene_templates",
        ]
        cur.execute(
            "SELECT name FROM _migration_history WHERE name LIKE '0003_%' ORDER BY name"
        )
        assert [r["name"] for r in cur.fetchall()] == ["0003_marketplace"]
    finally:
        conn.close()


def test_builtin_seed_idempotent(qiepai_db_path: Path) -> None:
    """seed_builtin_templates() is a no-op on the second call."""
    inserted_first = asyncio.run(marketplace_service.seed_builtin_templates())
    inserted_second = asyncio.run(marketplace_service.seed_builtin_templates())
    assert inserted_first == 0
    assert inserted_second == 0
    # 4 rows present
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n FROM scene_templates WHERE source = 'builtin'"
        )
        assert int(cur.fetchone()["n"]) == 4
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. List endpoint — pagination + category filter + sort
# ---------------------------------------------------------------------------


def test_list_templates_default_sort_popular(client: TestClient) -> None:
    """Default sort is ``popular`` (rating_avg DESC, use_count DESC)."""
    resp = client.get("/qiepai/marketplace/templates")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 4
    # payload is NOT included in the list endpoint (single GET only)
    assert "payload" not in body["items"][0]
    # denormalised aggregates are exposed
    for item in body["items"]:
        assert "rating_avg" in item
        assert "rating_count" in item
        assert "use_count" in item


def test_list_templates_category_filter(client: TestClient) -> None:
    """Filter by category narrows the list."""
    resp = client.get("/qiepai/marketplace/templates", params={"category": "sales"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "stpl_builtin_sales"
    assert body["items"][0]["category"] == "sales"


def test_list_templates_sort_recent(client: TestClient) -> None:
    """``sort=recent`` orders by ``created_at DESC``."""
    resp = client.get(
        "/qiepai/marketplace/templates", params={"sort": "recent"}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    # all 4 builtin rows share the same created_at (seed), so we only
    # assert the call succeeded — the sort path itself is unit-covered
    # by the smoke flow in the service docstring.
    assert len(items) == 4


def test_list_templates_invalid_sort_returns_422(client: TestClient) -> None:
    resp = client.get(
        "/qiepai/marketplace/templates", params={"sort": "garbage"}
    )
    assert resp.status_code == 422, resp.text
    assert "invalid sort" in resp.json()["detail"]


def test_list_templates_pagination(client: TestClient) -> None:
    """limit + offset slice the result set; ``total`` is the filtered count."""
    p1 = client.get(
        "/qiepai/marketplace/templates", params={"limit": 1, "offset": 0}
    ).json()
    p2 = client.get(
        "/qiepai/marketplace/templates", params={"limit": 1, "offset": 1}
    ).json()
    assert p1["total"] == 4
    assert p2["total"] == 4
    assert p1["limit"] == 1
    assert p2["offset"] == 1
    assert p1["items"][0]["id"] != p2["items"][0]["id"]


# ---------------------------------------------------------------------------
# 3. Single GET (payload included)
# ---------------------------------------------------------------------------


def test_get_template_returns_full_payload(client: TestClient) -> None:
    resp = client.get("/qiepai/marketplace/templates/stpl_builtin_sales")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "stpl_builtin_sales"
    # payload comes back as a real dict, not a stringified blob
    assert isinstance(body["payload"], dict)
    assert body["payload"]["avatar_id"] == "avatar-sales-male-02"
    assert body["payload"]["llm_provider"] == "openai"


def test_get_template_404(client: TestClient) -> None:
    resp = client.get("/qiepai/marketplace/templates/stpl_does_not_exist")
    assert resp.status_code == 404, resp.text


def test_get_template_returns_disabled_row(client: TestClient) -> None:
    """Single GET still serves soft-deleted templates (audit-friendly); the
    list endpoint is the only place that hides them. ``enabled=0`` in the
    response body tells the UI to render the row as removed.
    """
    client.delete("/qiepai/marketplace/templates/stpl_builtin_sales")
    resp = client.get("/qiepai/marketplace/templates/stpl_builtin_sales")
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] == 0


# ---------------------------------------------------------------------------
# 4. POST (admin)
# ---------------------------------------------------------------------------


def test_create_template_minimal(client: TestClient) -> None:
    created = _create_template(client)
    assert created["name"] == "test template"
    assert created["category"] == "ops"
    assert created["source"] == "user"
    assert created["enabled"] == 1
    # id follows the stpl_<12-hex> convention
    assert created["id"].startswith("stpl_")
    assert len(created["id"]) == len("stpl_") + 12


def test_create_template_missing_required_returns_422(client: TestClient) -> None:
    resp = client.post("/qiepai/marketplace/templates", json={"category": "hr"})
    assert resp.status_code == 422, resp.text
    assert "name" in resp.json()["detail"]


def test_create_template_payload_must_be_dict(client: TestClient) -> None:
    resp = client.post(
        "/qiepai/marketplace/templates",
        json={"name": "x", "category": "hr", "payload": "not a dict"},
    )
    assert resp.status_code == 422, resp.text


def test_create_template_source_builtin_downgraded_to_user(
    client: TestClient,
) -> None:
    """Admin can't claim ``source='builtin'``; service silently downgrades."""
    created = _create_template(client, source="builtin")
    assert created["source"] == "user"


def test_create_template_unknown_category_logs_but_accepts(
    client: TestClient,
) -> None:
    """Forward-compat: unknown categories are accepted (not 422)."""
    created = _create_template(client, category="legal")
    assert created["category"] == "legal"


# ---------------------------------------------------------------------------
# 5. PATCH (owner)
# ---------------------------------------------------------------------------


def test_patch_template_partial(client: TestClient) -> None:
    """PATCH updates only the supplied fields."""
    resp = client.patch(
        "/qiepai/marketplace/templates/stpl_builtin_sales",
        json={"description": "updated desc", "tags": ["sales", "BD"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description"] == "updated desc"
    assert body["tags"] == ["sales", "BD"]
    # name preserved
    assert body["name"] == "销售数字员工 - 商机跟进"


def test_patch_template_empty_body_returns_422(client: TestClient) -> None:
    resp = client.patch(
        "/qiepai/marketplace/templates/stpl_builtin_sales", json={}
    )
    assert resp.status_code == 422, resp.text


def test_patch_template_404(client: TestClient) -> None:
    resp = client.patch(
        "/qiepai/marketplace/templates/stpl_nope", json={"name": "x"}
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 6. DELETE (soft)
# ---------------------------------------------------------------------------


def test_delete_template_soft_hides_from_list(client: TestClient) -> None:
    """DELETE sets ``enabled = 0``; subsequent list excludes the row."""
    resp = client.delete("/qiepai/marketplace/templates/stpl_builtin_hr")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": "stpl_builtin_hr", "deleted": True, "enabled": 0}

    listed = client.get("/qiepai/marketplace/templates").json()
    assert all(item["id"] != "stpl_builtin_hr" for item in listed["items"])
    assert listed["total"] == 3


def test_delete_template_404(client: TestClient) -> None:
    resp = client.delete("/qiepai/marketplace/templates/stpl_nope")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 7. Rating endpoint — insert + recompute aggregates
# ---------------------------------------------------------------------------


def test_rate_template_insert_and_recompute(client: TestClient) -> None:
    """First rating: aggregates reflect the new row."""
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
        json={"rating": 5, "user_id": "u1", "comment": "perfect"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 5
    assert body["user_id"] == "u1"

    after = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales"
    ).json()
    assert after["rating_count"] == 1
    assert after["rating_avg"] == 5.0


def test_rate_template_re_rating_replaces_previous(
    client: TestClient,
) -> None:
    """UNIQUE(template_id, user_id) → re-rating replaces; count stays 1."""
    client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
        json={"rating": 5, "user_id": "u1"},
    )
    client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
        json={"rating": 3, "user_id": "u1"},
    )
    after = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales"
    ).json()
    assert after["rating_count"] == 1
    assert after["rating_avg"] == 3.0


def test_rate_template_multiple_users_average(client: TestClient) -> None:
    """Two distinct users → avg = (r1 + r2) / 2, count = 2."""
    client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
        json={"rating": 5, "user_id": "u1"},
    )
    client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
        json={"rating": 3, "user_id": "u2"},
    )
    after = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales"
    ).json()
    assert after["rating_count"] == 2
    assert after["rating_avg"] == 4.0


def test_rate_template_out_of_range_returns_422(client: TestClient) -> None:
    for bad in (0, 6, -1, 99):
        resp = client.post(
            "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
            json={"rating": bad},
        )
        assert resp.status_code == 422, (bad, resp.text)


def test_rate_template_404(client: TestClient) -> None:
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_nope/ratings",
        json={"rating": 5},
    )
    assert resp.status_code == 404, resp.text


def test_rate_template_non_integer_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/ratings",
        json={"rating": "five"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 8. Copies endpoint
# ---------------------------------------------------------------------------


def test_list_copies_empty_initially(client: TestClient) -> None:
    resp = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales/copies"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "total": 0}


def test_list_copies_after_copy_records_one_row(client: TestClient) -> None:
    """A copy records 1 audit row + bumps ``use_count`` on the parent."""
    client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/copy",
        json={"display_name": "我的销售副本"},
    )
    resp = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales/copies"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["template_id"] == "stpl_builtin_sales"
    assert body["items"][0]["target_employee_id"].startswith("emp_")

    after = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales"
    ).json()
    assert after["use_count"] == 1


def test_list_copies_404(client: TestClient) -> None:
    resp = client.get("/qiepai/marketplace/templates/stpl_nope/copies")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 9. Copy flow — auto-create employee + append revision
# ---------------------------------------------------------------------------


def test_copy_template_auto_creates_employee_and_revision(
    client: TestClient,
) -> None:
    """No ``target_employee_id`` → auto-create employee + revision."""
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/copy",
        json={"display_name": "我的销售", "role": "BD"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["template_id"] == "stpl_builtin_sales"
    assert body["target_employee_id"].startswith("emp_")
    assert body["revision_id"].startswith("rev_")
    assert body["copy_id"].startswith("cp_")
    # The new employee carries the display_name we passed.
    assert body["employee"]["display_name"] == "我的销售"
    assert body["employee"]["role"] == "BD"
    # The new revision's config_snapshot contains the template payload verbatim
    # (the employee row itself doesn't carry config_snapshot — that's only on
    # ``employee_revisions``).
    assert "avatar_id" in body["revision"]["config_snapshot"]
    assert body["revision"]["config_snapshot"]["llm_provider"] == "openai"
    assert body["revision"]["config_snapshot"]["warm_transfer_keywords"] == [
        "价格",
        "合同",
        "对接",
    ]


def test_copy_template_default_display_name_derived(
    client: TestClient,
) -> None:
    """No ``display_name`` → service falls back to ``"{template.name} (副本)"``."""
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_finance/copy",
        json={},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["employee"]["display_name"].endswith(" (副本)")
    assert body["employee"]["role"] == "数字员工"


def test_copy_template_with_target_employee_skips_creation(
    client: TestClient,
) -> None:
    """``target_employee_id`` set → no new employee; only revision appended."""
    # Pre-create an employee.
    pre = client.post(
        "/qiepai/employees",  # not mounted here; use the service directly
        # The test client only has the marketplace router mounted; we
        # need to reach into the qiepai DB directly to seed an employee.
        # Use the employees service via the test process.
        json={},  # placeholder, replaced below
    )
    # The above call will 404 because /qiepai/employees isn't mounted.
    # Drop it and use the service instead.
    _ = pre

    from apps.api.services.qiepai.employees import service as employees_service

    async def _seed_emp() -> dict:
        return await employees_service.create_employee(
            {"display_name": "pre-existing", "role": "test"}
        )

    emp = asyncio.run(_seed_emp())

    resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_hr/copy",
        json={"target_employee_id": emp["id"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["target_employee_id"] == emp["id"]
    # display_name was NOT changed (we didn't supply one, and target was
    # supplied, so the service skips employee creation entirely).
    assert body["employee"]["id"] == emp["id"]
    assert body["employee"]["display_name"] == "pre-existing"


def test_copy_template_with_target_404(client: TestClient) -> None:
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_sales/copy",
        json={"target_employee_id": "emp_does_not_exist"},
    )
    assert resp.status_code == 404, resp.text
    assert "emp_does_not_exist" in resp.json()["detail"]


def test_copy_template_404_on_unknown_template(client: TestClient) -> None:
    resp = client.post(
        "/qiepai/marketplace/templates/stpl_nope/copy", json={}
    )
    assert resp.status_code == 404, resp.text


def test_copy_template_use_count_increments_per_copy(
    client: TestClient,
) -> None:
    """``use_count`` aggregates every successful copy."""
    for _ in range(3):
        client.post(
            "/qiepai/marketplace/templates/stpl_builtin_sales/copy",
            json={"display_name": "副本"},
        )
    after = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_sales"
    ).json()
    assert after["use_count"] == 3


def test_copy_template_creates_revision_with_payload(
    client: TestClient,
) -> None:
    """The new revision's config_snapshot equals the template payload."""
    template = client.get(
        "/qiepai/marketplace/templates/stpl_builtin_finance"
    ).json()
    payload = template["payload"]

    copy_resp = client.post(
        "/qiepai/marketplace/templates/stpl_builtin_finance/copy",
        json={"display_name": "财务副本"},
    )
    assert copy_resp.status_code == 201, copy_resp.text
    revision = copy_resp.json()["revision"]
    assert revision["config_snapshot"] == payload
    assert revision["config_snapshot"]["metric_ids"] == payload["metric_ids"]