"""qiepai · initial metric seed (Phase ❷-3).

Lives **outside** the migration system on purpose. Per spec § 3 (拿不准点
#5 in section 0), mock JSON content will iterate across ❷-3 → ❷-6;
piggy-backing those changes on migrations would inflate
``_migration_history`` with rows that have no schema impact. Instead, this
seed step is called from the FastAPI ``lifespan`` after migrations finish,
is fully idempotent (``INSERT OR IGNORE`` + deterministic primary keys),
and only touches the qiepai enterprise database.

What gets seeded
================

1. **Five ``metric_definitions`` rows**, one per mock JSON asset:
     - ``financial-kpi``           (value KPI, currency)
     - ``sales-trend``             (12-month trend series)
     - ``customer-concentration``  (top-5 customer share)
     - ``orders-ar``               (orders vs AR outstanding)
     - ``target-attainment``       (annual target progress, fraction)

   ``enterprise_id`` is set to a placeholder string ``"huilton_seed"``.
   ❷-4 will swap this for a real ``enterprise_spaces.id`` once the
   single-tenant seed (拿不准点 #1) is added; the placeholder is harmless
   today because nothing in ❷-3 queries across enterprises.

2. **Five ``metric_snapshots`` rows** (one per metric, scope = ``"default"``).
   The snapshot's ``value`` and ``freshness_seconds`` are pulled from the
   mock JSON at seed time via :func:`load_kpi_snapshot`. The snapshot
   primary key is ``snap_<metric_id>_<scope>`` — deterministic, so a
   restart re-running this function is a no-op.

Idempotency contract
====================

* Re-running :func:`seed_initial_metrics` returns ``0`` (rows inserted) on
  every call after the first.
* The mock JSON is **not** re-read on every restart: snapshots are written
  with the values present at first seed time. If the mock JSON changes
  between restarts, the seed will *not* update the DB row. This is
  intentional for ❷-3 — the eventual sync (every-N-seconds refresh) is
  a ❷-4 concern; for now, "snapshot reflects what was on disk at first
  boot" is the documented behaviour.

Why ``INSERT OR IGNORE`` and not ``SELECT … INSERT``
====================================================

* O(1) per row regardless of table size.
* Atomic at the statement level (no transaction window where two workers
  could double-insert).
* Plays nicely with SQLite's WAL mode — no read-then-write race.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from apps.api.services.qiepai import db
from apps.api.services.qiepai.connectors import MOCK_CONNECTORS
from apps.api.services.qiepai.metrics import load_kpi_snapshot

log = logging.getLogger(__name__)

#: Placeholder enterprise id used until ❷-4 ships the real
#: ``enterprise_spaces`` seed (拿不准点 #1). Harmless for ❷-3 because the
#: seed step never queries ``metric_definitions`` by ``enterprise_id``.
_SEED_ENTERPRISE_ID: str = "huilton_seed"

#: Five metric definitions, one per mock JSON. Order is irrelevant — the
#: SQL is keyed by primary key, not insertion order. Keep this list in
#: lock-step with ``MOCK_CONNECTORS`` (both should have exactly five entries).
_METRIC_DEFS: list[dict[str, str | None]] = [
    {
        "id": "financial-kpi",
        "name": "财务 KPI 总览",
        "source": "mock://financial-kpi/v1",
        "formula": "value",
        "display_unit": "CNY",
        "display_format": "currency",
    },
    {
        "id": "sales-trend",
        "name": "销售趋势 (12 月)",
        "source": "mock://sales-trend/v1",
        "formula": "items[*].revenue",
        "display_unit": "CNY",
        "display_format": "series",
    },
    {
        "id": "customer-concentration",
        "name": "客户集中度 (Top 5)",
        "source": "mock://customer-concentration/v1",
        "formula": "items[*].share_pct",
        "display_unit": "%",
        "display_format": "pie",
    },
    {
        "id": "orders-ar",
        "name": "订单 / 应收结构",
        "source": "mock://orders-ar/v1",
        "formula": "items[*].orders, items[*].ar_outstanding",
        "display_unit": "CNY",
        "display_format": "stacked_bar",
    },
    {
        "id": "target-attainment",
        "name": "目标达成",
        "source": "mock://target-attainment/v1",
        "formula": "value",
        "display_unit": "",
        "display_format": "progress",
    },
]


def _seed_sync(payloads: dict[str, dict[str, Any] | None]) -> int:
    """Synchronous DB write core. Returns count of newly-inserted rows.

    ``payloads`` is the dict returned by :func:`_collect_snapshots`. We
    pass it in (rather than re-collecting inside the thread) so all the
    async work happens on the FastAPI event loop and the worker thread
    only touches the DB — avoiding nested ``asyncio.run``.

    Foreign-key handling
    --------------------

    ``metric_definitions.enterprise_id`` REFERENCES ``enterprise_spaces(id)``
    (NOT NULL). ❷-3 uses the placeholder ``"huilton_seed"`` for that column
    per spec 拿不准点 #1 (do NOT seed the real enterprise row in ❷-3 — that
    belongs to ❷-4), so the referenced enterprise row does not exist yet.
    We therefore temporarily disable ``PRAGMA foreign_keys`` for the seed
    transaction (documented SQLite pattern for forward-reference seeding)
    and re-enable it before closing the connection. This isolates the
    relaxed constraint to seed time only — every other code path keeps the
    strict FK check that ``db.connect()`` turns on by default.
    """
    conn = db.connect()
    inserted = 0
    try:
        # Relax FK only inside this connection's lifetime. We re-enable in
        # the finally block below; using the connection's own PRAGMA (not a
        # global one) means other connections in the WAL pool are unaffected.
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        for mdef in _METRIC_DEFS:
            metric_id = mdef["id"]
            if metric_id not in MOCK_CONNECTORS:
                # Defensive: keep DB and registry in lock-step. If someone
                # adds a row to _METRIC_DEFS but forgets the JSON asset
                # (or vice versa), we want a loud failure at seed time,
                # not a silently-broken cockpit page.
                log.error("seed: metric %r in _METRIC_DEFS but missing from MOCK_CONNECTORS", metric_id)
                continue
            cur.execute(
                "INSERT OR IGNORE INTO metric_definitions "
                "(id, enterprise_id, name, version, source, formula, display_unit, display_format) "
                "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                (
                    metric_id,
                    _SEED_ENTERPRISE_ID,
                    mdef["name"],
                    mdef["source"],
                    mdef["formula"],
                    mdef["display_unit"],
                    mdef["display_format"],
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
                log.info("seed: inserted metric_definitions %r", metric_id)
        conn.commit()

        # Snapshots were read from the live mock JSON via the async
        # loader before this thread was spawned — source-of-truth stays
        # on disk for ❷-4+ iterations. We just persist what the loader
        # returned; ``None`` means "unavailable at seed time" and we
        # intentionally do not write a row (a missing snapshot is a
        # first-class state, not an error).
        cur = conn.cursor()
        for metric_id, payload in payloads.items():
            if payload is None:
                log.warning("seed: snapshot for %r unavailable; skipping row", metric_id)
                continue
            snapshot_id = f"snap_{metric_id}_default"
            cur.execute(
                "INSERT OR IGNORE INTO metric_snapshots "
                "(id, metric_id, scope, as_of, freshness_seconds, value, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    metric_id,
                    "default",
                    payload["as_of"],
                    int(payload["freshness_seconds"]),
                    payload["value"],
                    payload["source"],
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
                log.info("seed: inserted metric_snapshot %r", snapshot_id)
        conn.commit()
        return inserted
    finally:
        # Restore the strict FK check before close so the connection is
        # left in the same state as a fresh ``db.connect()`` — defensive
        # in case someone reuses the connection object by accident.
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()


async def _collect_snapshots() -> dict[str, dict[str, Any] | None]:
    """Read every registered mock connector through the async loader.

    Runs all five concurrently via :func:`asyncio.gather` so a slow disk
    does not translate into five sequential awaits. The returned dict is
    keyed by metric id and preserves the registry order via Python's
    dict insertion semantics (CPython 3.7+).
    """
    names = list(MOCK_CONNECTORS.keys())
    results = await asyncio.gather(
        *(load_kpi_snapshot(name, scope="default") for name in names),
        return_exceptions=False,
    )
    return dict(zip(names, results))


async def seed_initial_metrics() -> int:
    """Idempotent seed of metric_definitions + metric_snapshots.

    Safe to call from the FastAPI ``lifespan`` after
    ``run_pending_migrations()``. Returns the number of newly-inserted
    rows in this invocation (``0`` on every call after the first).
    Re-raises on DB IO errors so the lifespan wrapper can log + skip.
    """
    payloads = await _collect_snapshots()
    return await asyncio.to_thread(_seed_sync, payloads)


__all__ = ["seed_initial_metrics"]
