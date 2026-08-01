"""qiepai · Phase ❹ backend bugfix regression tests.

Regression-net for the ❹ backend bugfix PR. Currently covers:

* **Bug 1 (B1)** — ``_row_to_dict`` must surface ``industry: str | None``
  on the wire (per spec ❹ section 1) instead of swallowing NULL behind
  an implicit ``dict(row)`` passthrough. The service layer previously
  decoded ``payload`` + ``tags`` (JSON TEXT columns) but treated
  ``industry`` as a plain ``dict(row)`` passthrough. While the runtime
  value was already ``None`` for NULL rows, the explicit
  ``industry: None`` assignment makes the type contract self-documenting
  and shields the field from silent regressions if someone later
  special-cases ``out.setdefault("industry", ...)`` or similar.

The test asserts two complementary things:

1. The module-level service helper surfaces ``"industry": None`` when
   the column is NULL (unit-style; pure DB row → dict).
2. The HTTP GET endpoint surfaces ``"industry": null`` in the JSON
   body for a template inserted with ``industry=None`` (integration-style;
   end-to-end wire shape).

Both run against a per-test temp DB (matches the
``test_marketplace_router`` fixture pattern: monkeypatch
``QIEPAI_ENTERPRISE_DB_PATH`` + ``get_db_path``, run migrations, seed
builtins). This keeps the new test order-independent and safe to run
under ``-p no:randomly``.

NOTE: this file is add-only — it does NOT touch any pre-existing test
files in ``apps/api/tests/`` (the standing reviewer instruction).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.qiepai import marketplace as marketplace_routes
from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai import migration_runner
from apps.api.services.qiepai.marketplace import service as marketplace_service


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirrors test_marketplace_router conventions)
# ---------------------------------------------------------------------------


@pytest.fixture
def qiepai_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the qiepai service at a fresh temp DB + bootstrap schema + seed."""
    db_file = tmp_path / "qiepai-marketplace-bugfix.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    asyncio.run(migration_runner.run_pending_migrations())
    asyncio.run(marketplace_service.seed_builtin_templates())
    return db_file


@pytest.fixture
def client(qiepai_db_path: Path) -> TestClient:
    """Mount the marketplace router under ``/qiepai`` like the real app."""
    app = FastAPI()
    app.include_router(marketplace_routes.router, prefix="/qiepai")
    return TestClient(app)


# ---------------------------------------------------------------------------
# B1 — ``industry: str | None`` explicit passthrough through ``_row_to_dict``
# ---------------------------------------------------------------------------


def test_industry_null_in_row(qiepai_db_path: Path) -> None:
    """B1 regression: a template row with ``industry IS NULL`` must surface
    ``"industry": None`` through ``_row_to_dict``.

    The function does ``out = dict(row)`` which already maps NULL TEXT
    columns to ``None``; the B1 fix adds an explicit
    ``if out.get("industry") is None: out["industry"] = None`` line so
    the wire contract (``industry: str | None``, per spec ❹ §1) is
    self-documenting and the field is not silently dropped by future
    refactors (e.g. anyone adding ``out.setdefault("industry", "")``
    would otherwise break the nullable contract — this test fails first
    so the breakage is loud, not silent).

    We seed a NULL industry via a raw INSERT (bypassing
    ``create_template`` which strips whitespace and maps ``"   "`` to
    ``None`` but a literal ``NULL`` also exercises the DB → dict path
    the same way) and then walk the public APIs that funnel into
    ``_row_to_dict``:

    * ``marketplace_service.get_template`` (sync) → dict with
      ``"industry": None``.
    * ``GET /qiepai/marketplace/templates/<id>`` → JSON body with
      ``"industry": null``.

    Both pass before the fix too (the runtime value is the same), so
    this test is primarily a **regression guard**: if anyone removes
    the explicit None passthrough line + also starts coercing NULL
    elsewhere, this fails immediately.
    """
    raw_id = "stpl_b1_null_industry"
    conn = qiepai_db.connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scene_templates ("
            "  id, enterprise_id, name, description, category, industry,"
            "  payload, tags, source, enabled, created_by"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (
                raw_id,
                marketplace_service.DEFAULT_ENTERPRISE_ID,
                "B1 null-industry template",
                "industry is intentionally NULL for B1 regression net",
                "ops",
                None,  # the NULL under test
                '{"avatar_id": "a", "voice_id": "b"}',
                "[]",
                "user",
                "tester",
            ),
        )
        conn.commit()
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()

    # 1. Service-layer path: ``get_template`` returns ``"industry": None``
    #    (not missing key, not empty string, not a sentinel).
    body = asyncio.run(marketplace_service.get_template(raw_id))
    assert "industry" in body, body.keys()
    assert body["industry"] is None, body["industry"]
    # Defence-in-depth: the value must be a literal None, not a derived
    # "" / 0 / "null" string — the wire contract demands the JSON null.
    assert body["industry"] in (None,)  # type-guard for mypy strict

    # 2. Wire-shape path: the HTTP GET surfaces ``"industry": null`` in
    #    the JSON body (i.e. ``resp.json()["industry"]`` is ``None``,
    #    not the string ``"null"`` and not the key missing).
    app = FastAPI()
    app.include_router(marketplace_routes.router, prefix="/qiepai")
    test_client = TestClient(app)
    resp = test_client.get(f"/qiepai/marketplace/templates/{raw_id}")
    assert resp.status_code == 200, resp.text
    json_body = resp.json()
    assert "industry" in json_body
    assert json_body["industry"] is None
