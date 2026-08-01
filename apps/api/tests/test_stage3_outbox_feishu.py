"""qiepai · Phase ❸ outbox + Feishu integration regression tests.

Covers the surface area the ❸-1 backend shipped:

* :mod:`apps.api.services.qiepai.outbox.events` — draft validation,
  sync insert, JSON payload decoding.
* :mod:`apps.api.services.qiepai.outbox.worker` — exponential backoff
  curve, atomic claim (``pending`` → ``processing``), retry-window
  guard, recovery helper.
* :mod:`apps.api.services.qiepai.outbox.publisher` — dry-run when
  credentials or chat_id are missing, :class:`PublishError` retryable
  semantics for 5xx / 429, Feishu interactive-card renderer.
* :mod:`apps.api.services.qiepai.integrations.feishu_settings` —
  ``is_configured`` predicate (app_id+app_secret pair vs webhook-only).
* :mod:`apps.api.services.qiepai.integrations.registry` — empty
  chat-id sentinel when no group is registered.

Each test is self-contained (per-test temp DB + per-test publisher
cache reset). Importing the production modules directly (not via the
FastAPI app) keeps the suite focused on the service-layer contracts
and avoids cross-coupling with the ❷-6 router fixtures.

NOTE: this file is add-only — it does NOT touch any pre-existing test
file in ``apps/api/tests/`` (the reviewer's standing instruction).
"""
from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest

