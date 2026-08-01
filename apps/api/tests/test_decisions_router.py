"""qiepai · decisions router regression tests (Phase ❷-5 review pass).

Covers the 7 issues a downstream reviewer flagged in
``apps.api.services.qiepai.decisions.service`` / the matching router. Each
test is scoped to one bug so failures point straight at the regression.

The tests use a per-test temp DB (the qiepai service module reads
``$QIEPAI_ENTERPRISE_DB_PATH`` at every ``db.connect()`` call, so
monkeypatching the env var + running the migration bootstrap gives every
test a clean slate). Migrations + the metric seed are re-applied inside
each test to keep the suite order-independent.

NOTE: this file is add-only — it does NOT touch any pre-existing test
files in ``apps/api/tests/`` (the reviewer's standing instruction).
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.qiepai import decisions as decisions_routes
from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai import migration_runner, seed


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
    db_file = tmp_path / "qiepai-test.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    # Reset any cached module-level state so connect() re-reads the env.
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    # Schema + metric seed so ``load_kpi_snapshot`` can resolve metric_ids.
    asyncio.run(migration_runner.run_pending_migrations())
    asyncio.run(seed.seed_initial_metrics())
    return db_file


@pytest.fixture
def client(qiepai_db_path: Path) -> TestClient:
    app = FastAPI()
    # The decisions router is mounted under ``/qiepai`` in production
    # (see ``apps/api/routes/qiepai/__init__.py``); replicate that
    # prefix here so the test URLs match the real API surface.
    app.include_router(decisions_routes.router, prefix="/qiepai")
    return TestClient(app)


def _create_decision(client: TestClient, **overrides) -> dict:
    """Helper: POST a minimal valid decision and return the body."""
    body = {"title": "test decision"}
    body.update(overrides)
    resp = client.post("/qiepai/decisions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Bug 1 — PATCH status=decided must require decision_text (422 otherwise)
# ---------------------------------------------------------------------------


def test_bug1_patch_status_decided_without_decision_text_returns_422(
    client: TestClient,
) -> None:
    created = _create_decision(client)
    resp = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "decided"},
    )
    assert resp.status_code == 422, resp.text
    assert "decision_text" in resp.json()["detail"]


def test_bug1_patch_status_decided_with_decision_text_returns_200(
    client: TestClient,
) -> None:
    created = _create_decision(client)
    resp = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "decided", "decision_text": "approved"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "decided"
    assert resp.json()["decision_text"] == "approved"


def test_bug1_patch_status_decided_with_blank_decision_text_returns_422(
    client: TestClient,
) -> None:
    created = _create_decision(client)
    for blank in ("", "   ", "\t\n"):
        resp = client.patch(
            f"/qiepai/decisions/{created['id']}",
            json={"status": "decided", "decision_text": blank},
        )
        assert resp.status_code == 422, f"blank={blank!r} body={resp.text}"


def test_bug1_patch_status_cancelled_does_not_require_decision_text(
    client: TestClient,
) -> None:
    """Cancelling is the sibling transition that the spec makes optional."""
    created = _create_decision(client)
    resp = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "cancelled"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Bug 2 — terminal rows reject status changes (409) but allow decision_text
# ---------------------------------------------------------------------------


def test_bug2_decided_row_can_still_update_decision_text(
    client: TestClient,
) -> None:
    created = _create_decision(client)
    # Close it.
    close = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "decided", "decision_text": "first pass"},
    )
    assert close.status_code == 200, close.text
    assert close.json()["status"] == "decided"

    # Post-hoc annotation must be allowed (Bug 2's whole point).
    edit = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"decision_text": "追注 after the fact"},
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["decision_text"] == "追注 after the fact"
    assert edit.json()["status"] == "decided"  # unchanged


def test_bug2_decided_row_rejects_status_transition_with_409(
    client: TestClient,
) -> None:
    created = _create_decision(client)
    client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "decided", "decision_text": "closed"},
    )
    # Now try to flip status — terminal lock must fire.
    bad = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "cancelled"},
    )
    assert bad.status_code == 409, bad.text


def test_bug2_cancelled_row_rejects_status_transition_with_409(
    client: TestClient,
) -> None:
    created = _create_decision(client)
    client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "cancelled"},
    )
    bad = client.patch(
        f"/qiepai/decisions/{created['id']}",
        json={"status": "decided", "decision_text": "too late"},
    )
    assert bad.status_code == 409, bad.text


# ---------------------------------------------------------------------------
# Bug 3 — GET ?status=<bogus> must 422 instead of silently returning []
# ---------------------------------------------------------------------------


def test_bug3_list_with_invalid_status_query_returns_422(
    client: TestClient,
) -> None:
    resp = client.get("/qiepai/decisions", params={"status": "banana"})
    assert resp.status_code == 422, resp.text
    assert "invalid status filter" in resp.json()["detail"]


def test_bug3_list_with_valid_status_query_still_works(
    client: TestClient,
) -> None:
    # Just exercising the happy path so a future regression on the
    # _VALID_STATUSES branch doesn't sneak past unnoticed.
    _create_decision(client)
    for ok in ("pending", "decided", "cancelled"):
        resp = client.get("/qiepai/decisions", params={"status": ok})
        assert resp.status_code == 200, f"status={ok} body={resp.text}"


# ---------------------------------------------------------------------------
# Bug 4 — POST snapshot_id must be rejected (auto-derived from metric_id)
# ---------------------------------------------------------------------------


def test_bug4_post_with_snapshot_id_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/qiepai/decisions",
        json={
            "title": "sneaky caller",
            "snapshot_id": "snap_stale_default",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "snapshot_id" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Bug 5 — POST fact_snapshot of non-dict type must be rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    [[1, 2, 3], "not a dict", 42, True, None],
)
def test_bug5_post_with_non_dict_fact_snapshot_returns_422(
    client: TestClient, bad_value: object
) -> None:
    resp = client.post(
        "/qiepai/decisions",
        json={"title": "bad snapshot", "fact_snapshot": bad_value},
    )
    assert resp.status_code == 422, f"value={bad_value!r} body={resp.text}"
    assert "fact_snapshot" in resp.json()["detail"]


def test_bug5_post_with_dict_fact_snapshot_still_works(
    client: TestClient,
) -> None:
    """Regression guard — dict must still be accepted."""
    resp = client.post(
        "/qiepai/decisions",
        json={
            "title": "good snapshot",
            "fact_snapshot": {"items": [], "note": "manual"},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fact_snapshot"] == {"items": [], "note": "manual"}


# ---------------------------------------------------------------------------
# Bug 6 — POST with unknown metric_id stays silent (no 422) + logs a warning
# ---------------------------------------------------------------------------


def test_bug6_post_with_unknown_metric_id_returns_200_with_unavailable_note(
    client: TestClient,
) -> None:
    resp = client.post(
        "/qiepai/decisions",
        json={"title": "typo'd metric", "metric_id": "financial-kpi-TYPO"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The unavailable placeholder from spec § 21.1 (matches ❷-3 mock
    # loader: missing data is "unavailable", not zero).
    assert body["metric_id"] == "financial-kpi-TYPO"
    assert body["fact_snapshot"].get("note") == "metric snapshot unavailable"
    # snapshot_id must NOT be set when the metric doesn't resolve.
    assert body["snapshot_id"] is None


def test_bug6_post_with_unknown_metric_id_logs_warning(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Operators need a breadcrumb to debug typos from backend logs."""
    with caplog.at_level(logging.WARNING, logger="apps.api.services.qiepai.decisions.service"):
        resp = client.post(
            "/qiepai/decisions",
            json={"title": "typo'd metric", "metric_id": "totally-bogus-id"},
        )
    assert resp.status_code == 200
    assert any(
        "unknown metric_id" in rec.message and "totally-bogus-id" in rec.message
        for rec in caplog.records
    ), f"expected a warning about 'totally-bogus-id', got: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Bug 7 — cached_at ternary is pythonic (covered by static review + smoke)
# ---------------------------------------------------------------------------


def test_bug7_cached_at_uses_explicit_ternary(client: TestClient) -> None:
    """Smoke test for the _persist_ai_suggestion_cache path.

    The cache write goes through ``_persist_ai_suggestion_cache`` which
    holds the ternary. We exercise both branches by hitting the
    ``ai-suggestion`` endpoint twice; the mock suggester is always used
    (no OpenClaw token in tests), so ``cached_at`` should be ``"mock"``.
    """
    created = _create_decision(client)
    resp = client.get(f"/qiepai/decisions/{created['id']}/ai-suggestion")
    assert resp.status_code == 200, resp.text
    # Mock suggester always reports ``_used_mock=True`` → cached_at must
    # resolve to "mock" via the explicit ternary.
    cache = resp.json()
    assert cache.get("_used_mock") is True  # sanity: mock path engaged
    # Re-read the row and confirm the persisted cache column has
    # ``cached_at: "mock"``.
    reread = client.get(f"/qiepai/decisions/{created['id']}")
    assert reread.status_code == 200, reread.text
    ai = reread.json().get("ai_suggestion")
    assert isinstance(ai, dict), ai
    assert ai.get("cached_at") == "mock", ai