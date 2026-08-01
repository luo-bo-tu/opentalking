"""qiepai · Phase ❸ backend bugfix regression tests.

Covers the three bugs that the ❸ backend bugfix PR closed (Bug 1 /
Bug 2 / Bug 3). The PR fixed the production code in
:mod:`apps.api.services.qiepai.outbox` + the integrations package;
this file is the **regression-net** so future refactors can't silently
re-introduce any of the three regressions:

* **Bug 1** — two concurrent ``poll_once`` calls must not double-claim
  the same pending row. The claim helper now ships an atomic
  ``UPDATE … WHERE state='pending'`` guard so the second worker sees
  only the rows the first worker has not yet taken.
* **Bug 2** — the mark-published / mark-retry / mark-failed helpers
  carry a ``WHERE state='processing'`` (or ``'pending'``) state guard
  so a late delivery / replay / manual UPDATE cannot overwrite a row
  that has already been finalised (``'published'`` / ``'failed'``).
* **Bug 3** — the in-process ``tenant_access_token`` cache survives
  the 60-second safety margin and is shared across every callsite in
  a single Python process; the actual HTTP ``POST`` to Feishu's token
  endpoint fires once per cache lifetime, not once per call.

Each test is self-contained (per-test temp DB, per-test publisher
cache reset) so the suite is order-independent and safe to run with
``-p no:randomly``. The publisher / worker functions are imported
directly (not through the FastAPI app) so the tests stay focused on
the outbox + integrations surface and don't accidentally depend on
the ❷-6 routes fixtures.

NOTE: this file is add-only — it does NOT touch any pre-existing test
files in ``apps/api/tests/`` (the reviewer's standing instruction).
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai import migration_runner, seed
from apps.api.services.qiepai.outbox import worker
from apps.api.services.qiepai.outbox.events import OutboxEventDraft, insert_event
from apps.api.services.qiepai.outbox.publisher import (
    PublishError,
    _fetch_tenant_token,
    _get_token,
    _reset_token_cache_for_tests,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qiepai_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Per-test temp DB + migrated schema + seeded metrics.

    Identical to the ❷-5 / ❷-6 review-pass fixtures: monkeypatch the
    env var + the module-level ``get_db_path`` so every ``db.connect()``
    call lands on the temp file, then run the migrations + seed so
    the outbox table exists.
    """
    db_file = tmp_path / "qiepai-stage3-bugfix.sqlite"
    monkeypatch.setenv("QIEPAI_ENTERPRISE_DB_PATH", str(db_file))
    monkeypatch.setattr(qiepai_db, "get_db_path", lambda: db_file)
    asyncio.run(migration_runner.run_pending_migrations())
    asyncio.run(seed.seed_initial_metrics())
    return db_file


@pytest.fixture
def reset_publisher_cache() -> Iterator[None]:
    """Drop the in-process token cache between tests so Bug 3 sees a
    clean slate and one test's expired-token manipulation cannot leak
    into the next."""
    _reset_token_cache_for_tests()
    worker.reset_for_tests()
    yield
    _reset_token_cache_for_tests()
    worker.reset_for_tests()


def _seed_pending_events(
    db_file: Path, *, count: int, event_type: str = "system.heartbeat"
) -> list[tuple[str, str]]:
    """Insert ``count`` pending ``outbox_events`` rows.

    Uses the public :func:`insert_event` helper so the rows go through
    the same insert path as production code (state defaults to
    ``'pending'`` on the SQL side). Returns a list of
    ``(row_id, aggregate_id)`` tuples in insertion order so test
    assertions can pick the right handle:

    * ``row_id`` (e.g. ``"out_5f3c…"``) — what :func:`_row_state` and
      the dispatcher helpers (``_mark_published_sync`` etc.) need.
    * ``aggregate_id`` (e.g. ``"agg-007"``) — what ``fake_publish``
      records; the concurrent-worker test asserts that the union of
      dispatched aggregate_ids matches the union of seeded aggregate_ids.
    """
    inserted: list[tuple[str, str]] = []
    for i in range(count):
        draft = OutboxEventDraft(
            event_type=event_type,
            aggregate_type="system",
            aggregate_id=f"agg-{i:03d}",
            payload={"i": i},
        )
        # The async wrapper swallows exceptions on purpose — call the
        # sync helper directly so test failures surface the real cause.
        from apps.api.services.qiepai.outbox.events import _insert_sync

        new_id = _insert_sync(draft)
        inserted.append((new_id, draft.aggregate_id))
    return inserted