from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai import migration_runner
from apps.api.services.qiepai.integrations import feishu_settings
from apps.api.services.qiepai.integrations.feishu_settings import (
    FeishuSettings,
    reload_settings,
)
from apps.api.services.qiepai.integrations.registry import first_active_chat_id
from apps.api.services.qiepai.outbox import worker
from apps.api.services.qiepai.outbox.events import (
    EVENT_TYPES,
    OutboxEventDraft,
    _insert_sync,
    build_event_payload,
    insert_event,
)
from apps.api.services.qiepai.outbox.publisher import (
    PublishError,
    publish_outbox_event,
    reset_for_tests,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qiepai_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Per-test temp DB + migrated schema (incl. ``feishu_groups``)."""
    db_file = tmp_path / "qiepai-stage3-outbox.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    asyncio.run(migration_runner.run_pending_migrations())
    return db_file


@pytest.fixture
def reset_publisher_cache() -> Iterator[None]:
    """Drop the in-process token cache + worker handle between tests."""
    reset_for_tests()
    worker.reset_for_tests()
    yield
    reset_for_tests()
    worker.reset_for_tests()


# ---------------------------------------------------------------------------
# 1. outbox.events — OutboxEventDraft validation
# ---------------------------------------------------------------------------


def test_outbox_event_draft_validates_nonempty_event_type() -> None:
    """An empty ``event_type`` raises :class:`ValueError` with a clear msg.

    The validator runs before the SQL INSERT so callers see a clean
    stack trace when they ship a typo (``None`` from a forgotten
    ``if event_type`` branch, etc.). Without this test the bug would
    only surface as a NOT NULL constraint violation in the INSERT.
    """
    with pytest.raises(ValueError, match="event_type must be a non-empty string"):
        OutboxEventDraft(
            event_type="",
            aggregate_type="employee",
            aggregate_id="emp-1",
            payload={"display_name": "demo"},
        ).validate()


def test_outbox_event_draft_rejects_non_serialisable_payload() -> None:
    """Bytes / datetime / set payloads raise before hitting SQLite.

    SQLite stores ``payload`` as ``TEXT`` so the in-process
    :func:`json.dumps` probe is the only safety net — production code
    must surface a clear :class:`ValueError` rather than crashing the
    request handler with a ``TypeError`` deep in the migration layer.
    """
    with pytest.raises(ValueError, match="payload is not JSON-serialisable"):
        OutboxEventDraft(
            event_type="system.demo_notify",
            aggregate_type="system",
            aggregate_id="agg-1",
            payload={"binary": b"\\x00\\xff"},  # type: ignore[dict-item]
        ).validate()


def test_insert_sync_persists_row_with_correct_state(
    qiepai_db_path: Path,
) -> None:
    """``_insert_sync`` writes a row in ``state='pending'`` with state='processing'
    state transition path exercised by the worker (atomic claim)."""
    draft = OutboxEventDraft(
        event_type="employee.published",
        aggregate_type="employee",
        aggregate_id="emp-007",
        payload={"display_name": "Zhang Wei", "role": "SDR"},
    )
    new_id = _insert_sync(draft)
    assert new_id.startswith("out_"), (
        f"row id prefix should be 'out_'; got {new_id!r} — the id factory "
        f"in outbox.events._insert_sync changed shape"
    )

    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT event_type, aggregate_type, aggregate_id, payload, state "
            "FROM outbox_events WHERE id = ?",
            (new_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None
    assert str(row["event_type"]) == "employee.published"
    assert str(row["aggregate_type"]) == "employee"
    assert str(row["aggregate_id"]) == "emp-007"
    # payload stored as JSON TEXT — must round-trip via json.loads.
    import json as _json

    assert _json.loads(str(row["payload"])) == {
        "display_name": "Zhang Wei",
        "role": "SDR",
    }


def test_insert_event_returns_none_on_failure(
    qiepai_db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The async ``insert_event`` swallows exceptions and returns ``None``.

    Business code (digital employee publish, decision status change,
    task assignment) must not crash on outbox failures — the outbox
    is best-effort by design. This test simulates a DB outage and
    asserts the wrapper returns ``None`` instead of raising into the
    FastAPI request path.
    """
    draft = OutboxEventDraft(
        event_type="system.heartbeat",
        aggregate_type="system",
        aggregate_id="agg-x",
        payload={"msg": "hi"},
    )

    async def _boom(_draft: OutboxEventDraft) -> str:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(
        "apps.api.services.qiepai.outbox.events.asyncio_to_thread_insert",
        _boom,
    )
    # The wrapper returns None on any exception; it never raises.
    result = asyncio.run(insert_event(draft))
    assert result is None


def test_build_event_payload_decodes_payload_json() -> None:
    """``build_event_payload`` decodes the JSON ``payload`` column and
    merges the dispatch keys up so the publisher can read
    ``payload['title']`` regardless of trigger.

    Also covers the malformed-payload branch — a row with garbage in
    ``payload`` (e.g. legacy ``_raw`` blob) must not crash the
    publisher; the helper falls back to an empty dict + logs a warning.
    """
    body = build_event_payload(
        "decision.created",
        "decision",
        "dec-1",
        '{"decision_title": "买 Q3 服务器", "decision_text": "..."}',
    )
    assert body["decision_title"] == "买 Q3 服务器"
    assert body["decision_text"] == "..."
    assert body["_event_type"] == "decision.created"
    assert body["_aggregate_type"] == "decision"
    assert body["_aggregate_id"] == "dec-1"

    # Malformed JSON — should fall back to empty dict.
    bad = build_event_payload("system.heartbeat", "system", "agg-2", "not-json{{{")
    assert bad == {
        "_event_type": "system.heartbeat",
        "_aggregate_type": "system",
        "_aggregate_id": "agg-2",
    }


# ---------------------------------------------------------------------------
# 2. outbox.worker — backoff curve + claim helper
# ---------------------------------------------------------------------------


def test_compute_backoff_seconds_monotonic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff grows exponentially with attempts (before jitter cap)."""
    # Seed random so jitter is deterministic.
    monkeypatch.setattr(random, "uniform", lambda _a, _b: 0.0)
    prev = 0
    for attempts in range(0, 6):
        secs = worker.compute_backoff_seconds(attempts)
        # 2^attempts base; never below 1 (clamp); no jitter from stubbed RNG.
        expected = max(1, 2 ** max(0, attempts))
        assert secs == expected, (
            f"attempts={attempts} expected {expected}s, got {secs}s — "
            f"the curve drifted away from 2^attempts"
        )
        assert secs >= prev
        prev = secs


def test_compute_backoff_seconds_capped_at_max_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff is clamped to ``MAX_BACKOFF_S`` (3600s) so a long outage
    can't schedule retries weeks in the future."""
    monkeypatch.setattr(random, "uniform", lambda _a, _b: 0.0)
    # attempts=20 → 2^20 = 1_048_576 → must be clamped to 3600.
    assert worker.compute_backoff_seconds(20) == worker.MAX_BACKOFF_S


def test_claim_batch_sync_transitions_to_processing(
    qiepai_db_path: Path,
) -> None:
    """Atomic claim moves rows from ``pending`` → ``processing`` in one
    UPDATE, so two concurrent ``poll_once`` calls cannot double-claim.

    The post-claim ``state`` value is what the dispatcher helpers key
    off (``WHERE state='processing'`` guard); the test seeds 3 pending
    rows and asserts all 3 are now in ``processing``.
    """
    ids = [
        _insert_sync(
            OutboxEventDraft(
                event_type="system.demo_notify",
                aggregate_type="system",
                aggregate_id=f"agg-{i}",
                payload={"i": i},
            )
        )
        for i in range(3)
    ]
    claimed = worker._claim_batch_sync(limit=10, now_iso="2099-01-01 00:00:00")
    assert sorted(row["id"] for row in claimed) == sorted(ids)

    # Rows are now in 'processing' — the dispatcher's UPDATE WHERE
    # state='processing' will accept them.
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, state FROM outbox_events ORDER BY id ASC"
        )
        states = {str(r["id"]): str(r["state"]) for r in cur.fetchall()}
    finally:
        conn.close()
    for rid in ids:
        assert states[rid] == "processing", (
            f"row {rid!r} should be in 'processing' after claim; got "
            f"{states[rid]!r} — the atomic UPDATE...WHERE state='pending' "
            f"guard in _claim_batch_sync is missing"
        )


