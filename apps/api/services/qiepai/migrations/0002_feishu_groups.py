"""qiepai · Phase ❸-1 migration — ``feishu_groups`` table.

This migration is **additive**: the ❷-2 ``0001_initial.py`` already
shipped the empty ``outbox_events`` table; ❸-1 only needs the
destinations to point at, stored in ``feishu_groups``.

Table
======

* ``id``           TEXT PK            — ``fgrp_<12-hex>`` (registry helper)
* ``name``         TEXT NOT NULL       — human label for the operator
* ``chat_id``      TEXT NOT NULL UNIQUE — Feishu ``oc_xxx`` chat id
* ``enabled``      INTEGER DEFAULT 1   — boolean 0/1 (boolean check)
* ``created_at``   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
* ``last_used_at`` TIMESTAMP NULL      — bookkeeping for the dashboard

Rationale: the worker picks the *first* enabled group as the
destination; future v2 will fan-out across all enabled groups with
dedup-by-``event_id`` so a single logical event lands in N chats but
each chat only ever sees one card. v1 is fine for the demo where the
operator uses a single primary chat.

Idempotency
===========

All DDL uses ``IF NOT EXISTS`` so re-applying is a no-op. The runner
records the migration name in ``_migration_history`` only after
:func:`apply` returns so a partial failure will be retried.
"""
from __future__ import annotations

import sqlite3

MIGRATION_NAME: str = "0002_feishu_groups"

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS feishu_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    chat_id TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feishu_groups_enabled
    ON feishu_groups(enabled, created_at);
"""


def apply(conn: sqlite3.Connection) -> None:
    """Apply the ``feishu_groups`` table DDL.

    Single ``executescript`` so the create-table + index pair stay
    consistent; re-apply is harmless.
    """
    conn.executescript(SCHEMA_SQL)


__all__ = ["MIGRATION_NAME", "SCHEMA_SQL", "apply"]
