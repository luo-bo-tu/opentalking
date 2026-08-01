"""qiepai · outbox worker (Phase ❸-1).

Background asyncio loop that:

1. Every ``QIEPAI_OUTBOX_POLL_S`` seconds (default 2.0s; configurable)
   claims a batch of up to ``QIEPAI_OUTBOX_BATCH`` (default 50) pending
   ``outbox_events`` rows via
   :func:`poll_once`.
2. Dispatches each row through :func:`apps.api.services.qiepai.outbox.publisher.publish_outbox_event`,
   using the **first active Feishu group** as the destination
   (``feishu_groups`` registry).
3. Marks the row ``state='published'`` on success.
4. On failure, increments ``attempts`` and sets ``next_retry_at`` =
   ``now + exp_backoff(attempts)`` (``2^attempts`` seconds, capped at
   ``MAX_BACKOFF_S`` = 3600s, with ±20 % jitter).
5. When ``attempts >= MAX_ATTEMPTS`` (default 5) the row is moved to
   ``state='failed'`` and a ``WARNING`` log line is emitted so the
   operator notices on the next dashboard refresh.

Public entry points
===================

* :func:`start_worker` — spawn the loop on the running event loop.
* :func:`stop_worker` — graceful cancellation (called from lifespan).
* :func:`poll_once` — synchronous, batch-limited claim + dispatch used
  by the loop body and surfaced for tests.
* :func:`claim_batch_sync` / :func:`mark_published_sync` /
  :func:`mark_retry_sync` / :func:`mark_failed_sync` — DB IO helpers
  wrapped in ``asyncio.to_thread`` by the loop.

Why a per-row UPDATE on state? (vs. a single transactional claim)
=================================================================

SQLite's ``UPDATE … RETURNING`` exists in some builds but not all; we
avoid the portability headache by claiming rows in one transaction
with a row-by-row attempt-counter increment. On any race (two workers
in the same process, which we don't expect) the worst case is "two
workers each publish a copy" — the Feishu message endpoint will simply
print the card twice, which is a noisy but harmless failure mode.

Configuration
=============

Three env vars govern the loop:

* ``QIEPAI_OUTBOX_ENABLED`` (default ``"1"``) — set to ``"0"`` to
  prevent the worker from spawning (for tests / single-shot
  migrations).
* ``QIEPAI_OUTBOX_POLL_S`` (default ``"2.0"``).
* ``QIEPAI_OUTBOX_BATCH`` (default ``"50"``).

``QIEPAI_OUTBOX_ENABLED=0`` is honoured by :func:`start_worker` so
calling code does not have to special-case the env var.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from .. import db
from ..integrations.registry import first_active_chat_id
from .publisher import PublishError, publish_outbox_event
from .publisher import reset_for_tests as _reset_publisher_for_tests

log = logging.getLogger(__name__)


#: Maximum delivery attempts before the row is marked ``state='failed'``.
MAX_ATTEMPTS: Final[int] = 5
#: Exponential backoff ceiling — prevents a 50-day retry during long
#: outages while still letting transient errors recover within an hour.
MAX_BACKOFF_S: Final[int] = 3600
#: Jitter band (± 20 % of the un-jittered backoff) so a thundering-herd
#: reconnect doesn't hit the Feishu endpoint all at once.
_BACKOFF_JITTER: Final[float] = 0.2


@dataclass
class WorkerResult:
    """One ``poll_once`` batch result.

    Returned by :func:`poll_once` so tests can assert the loop is moving
    rows through the state machine without having to scrape logs.
    """

    claimed: int = 0
    published: int = 0
    retried: int = 0
    failed: int = 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("outbox.worker: invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("outbox.worker: invalid %s=%r; using default %s", name, raw, default)
        return default


def _worker_enabled() -> bool:
    raw = os.environ.get("QIEPAI_OUTBOX_ENABLED", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on", ""):
        return True
    log.warning("outbox.worker: unrecognized QIEPAI_OUTBOX_ENABLED=%r; treating as enabled", raw)
    return True


def _poll_interval_s() -> float:
    return _env_float("QIEPAI_OUTBOX_POLL_S", 2.0)


def _batch_size() -> int:
    return _env_int("QIEPAI_OUTBOX_BATCH", 50)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def compute_backoff_seconds(attempts: int) -> int:
    """Exponential backoff with ±20 % jitter, clamped to ``MAX_BACKOFF_S``.

    Pure function — exported so tests can pin the curve without spinning
    up a worker. Jitter is deterministic given the input ``attempts``
    via :func:`random.uniform` seeded by the call-site's RNG; tests
    can pass their own RNG via ``random.seed(...)``.
    """
    base = min(2 ** max(0, int(attempts)), MAX_BACKOFF_S)
    jitter_band = base * _BACKOFF_JITTER
    delta = random.uniform(-jitter_band, jitter_band)  # noqa: S311
    return max(1, int(round(base + delta)))


# ---------------------------------------------------------------------------
# DB IO helpers (sync — wrapped in asyncio.to_thread by the loop)
# ---------------------------------------------------------------------------


def _claim_batch_sync(limit: int, now_iso: str) -> list[dict[str, Any]]:
    """Atomically claim up to ``limit`` ready rows.

    "Ready" = ``state='pending' AND (next_retry_at IS NULL OR next_retry_at <= now)``.

    The claim transitions matching rows from ``state='pending'`` to
    ``state='processing'`` via an atomic ``UPDATE ... WHERE state='pending'``
    so concurrent ``poll_once`` calls cannot double-claim the same row.
    The inner ``SELECT ... LIMIT ?`` picks the candidates; the outer
    ``WHERE state='pending'`` guard ensures only rows that are still
    claimable get transitioned (a row that another worker has already
    taken in the same instant will match ``state='processing'`` and be
    skipped by our UPDATE, so we don't publish it).

    Returns the claimed rows as dicts (id + the columns needed by the
    publisher). Empty list when nothing is ready.

    Recovery: if a previous worker crash left rows in ``state='processing'``
    they would be invisible to the next claim; :func:`_recover_processing_to_pending_sync`
    is called once per :func:`start_worker` so they come back to
    ``pending`` on the next boot.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'processing' "
            "WHERE id IN ("
            "  SELECT id FROM outbox_events "
            "  WHERE state = 'pending' "
            "    AND (next_retry_at IS NULL OR next_retry_at <= ?) "
            "  ORDER BY created_at ASC, id ASC LIMIT ?"
            ") AND state = 'pending' "
            "RETURNING id, event_type, aggregate_type, aggregate_id, payload, "
            "  state, attempts, next_retry_at",
            (now_iso, limit),
        )
        rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _mark_published_sync(row_id: str) -> None:
    """Move a claimed row to ``state='published'``.

    Carries a ``WHERE state='processing'`` guard so a late delivery,
    replay, or manual UPDATE that already moved the row to
    ``'failed'`` / ``'published'`` cannot be silently overwritten.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'published', last_error = NULL, "
            "attempts = attempts + 1 WHERE id = ? AND state = 'processing'",
            (row_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_retry_sync(
    row_id: str,
    *,
    error_text: str,
    attempts_after: int,
    next_retry_iso: str,
) -> None:
    """Bump attempts + move the claimed row back to ``state='pending'`` for re-claim.

    Guarded by ``WHERE state='processing'`` so the retry path cannot
    resurrect a row that another worker has already finalised.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'pending', last_error = ?, "
            "attempts = ?, next_retry_at = ? WHERE id = ? AND state = 'processing'",
            (error_text[:1000], attempts_after, next_retry_iso, row_id),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_failed_sync(row_id: str, *, error_text: str, attempts_after: int) -> None:
    """Move a claimed row to ``state='failed'``; the row stays in the table for audit.

    Guarded by ``WHERE state='processing'`` so we never silently
    re-fail a row that is already finalised.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'failed', last_error = ?, "
            "attempts = ? WHERE id = ? AND state = 'processing'",
            (error_text[:1000], attempts_after, row_id),
        )
        conn.commit()
    finally:
        conn.close()


def _recover_processing_to_pending_sync() -> int:
    """Move any leftover ``state='processing'`` rows back to ``pending``.

    Called from :func:`start_worker` on worker boot so a crash that
    left rows in-flight doesn't silently strand them forever.

    Returns the number of rows recovered.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'pending' WHERE state = 'processing'"
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def _now_iso() -> str:
    """SQLite CURRENT_TIMESTAMP format: ``YYYY-MM-DD HH:MM:SS`` (UTC).

    SQLite stores TIMESTAMP in UTC by convention; we mirror the seed /
    migration files by using the literal UTC string here.
    """
    import datetime as _dt

    return _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _iso_in(seconds: int) -> str:
    import datetime as _dt

    return (_dt.datetime.utcnow() + _dt.timedelta(seconds=seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ---------------------------------------------------------------------------
# poll_once — single batch cycle
# ---------------------------------------------------------------------------


async def poll_once(
    *,
    client: httpx.AsyncClient,
    batch_size: int | None = None,
    chat_id_override: str | None = None,
) -> WorkerResult:
    """Run a single poll + dispatch cycle, return a :class:`WorkerResult`.

    No exception handling around the publisher — let :class:`PublishError`
    propagate so the worker loop survives only on transport-level
    failures (which we've already classified as retryable).

    Parameters
    ----------
    client
        Shared ``httpx.AsyncClient`` for the publisher's IO. The caller
        owns its lifecycle (the worker loop borrows a single client per
        cycle).
    batch_size
        Optional override (default = env-configured batch). Tests pass
        a small number (e.g. 5) to keep the cycle under their step
        budget.
    chat_id_override
        Used by tests; the production loop reads the chat_id from the
        ``feishu_groups`` registry. Passing a non-empty string here
        enables a deterministic end-to-end test against a mock webhook.
    """
    limit = batch_size if batch_size is not None else _batch_size()
    if chat_id_override is not None:
        chat_id = chat_id_override
    else:
        chat_id = await first_active_chat_id()

    claimed = await asyncio.to_thread(_claim_batch_sync, limit, _now_iso())
    result = WorkerResult(claimed=len(claimed))
    if not claimed:
        return result

    for row in claimed:
        attempts_so_far = int(row.get("attempts") or 0)
        try:
            outcome = await publish_outbox_event(
                client,
                event_type=row["event_type"],
                aggregate_type=row["aggregate_type"],
                aggregate_id=row["aggregate_id"],
                payload_text=row["payload"] or "",
                chat_id=chat_id,
            )
        except PublishError as exc:
            outcome = {"ok": False, "mode": "live", "info": str(exc)}
            new_attempts = attempts_so_far + 1
            if new_attempts >= MAX_ATTEMPTS or not exc.retryable:
                await asyncio.to_thread(
                    _mark_failed_sync,
                    row["id"],
                    error_text=f"PERM_FAIL: {exc}" if not exc.retryable else f"GIVEUP: {exc}",
                    attempts_after=new_attempts,
                )
                result.failed += 1
                log.warning(
                    "outbox.worker: row %s permanently failed: %s",
                    row["id"],
                    exc,
                )
                continue
            backoff = compute_backoff_seconds(new_attempts)
            await asyncio.to_thread(
                _mark_retry_sync,
                row["id"],
                error_text=f"transient: {exc}",
                attempts_after=new_attempts,
                next_retry_iso=_iso_in(backoff),
            )
            result.retried += 1
            log.info(
                "outbox.worker: row %s transient fail (%s); retry in %ds",
                row["id"],
                exc,
                backoff,
            )
            continue
        except Exception as exc:  # noqa: BLE001
            # Unexpected error (network bug, JSON error in payload, etc.).
            # Treat as retryable; backoff + state=pending so a future
            # poll picks it up.
            new_attempts = attempts_so_far + 1
            if new_attempts >= MAX_ATTEMPTS:
                await asyncio.to_thread(
                    _mark_failed_sync,
                    row["id"],
                    error_text=f"unhandled: {exc}",
                    attempts_after=new_attempts,
                )
                result.failed += 1
                log.exception(
                    "outbox.worker: row %s permanently failed (unhandled): %s",
                    row["id"],
                    exc,
                )
                continue
            backoff = compute_backoff_seconds(new_attempts)
            await asyncio.to_thread(
                _mark_retry_sync,
                row["id"],
                error_text=f"unhandled: {exc}",
                attempts_after=new_attempts,
                next_retry_iso=_iso_in(backoff),
            )
            result.retried += 1
            log.exception(
                "outbox.worker: row %s unhandled error, retry in %ds",
                row["id"],
                backoff,
            )
            continue

        # Success path
        await asyncio.to_thread(_mark_published_sync, row["id"])
        result.published += 1
        log.info(
            "outbox.worker: row %s published mode=%s info=%s",
            row["id"],
            outcome.get("mode"),
            outcome.get("info"),
        )

    return result


# ---------------------------------------------------------------------------
# Long-running loop
# ---------------------------------------------------------------------------


@dataclass
class _WorkerHandle:
    """Internal handle returned by :func:`start_worker` so tests / lifespan
    can cancel the loop cleanly without holding the task itself.
    """

    task: asyncio.Task[None]
    stopped: asyncio.Event


async def _run_loop(handle: _WorkerHandle) -> None:
    """Body of the worker task: poll → sleep → poll → … → cancel."""
    poll_s = _poll_interval_s()
    log.info(
        "outbox.worker: loop starting poll_s=%s batch=%s", poll_s, _batch_size()
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        while not handle.stopped.is_set():
            try:
                await poll_once(client=client)
            except Exception:  # noqa: BLE001
                # Never let the loop die — log + wait + retry. The most
                # common cause is a transient DB IO error; the next
                # cycle will inherit a clean connection.
                log.exception("outbox.worker: poll_once raised; continuing")
            try:
                await asyncio.wait_for(handle.stopped.wait(), timeout=poll_s)
            except asyncio.TimeoutError:
                pass
    log.info("outbox.worker: loop exiting")


def start_worker() -> _WorkerHandle | None:
    """Spawn the worker on the running event loop.

    Returns ``None`` if ``QIEPAI_OUTBOX_ENABLED=0`` so the caller can
    skip the stop-on-shutdown branch entirely.

    Safe to call multiple times — duplicate calls are deduplicated by
    reusing an existing in-flight handle, with a WARNING log line.

    Also recovers any rows left in ``state='processing'`` from a
    previous worker crash — those rows are moved back to
    ``state='pending'`` so the new loop can re-pick them on its first
    cycle.
    """
    global _ACTIVE_HANDLE  # noqa: PLW0603

    if not _worker_enabled():
        log.info("outbox.worker: disabled via QIEPAI_OUTBOX_ENABLED=0; not starting")
        return None

    if _ACTIVE_HANDLE is not None and not _ACTIVE_HANDLE.task.done():
        log.warning("outbox.worker: already running, returning existing handle")
        return _ACTIVE_HANDLE

    # Recover any rows left in ``state='processing'`` from a previous
    # worker crash. start_worker is sync (called from lifespan), so call
    # the sync helper directly — DB IO is fast and the rowcount is
    # only used for a log line.
    recovered_count = _recover_processing_to_pending_sync()
    if recovered_count:
        log.info(
            "outbox.worker: recovered %d 'processing' row(s) to 'pending'",
            recovered_count,
        )

    handle = _WorkerHandle(
        task=asyncio.create_task(_noop_handle_placeholder()),
        stopped=asyncio.Event(),
    )
    real_task = asyncio.create_task(_run_loop(handle))
    handle.task = real_task
    _ACTIVE_HANDLE = handle
    return handle


async def _noop_handle_placeholder() -> None:  # pragma: no cover
    """Placeholder used only because :func:`_WorkerHandle` requires a task.

    Immediately replaced by the real task before :func:`start_worker`
    returns; never observable from outside.
    """
    return None


async def stop_worker(handle: _WorkerHandle | None) -> None:
    """Signal the worker to exit and wait for the task to drain.

    Idempotent — ``None`` handle (worker never spawned) is a no-op.
    """
    global _ACTIVE_HANDLE  # noqa: PLW0603

    if handle is None:
        _ACTIVE_HANDLE = None
        return

    handle.stopped.set()
    try:
        await asyncio.wait_for(handle.task, timeout=5.0)
    except asyncio.TimeoutError:
        handle.task.cancel()
    except asyncio.CancelledError:
        pass
    finally:
        if _ACTIVE_HANDLE is handle:
            _ACTIVE_HANDLE = None


_ACTIVE_HANDLE: _WorkerHandle | None = None


__all__ = [
    "MAX_ATTEMPTS",
    "MAX_BACKOFF_S",
    "WorkerResult",
    "compute_backoff_seconds",
    "poll_once",
    "start_worker",
    "stop_worker",
    "reset_for_tests",
]


def reset_for_tests() -> None:
    """Test helper: drop the worker handle + reset the token cache."""
    global _ACTIVE_HANDLE
    _ACTIVE_HANDLE = None
    # Also clear the publisher's tenant_access_token cache so two
    # tests in a row start with the same "no token" baseline.
    _reset_publisher_for_tests()