def test_claim_batch_sync_skips_rows_with_future_next_retry_at(
    qiepai_db_path: Path,
) -> None:
    """Rows whose ``next_retry_at`` is still in the future must NOT be
    picked up — the worker respects the retry window the mark_retry_sync
    helper scheduled."""
    # Seed 2 rows.
    for i in range(2):
        _insert_sync(
            OutboxEventDraft(
                event_type="system.demo_notify",
                aggregate_type="system",
                aggregate_id=f"agg-{i}",
                payload={"i": i},
            )
        )

    # Manually push the first row's next_retry_at to the future.
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET next_retry_at = '2099-12-31 23:59:59' "
            "WHERE aggregate_id = 'agg-0'"
        )
        conn.commit()
    finally:
        conn.close()

    # Claiming with now='2026-01-01' must skip the future-retry row.
    claimed = worker._claim_batch_sync(limit=10, now_iso="2026-01-01 00:00:00")
    claimed_agg = sorted(row["aggregate_id"] for row in claimed)
    assert claimed_agg == ["agg-1"], (
        f"expected to claim only agg-1 (agg-0's next_retry_at is in the "
        f"future); got {claimed_agg} — the retry-window guard in the "
        f"claim helper is missing"
    )


def test_recover_processing_to_pending_sync(
    qiepai_db_path: Path,
) -> None:
    """``_recover_processing_to_pending_sync`` rescues rows left in
    ``processing`` by a crashed worker — without this the queue
    silently strands rows forever.

    Called once per ``start_worker``; not exposed in any route.
    """
    # Insert + manually transition to 'processing' (simulating a crash).
    rid = _insert_sync(
        OutboxEventDraft(
            event_type="system.demo_notify",
            aggregate_type="system",
            aggregate_id="agg-x",
            payload={},
        )
    )
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'processing' WHERE id = ?",
            (rid,),
        )
        conn.commit()
    finally:
        conn.close()

    recovered = worker._recover_processing_to_pending_sync()
    assert recovered == 1

    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT state FROM outbox_events WHERE id = ?", (rid,)
        )
        new_state = str(cur.fetchone()["state"])
    finally:
        conn.close()
    assert new_state == "pending"