def _row_state(db_file: Path, row_id: str) -> tuple[str, int]:
    """Return ``(state, attempts)`` for a single outbox row."""
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT state, attempts FROM outbox_events WHERE id = ?",
            (row_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise AssertionError(f"outbox row {row_id!r} vanished")
    return str(row["state"]), int(row["attempts"])


def _count_published(db_file: Path) -> int:
    """Number of rows currently in ``state='published'``."""
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM outbox_events WHERE state = 'published'"
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return int(row["c"])


# ---------------------------------------------------------------------------
# Bug 1 — two concurrent poll_once calls must not double-claim pending rows
# ---------------------------------------------------------------------------


def test_concurrent_workers_no_double_claim(
    qiepai_db_path: Path,
    reset_publisher_cache: None,
) -> None:
    """Bug 1 regression: 32 pending rows, two concurrent workers.

    Spawns two ``poll_once`` coroutines via ``asyncio.gather`` against
    a queue of 32 pending events. The post-❸-1 claim helper carries an
    atomic ``UPDATE … WHERE state='pending'`` guard; without it both
    workers would ``SELECT`` the same 32 rows and the publisher would
    be invoked 64 times (every event published twice). The assertion:

    * total publisher invocations across both workers ``<= 32`` (the
      fix ensures both workers together publish each pending row at
      most once; one worker may take the lot, or they may split);
    * the union of aggregate_ids actually published is exactly the
      32 distinct events that were seeded (no row is silently
      dropped, none is published twice);
    * the DB rowcount in ``state='published'`` is exactly 32 after
      both workers drain.
    """
    seeded_pairs = _seed_pending_events(qiepai_db_path, count=32)
    assert len(seeded_pairs) == 32
    seeded_aggregate_ids = [agg for (_row_id, agg) in seeded_pairs]

    published_aggregate_ids: list[str] = []

    async def fake_publish(
        client: httpx.AsyncClient,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload_text: str,
        chat_id: str,
    ) -> dict[str, Any]:
        # Tiny sleep so both workers are genuinely in flight at once —
        # otherwise the second ``poll_once`` call simply sees an empty
        # queue because the first one finished before the second even
        # entered ``_claim_batch_sync``.
        await asyncio.sleep(0.005)
        published_aggregate_ids.append(aggregate_id)
        return {"ok": True, "mode": "live", "info": "stubbed"}

    async def run_two_workers() -> None:
        # chat_id_override bypasses the feishu_groups registry so the
        # test does not need a seeded group row.
        async with httpx.AsyncClient(timeout=10.0) as client:
            await asyncio.gather(
                worker.poll_once(
                    client=client,
                    batch_size=32,
                    chat_id_override="chat_test",
                ),
                worker.poll_once(
                    client=client,
                    batch_size=32,
                    chat_id_override="chat_test",
                ),
            )

    with patch.object(worker, "publish_outbox_event", side_effect=fake_publish):
        asyncio.run(run_two_workers())

    # 1. Each event was published AT MOST once across both workers —
    #    the ``UPDATE … WHERE state='pending'`` claim guard inside
    #    ``_claim_batch_sync`` is what makes this possible.
    assert len(published_aggregate_ids) <= 32, (
        f"publisher was invoked {len(published_aggregate_ids)} times for "
        f"32 events; the claim guard is missing — both workers SELECT-ed "
        f"the whole pending queue and double-published everything"
    )

    # 2. Every seeded event made it through at least once (no silent
    #    drop) — the SELECT query picks every pending row regardless
    #    of which worker claims it, so the union of dispatched rows
    #    must equal the 32 distinct ids we inserted.
    assert set(published_aggregate_ids) == set(seeded_aggregate_ids), (
        f"missing events in published set: "
        f"{set(seeded_aggregate_ids) - set(published_aggregate_ids)}"
    )

    # 3. The DB reflects the same picture: exactly 32 rows in
    #    ``state='published'``. Without the guard the worker would
    #    still leave 32 rows there (mark_published overwrites state
    #    unconditionally) but with potentially-inflated ``attempts``;
    #    with the guard we get exactly 1 attempt per row.
    assert _count_published(qiepai_db_path) == 32

    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        # Every published row has ``attempts == 1`` — exactly one
        # successful delivery per event. With the bug present both
        # workers call ``_mark_published_sync`` on every row, so each
        # row would have ``attempts == 2`` (incremented twice).
        cur.execute(
            "SELECT attempts FROM outbox_events WHERE state = 'published'"
        )
        attempts = [int(r["attempts"]) for r in cur.fetchall()]
    finally:
        conn.close()
    assert attempts == [1] * 32, (
        f"expected attempts=1 on every row (one successful delivery), "
        f"got counts={sorted(set(attempts))} (likely the worker is "
        f"double-publishing and bumping attempts twice)"
    )


# ---------------------------------------------------------------------------
# Bug 2 — mark_published must carry a state guard (no overwrite)
# ---------------------------------------------------------------------------


def test_state_guard_on_retry(
    qiepai_db_path: Path,
    reset_publisher_cache: None,
) -> None:
    """Bug 2 regression: state guard on the dispatcher UPDATEs.

    The ❸-1 ``_mark_published_sync`` / ``_mark_retry_sync`` /
    ``_mark_failed_sync`` helpers each carry an explicit state guard
    on the WHERE clause (``state='processing'`` /
    ``state='pending'`` / ``state='pending'`` respectively) so that:

    * a row that has already been finalised (``'published'`` /
      ``'failed'``) cannot be silently overwritten by a late
      delivery, replay, or scheduler callback;
    * the worker cannot accidentally clobber an event that another
      worker has already moved to ``'failed'``.

    The test exercises three scenarios:

    1. First publish attempt raises ``PublishError(retryable=True)`` →
       state stays ``'pending'`` and ``attempts`` is bumped (the
       retry path is the only way back to ``'pending'`` so this is
       really exercising ``_mark_retry_sync``).
    2. Second publish attempt succeeds → ``_mark_published_sync``
       moves the row to ``'published'``. The row's ``attempts``
       column reflects both invocations.
    3. **State-guard proof** — after manually flipping the row's
       state to ``'failed'``, calling ``_mark_published_sync`` must
       return ``rowcount == 0`` (the ``WHERE state='processing'``
       guard rejects the update). Without the guard the helper would
       silently overwrite the ``'failed'`` row with ``'published'``.
    """
    # One event, manually inserted so we can exercise the dispatcher
    # directly without spinning up the full worker loop.
    seeded_id = _seed_pending_events(qiepai_db_path, count=1)[0][0]

    publish_calls: list[dict[str, Any]] = []

    async def flaky_publish(
        client: httpx.AsyncClient,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload_text: str,
        chat_id: str,
    ) -> dict[str, Any]:
        publish_calls.append({"id": aggregate_id, "call": len(publish_calls) + 1})
        if len(publish_calls) == 1:
            # First attempt — transient retryable failure.
            raise PublishError("simulated transient", status_code=503)
        return {"ok": True, "mode": "live", "info": "ok"}

    # ---- Scenario 1: first call fails, state preserved as 'pending' ----
    async def run_first_fail() -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await worker.poll_once(
                client=client,
                batch_size=10,
                chat_id_override="chat_test",
            )

    with patch.object(worker, "publish_outbox_event", side_effect=flaky_publish):
        asyncio.run(run_first_fail())

    state_after_fail, attempts_after_fail = _row_state(qiepai_db_path, seeded_id)
    assert state_after_fail == "pending", (
        f"after a transient failure the row must stay pending for a "
        f"later retry, got state={state_after_fail!r}"
    )
    assert attempts_after_fail == 1, (
        f"expected attempts=1 after the first failure (the retry path "
        f"bumps it), got attempts={attempts_after_fail}"
    )

    # The retry path sets ``next_retry_at`` to ``now + backoff`` (1-3s
    # for ``attempts=1``). Clear it so the second poll picks the row
    # up immediately rather than waiting out the backoff window.
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET next_retry_at = NULL WHERE id = ?",
            (seeded_id,),
        )
        conn.commit()
    finally:
        conn.close()

    # ---- Scenario 2: second call succeeds, row moves to 'published' ----
    async def run_second_success() -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await worker.poll_once(
                client=client,
                batch_size=10,
                chat_id_override="chat_test",
            )

    with patch.object(worker, "publish_outbox_event", side_effect=flaky_publish):
        asyncio.run(run_second_success())

    state_after_success, attempts_after_success = _row_state(qiepai_db_path, seeded_id)
    assert state_after_success == "published", (
        f"after a successful retry the row must move to 'published', "
        f"got state={state_after_success!r}"
    )
    assert attempts_after_success == 2, (
        f"expected attempts=2 across the two calls, got "
        f"attempts={attempts_after_success}"
    )

    # ---- Scenario 3: state guard proof ----
    # Manually flip the row's state to 'failed' — this simulates a
    # manual UPDATE that an operator might perform via the admin
    # endpoint, or another worker's give-up path. The dispatcher's
    # ``_mark_published_sync`` must NOT be able to overwrite this
    # back to 'published': the production helper carries a
    # ``WHERE state='processing'`` guard that rejects any UPDATE
    # when the row is no longer in the expected state.
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'failed', last_error = 'manual' "
            "WHERE id = ?",
            (seeded_id,),
        )
        conn.commit()
        # Read the manual state to confirm the setup is what we expect.
        cur.execute(
            "SELECT state FROM outbox_events WHERE id = ?", (seeded_id,)
        )
        manual_state = str(cur.fetchone()["state"])
    finally:
        conn.close()
    assert manual_state == "failed"

    # Invoke the production dispatcher helper directly — it MUST be
    # a no-op on a 'failed' row. Without the ``WHERE state='processing'``
    # guard the helper would silently flip the row back to
    # 'published', which is exactly the Bug 2 regression.
    from apps.api.services.qiepai.outbox.worker import (
        _mark_published_sync as production_mark_published,
    )

    production_mark_published(seeded_id)

    final_state, final_attempts = _row_state(qiepai_db_path, seeded_id)
    assert final_state == "failed", (
        f"the dispatcher silently overwrote a 'failed' row to "
        f"{final_state!r}; the state guard in _mark_published_sync "
        f"is missing — Bug 2 is not fixed"
    )
    assert final_attempts == 2, (
        f"the guard must reject the UPDATE entirely (no attempts "
        f"bump); got attempts={final_attempts} — the dispatcher "
        f"incremented the counter even though it refused the state "
        f"change"
    )


