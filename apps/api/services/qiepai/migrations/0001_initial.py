"""qiepai · ❷-2 initial migration (11-domain P0-D schema).

This file declares the complete Phase ❷-2 schema for the qiepai enterprise
business layer. Per spec section 2.1 (``qiepai-claw-stage2-spec.md``), this
is the **initial** migration; ❷-3 ~ ❷-6 will ship their own migration files
(e.g. ``0002_seed_huilton.py``) rather than amend this one.

Tables (11, in spec order):

  1. ``enterprise_spaces``        — 4-level tree, materialized path, seed flag
  2. ``employees``                — digital employees; FK enterprise + nullable persona
  3. ``employee_revisions``       — config snapshots; UNIQUE(employee_id, revision_number)
  4. ``data_connectors``          — connector metadata + probe state
  5. ``ontology_types``           — ontology type definitions (versioned)
  6. ``metric_definitions``       — KPI/metric definitions (versioned)
  7. ``metric_snapshots``         — point-in-time metric values (NULL = unavailable)
  8. ``decision_items``           — decision queue (FK metric + snapshot + JSON)
  9. ``business_tasks``           — task queue (FK decision + OpenClaw runtime_task_id)
  10. ``audit_events``            — append-only audit log
  11. ``outbox_events``           — transactional outbox for downstream publishing

INDEXes (3, additive — these are *not* in spec 2.1 verbatim but are needed by
the most likely business queries in ❷-3+):

  - ``idx_employees_enterprise``    ON ``employees(enterprise_id)``
  - ``idx_decision_items_open``     ON ``decision_items(enterprise_id, status, created_at DESC)``
  - ``idx_outbox_pending_retry``    ON ``outbox_events(state, next_retry_at)``

All DDL is wrapped in ``IF NOT EXISTS`` so a re-apply is a no-op. The runner
guards against double-apply via ``_migration_history`` regardless.

JSON fields are stored as ``TEXT`` (spec convention; SQLite has no native JSON
type). The bundled SQLite 3.53 ships the JSON1 extension so business code may
later use ``json_extract(column, '$.field')`` for filtering — that is **not**
exercised here.
"""
from __future__ import annotations

import sqlite3

MIGRATION_NAME: str = "0001_initial"

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS enterprise_spaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    path TEXT NOT NULL,
    level INTEGER NOT NULL,
    inheritance_policy TEXT NOT NULL DEFAULT 'inherit',
    seed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL REFERENCES enterprise_spaces(id),
    persona_id TEXT,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    current_revision_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_employees_enterprise
    ON employees(enterprise_id);

CREATE TABLE IF NOT EXISTS employee_revisions (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    revision_number INTEGER NOT NULL,
    workspace_file_hash TEXT NOT NULL,
    config_snapshot TEXT NOT NULL,
    publish_state TEXT NOT NULL DEFAULT 'draft',
    readiness_p0 BOOLEAN NOT NULL DEFAULT 0,
    readiness_p1 BOOLEAN NOT NULL DEFAULT 0,
    sync_state TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(employee_id, revision_number)
);

CREATE TABLE IF NOT EXISTS data_connectors (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL REFERENCES enterprise_spaces(id),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_probe_at TIMESTAMP,
    last_probe_state TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ontology_types (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL REFERENCES enterprise_spaces(id),
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    schema TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metric_definitions (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL REFERENCES enterprise_spaces(id),
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    formula TEXT NOT NULL,
    display_unit TEXT,
    display_format TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL REFERENCES metric_definitions(id),
    scope TEXT NOT NULL,
    as_of TIMESTAMP NOT NULL,
    freshness_seconds INTEGER NOT NULL,
    value REAL,
    source TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decision_items (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL REFERENCES enterprise_spaces(id),
    title TEXT NOT NULL,
    description TEXT,
    metric_id TEXT REFERENCES metric_definitions(id),
    snapshot_id TEXT REFERENCES metric_snapshots(id),
    fact_snapshot TEXT NOT NULL,
    ai_suggestion TEXT,
    owner_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_at TIMESTAMP,
    decision_text TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_decision_items_open
    ON decision_items(enterprise_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS business_tasks (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT NOT NULL REFERENCES enterprise_spaces(id),
    decision_id TEXT REFERENCES decision_items(id),
    title TEXT NOT NULL,
    description TEXT,
    assignee_id TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    runtime_task_id TEXT,
    session_key TEXT,
    run_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    enterprise_id TEXT,
    actor_id TEXT,
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    payload TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outbox_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_retry_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending_retry
    ON outbox_events(state, next_retry_at);
"""


def apply(conn: sqlite3.Connection) -> None:
    """Apply the initial schema to ``conn``.

    DDL is dispatched via ``executescript`` which auto-commits each statement
    (the sqlite3 driver issues an implicit COMMIT before running multi-statement
    scripts). We rely on the fact that every statement uses ``IF NOT EXISTS``
    so a partial apply — e.g. due to a transient I/O error mid-script — will
    be safely re-runnable on the next migration attempt. The history row is
    written by the runner **only after** ``apply`` returns successfully, so a
    raised exception means the migration will be retried on the next call.
    """
    conn.executescript(SCHEMA_SQL)


__all__ = ["MIGRATION_NAME", "SCHEMA_SQL", "apply"]