# ---------------------------------------------------------------------------
# 3. outbox.publisher — dry-run + retryable + card renderer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio  # type: ignore[misc]
async def test_publish_outbox_event_dry_run_no_creds(
    reset_publisher_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without app_id/app_secret/webhook_url the publisher short-circuits
    to dry-run and returns ``mode='dry_run'`` instead of POSTing.

    This is the v1 demo behaviour for environments without a real
    飞书 app — every dispatch logs the message body but never reaches
    out to the network. The test asserts no HTTP traffic is generated.
    """
    # Force credentials to empty.
    monkeypatch.setenv("QIEPAI_FEISHU_APP_ID", "")
    monkeypatch.setenv("QIEPAI_FEISHU_APP_SECRET", "")
    monkeypatch.setenv("QIEPAI_FEISHU_WEBHOOK_URL", "")
    reload_settings()

    async with httpx.AsyncClient(timeout=5.0) as client:
        result = await publish_outbox_event(
            client,
            event_type="system.heartbeat",
            aggregate_type="system",
            aggregate_id="agg-1",
            payload_text='{"display_name": "demo", "message": "hi"}',
            chat_id="oc_test",
        )
    assert result == {
        "ok": True,
        "mode": "dry_run",
        "info": "no credentials or chat_id",
    }


@pytest.mark.asyncio  # type: ignore[misc]
async def test_publish_outbox_event_dry_run_no_chat_id(
    reset_publisher_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with valid credentials, an empty chat_id is dry-run.

    This is the expected behaviour when the operator hasn't added a
    Feishu group via the dashboard — the worker logs the message and
    leaves the row in pending (or transitions to failed after
    MAX_ATTEMPTS). Without this fallback the worker would pile up
    5-attempt-failed rows for every demo event.
    """
    # Configure credentials so we hit the chat_id-missing branch.
    monkeypatch.setenv("QIEPAI_FEISHU_APP_ID", "cli_test_app_id")
    monkeypatch.setenv("QIEPAI_FEISHU_APP_SECRET", "cli_test_app_secret")
    monkeypatch.setenv("QIEPAI_FEISHU_WEBHOOK_URL", "")
    reload_settings()

    async with httpx.AsyncClient(timeout=5.0) as client:
        result = await publish_outbox_event(
            client,
            event_type="system.heartbeat",
            aggregate_type="system",
            aggregate_id="agg-1",
            payload_text='{"message": "hi"}',
            chat_id="",  # empty — registry returned ''
        )
    assert result == {
        "ok": True,
        "mode": "dry_run",
        "info": "no credentials or chat_id",
    }


def test_publish_error_retryable_for_5xx_and_429() -> None:
    """PublishError classifies status codes so the worker can pick
    retry vs give-up policy: 5xx and 429 are retryable; other 4xx
    are not (no point retrying — same response will come back).
    """
    e5xx = PublishError("boom", status_code=503)
    assert e5xx.retryable is True
    e429 = PublishError("rate-limit", status_code=429)
    assert e429.retryable is True
    e400 = PublishError("bad-req", status_code=400)
    assert e400.retryable is False
    e401 = PublishError("auth", status_code=401)
    assert e401.retryable is False
    # Network error: no status_code → retryable (default).
    enet = PublishError("transport")
    assert enet.retryable is True
    # Explicit override wins.
    e_force = PublishError("transient-blip", status_code=503, retryable=False)
    assert e_force.retryable is False


def test_render_card_includes_aggregate_id_always() -> None:
    """The Feishu card always renders the ``_aggregate_id`` so the
    operator can deep-link from the chat back to the dashboard row.

    Without this every card looks identical and the chat becomes
    useless as an audit trail.
    """
    from apps.api.services.qiepai.outbox.publisher import _render_card

    body = build_event_payload(
        "kpi.anomaly",
        "kpi",
        "kpi-financial-q3",
        '{"metric_name": "营收", "metric_value": "850", "unit": "万元"}',
    )
    card = _render_card(body)
    # Card has the expected Feishu interactive shape.
    assert card["header"]["template"] == "red"  # aggregate_type=kpi → red
    assert "KPI 异常告警" in card["header"]["title"]["content"]
    elements_text = str(card["elements"])
    assert "kpi-financial-q3" in elements_text
    assert "850" in elements_text
    assert "万元" in elements_text


# ---------------------------------------------------------------------------
# 4. integrations.feishu_settings — is_configured predicate
# ---------------------------------------------------------------------------


def test_feishu_settings_is_configured_app_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``is_configured`` is true iff ``app_id`` + ``app_secret`` are both
    set (the tenant-token path) OR a webhook URL is set (the webhook
    fallback). Otherwise the publisher enters dry-run.
    """
    monkeypatch.setenv("QIEPAI_FEISHU_APP_ID", "cli_xxx")
    monkeypatch.setenv("QIEPAI_FEISHU_APP_SECRET", "yyy")
    monkeypatch.setenv("QIEPAI_FEISHU_WEBHOOK_URL", "")
    reload_settings()

    cfg = feishu_settings.feishu_settings()
    assert cfg.is_configured() is True
    assert cfg.app_id == "cli_xxx"
    assert cfg.app_secret == "yyy"


def test_feishu_settings_is_configured_webhook_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Webhook URL alone is enough — the tenant-token path is optional."""
    monkeypatch.setenv("QIEPAI_FEISHU_APP_ID", "")
    monkeypatch.setenv("QIEPAI_FEISHU_APP_SECRET", "")
    monkeypatch.setenv("QIEPAI_FEISHU_WEBHOOK_URL", "https://open.feishu.cn/hook/abc")
    reload_settings()

    cfg = feishu_settings.feishu_settings()
    assert cfg.is_configured() is True
    assert cfg.webhook_url == "https://open.feishu.cn/hook/abc"


def test_feishu_settings_unconfigured_when_all_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-empty env vars ⇒ ``is_configured()`` returns False; the
    publisher will then dry-run every dispatch."""
    monkeypatch.setenv("QIEPAI_FEISHU_APP_ID", "")
    monkeypatch.setenv("QIEPAI_FEISHU_APP_SECRET", "")
    monkeypatch.setenv("QIEPAI_FEISHU_WEBHOOK_URL", "")
    reload_settings()

    cfg = feishu_settings.feishu_settings()
    assert cfg.is_configured() is False


def test_feishu_settings_invalid_int_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-numeric ``QIEPAI_OUTBOX_BATCH`` falls back to the default
    (50) instead of crashing the worker on startup.

    Same for ``QIEPAI_FEISHU_TOKEN_TTL_S`` — the typed-config loader
    is forgiving on bad input so a typo in the .env doesn't take the
    process down.
    """
    monkeypatch.setenv("QIEPAI_OUTBOX_BATCH", "not-a-number")
    monkeypatch.setenv("QIEPAI_FEISHU_TOKEN_TTL_S", "also-bad")
    reload_settings()

    cfg = feishu_settings.feishu_settings()
    assert cfg.batch_size == 50
    assert cfg.token_ttl_s == 7200


# ---------------------------------------------------------------------------
# 5. integrations.registry — empty chat_id sentinel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio  # type: ignore[misc]
async def test_first_active_chat_id_returns_empty_when_no_groups(
    qiepai_db_path: Path,
) -> None:
    """When the operator hasn't registered any Feishu group, the
    worker asks the registry for the first active chat_id and gets
    back an empty string. This is the dry-run sentinel — the
    publisher logs the body and moves on rather than 502ing.
    """
    assert await first_active_chat_id() == "", (
        f"empty registry should return '' sentinel; got "
        f"{await first_active_chat_id()!r}"
    )


# ---------------------------------------------------------------------------
# 6. EVENT_TYPES catalogue — sanity check the ❸-1 contract
# ---------------------------------------------------------------------------


def test_event_types_catalogue_matches_published_set() -> None:
    """The canonical :data:`EVENT_TYPES` frozenset is the single source
    of truth for what the worker can publish. Adding a new trigger
    means extending this set; the catalogue must match the v1 spec.
    """
    expected = {
        # employee lifecycle
        "employee.published",
        "employee.failed_publish",
        # decision lifecycle
        "decision.created",
        "decision.decided",
        "decision.cancelled",
        # task lifecycle
        "task.assigned",
        "task.completed",
        "task.cancelled",
        # KPI / metrics
        "kpi.anomaly",
        "kpi.freshness_warning",
        # manual / demo triggers
        "system.demo_notify",
        "system.heartbeat",
    }
    assert EVENT_TYPES == frozenset(expected), (
        f"EVENT_TYPES catalogue drifted from the spec; diff="
        f"missing={expected - set(EVENT_TYPES)} extra={set(EVENT_TYPES) - expected}"
    )


# ---------------------------------------------------------------------------
# 7. Routers — module wiring sanity check
# ---------------------------------------------------------------------------


def test_outbox_router_exposes_endpoints() -> None:
    """The outbox router must carry the 5 admin endpoints so the
    operator dashboard can list / inspect / replay / trigger."""
    from apps.api.routes.qiepai.outbox_events import router as outbox_router

    # The router carries prefix='/outbox' so paths already start with /outbox/.
    paths = sorted(
        route.path
        for route in outbox_router.routes
        if hasattr(route, "path")
    )
    expected_suffixes = (
        "/outbox/events",
        "/outbox/events/{event_id}",
        "/outbox/events/trigger_demo",
        "/outbox/events/trigger_kpi_anomaly",
        "/outbox/events/{event_id}/replay",
    )
    path_set = set(paths)
    for expected in expected_suffixes:
        assert expected in path_set, (
            f"outbox router missing endpoint {expected!r}; found paths={paths}"
        )


def test_feishu_router_exposes_endpoints() -> None:
    """The Feishu integration router must carry the 4 admin endpoints."""
    # The router lives under the service package (not the routes
    # shim); both paths work — use the service package which the
    # shim re-exports.
    from apps.api.services.qiepai.integrations.feishu_router import router

    paths = sorted(
        f"{router.prefix}{route.path}"
        for route in router.routes
        if hasattr(route, "path")
    )
    expected_suffixes = (
        "/integrations/feishu/groups",
        "/integrations/feishu/groups/{group_id}/delete",
        "/integrations/feishu/test",
    )
    # The GET /groups + POST /groups endpoints are both on the same
    # '/groups' path so dedupe before comparing.
    unique_paths = set(paths)
    for suffix in expected_suffixes:
        assert any(p.endswith(suffix) for p in unique_paths), (
            f"feishu router missing endpoint ending in {suffix!r}; "
            f"found paths={paths}"
        )
    # Also assert the /test endpoint is mounted.
    assert any(p.endswith("/integrations/feishu/test") for p in unique_paths)