# ---------------------------------------------------------------------------
# Bug 3 — in-process tenant_access_token cache is shared across callsites
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_feishu_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a fake Feishu app id + secret so the publisher is not
    in dry-run mode (which short-circuits the token fetch entirely).

    Uses an LRU-cache busting reload so the patched env vars are
    visible to :func:`feishu_settings` immediately.
    """
    monkeypatch.setenv("QIEPAI_FEISHU_APP_ID", "cli_test_app_id")
    monkeypatch.setenv("QIEPAI_FEISHU_APP_SECRET", "cli_test_app_secret")
    from apps.api.services.qiepai.integrations.feishu_settings import (
        reload_settings,
    )

    reload_settings()


def test_tenant_token_cache_shared(
    reset_publisher_cache: None,
    fake_feishu_credentials: None,
) -> None:
    """Bug 3 regression: token cache is shared + respects the 60s TTL.

    Five sequential ``_get_token`` calls must hit the HTTP token
    endpoint exactly once — the first call refreshes the in-process
    cache; the next four return the cached token without making any
    network IO. Then we forcibly age the cache past the 60-second
    safety margin and confirm the next call refreshes (1 additional
    HTTP hit). Finally a final call within the new TTL must NOT make
    any further HTTP request.

    The test inspects :func:`_fetch_tenant_token` (the real private
    function that does the HTTP POST) via a monkeypatched
    ``httpx.AsyncClient`` so we can count calls without needing to
    stub the publisher out.
    """
    http_calls = 0

    class _CountingTransport(httpx.AsyncBaseTransport):
        """httpx transport that counts requests + returns a canned
        ``tenant_access_token`` response so :func:`_fetch_tenant_token`
        thinks it talked to the real Feishu API."""

        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(
            self, request: httpx.Request
        ) -> httpx.Response:
            nonlocal http_calls
            self.calls += 1
            http_calls += 1
            # Only the token endpoint matters for this test; reply
            # with the canonical Feishu body.
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": f"t-{self.calls}",
                    "expire": 7200,
                },
            )

    transport = _CountingTransport()

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=transport, timeout=10.0
        ) as client:
            # 1. Five sequential calls must produce exactly one HTTP
            #    fetch (Bug 3's whole point — process-wide cache).
            for _ in range(5):
                token = await _get_token(client)
                assert token, (
                    "fake transport always returns a non-empty token; "
                    "_get_token returning empty means the cache was "
                    "bypassed or the credentials didn't load"
                )

            assert transport.calls == 1, (
                f"after 5 _get_token calls the token endpoint was hit "
                f"{transport.calls} times; Bug 3's cache is missing — "
                f"every callsite refreshes the token independently"
            )
            assert http_calls == 1

            # 2. Force the cache past its 60-second safety margin by
            #    rewriting ``expires_at`` to ``now - 1`` (monotonic
            #    seconds). ``_get_token`` should treat this as stale
            #    and make a fresh HTTP request.
            from apps.api.services.qiepai.outbox.publisher import _TOKEN

            import time as _time

            _TOKEN.expires_at = _time.monotonic() - 1.0
            token_after_expiry = await _get_token(client)
            assert token_after_expiry, "post-expiry refresh returned empty"
            assert transport.calls == 2, (
                f"after the cache expired the next _get_token must "
                f"refresh (calls=2); got calls={transport.calls}"
            )

            # 3. Within the new TTL the cache must keep serving from
            #    memory — no further HTTP.
            for _ in range(3):
                again = await _get_token(client)
                assert again == token_after_expiry, (
                    "within the TTL the cached token must be served "
                    "verbatim; got a different value (cache replaced "
                    "the wrong slot?)"
                )
            assert transport.calls == 2, (
                f"3 additional in-TTL calls must NOT increment HTTP "
                f"calls; got calls={transport.calls} — the cache "
                f"still refreshes on every read"
            )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Self-check: the module's own private helpers are importable + wired up
# ---------------------------------------------------------------------------


def test_stage3_module_wiring() -> None:
    """Sanity check that the symbols the bugfix regression tests rely
    on are actually importable from the public surface — guards
    against a future refactor that moves ``_get_token`` /
    ``_fetch_tenant_token`` somewhere unexpected.
    """
    assert callable(_get_token)
    assert callable(_fetch_tenant_token)
    assert callable(_reset_token_cache_for_tests)
    assert callable(worker.poll_once)
    assert callable(worker.reset_for_tests)
    assert issubclass(PublishError, RuntimeError)
    # insert_event is async + catches everything (it's the "best-effort"
    # wrapper business code uses); _insert_sync raises on failure.
    assert callable(insert_event)