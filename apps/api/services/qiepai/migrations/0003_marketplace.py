"""qiepai · Phase ❹ migration — marketplace scene-template tables.

Adds the three tables backing the scene-template marketplace
(``GET /api/qiepai/marketplace/templates`` and friends):

* ``scene_templates`` — one row per template. ``payload`` is the JSON
  blob an operator can copy into a new employee; ``use_count`` /
  ``rating_avg`` / ``rating_count`` are denormalised aggregates that
  the list endpoint sorts on (recomputed inside the service layer on
  each rating / copy event).

* ``scene_template_ratings`` — one row per (template, user) pair. The
  ``UNIQUE(template_id, user_id)`` constraint is the source of truth for
  "one rating per user" — the service catches the IntegrityError and
  raises a 409 instead of letting SQLite surface a raw FK error.

* ``scene_template_copies`` — append-only audit log of who copied which
  template to which employee. Backs the ``GET …/copies`` endpoint and
  feeds the ``use_count`` denormalisation on ``scene_templates``.

FK semantics
============

``scene_template_ratings.template_id`` and
``scene_template_copies.template_id`` reference
``scene_templates(id)``. ❹ ships with the single-tenant
``"huilton_seed"`` placeholder (mirrors the ❷-3 metric seed +
❷-5/❷-6 decision/employee services' ``DEFAULT_ENTERPRISE_ID``); the
service layer uses the same ``PRAGMA foreign_keys = OFF`` /
``ON`` dance the decisions/employees services use, so the FK check
still fires for any *real* misuse (bad template id, unknown employee
id) once the demo enterprise row exists.

``scene_template_copies.target_employee_id`` references
``employees(id)`` — the copy endpoint always passes a real employee
id (either the auto-created one or the operator-supplied one) so this
FK is enforced in practice.

Idempotency
===========

Every DDL uses ``IF NOT EXISTS`` so a re-apply is a no-op. The runner
records the migration name in ``_migration_history`` only after
:func:`apply` returns so a partial failure will be retried.
"""
from __future__ import annotations

import sqlite3

MIGRATION_NAME: str = "0003_marketplace"

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS scene_templates (
    id TEXT PRIMARY KEY,                      -- stpl_<12-hex>
    enterprise_id TEXT NOT NULL,              -- single-tenant placeholder "huilton_seed"
    name TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,                   -- customer_service / sales / finance / hr / ops
    industry TEXT,                            -- 二级分类
    payload TEXT NOT NULL,                    -- JSON 完整 scene_assets 配置
    tags TEXT,                                -- JSON array
    source TEXT NOT NULL DEFAULT 'user',      -- user / builtin / imported
    enabled INTEGER NOT NULL DEFAULT 1,       -- 公开 marketplace 可见 (软删 = 0)
    created_by TEXT,                          -- user_id (manager 引用)
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    use_count INTEGER NOT NULL DEFAULT 0,
    rating_avg REAL NOT NULL DEFAULT 0,
    rating_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_scene_templates_enabled_category
    ON scene_templates(enabled, category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scene_templates_use_count
    ON scene_templates(use_count DESC, rating_avg DESC);

CREATE TABLE IF NOT EXISTS scene_template_ratings (
    id TEXT PRIMARY KEY,                      -- rt_<12-hex>
    template_id TEXT NOT NULL REFERENCES scene_templates(id),
    user_id TEXT,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(template_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_scene_template_ratings_template
    ON scene_template_ratings(template_id, created_at DESC);

CREATE TABLE IF NOT EXISTS scene_template_copies (
    id TEXT PRIMARY KEY,                      -- cp_<12-hex>
    template_id TEXT NOT NULL REFERENCES scene_templates(id),
    copied_by TEXT,
    target_employee_id TEXT REFERENCES employees(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_scene_template_copies_template
    ON scene_template_copies(template_id, created_at DESC);
"""


def apply(conn: sqlite3.Connection) -> None:
    """Apply the marketplace DDL block (3 tables + 4 indexes).

    Single ``executescript`` so the create-table + index pair stay
    consistent; re-apply is harmless because of the ``IF NOT EXISTS``
    guards above.
    """
    conn.executescript(SCHEMA_SQL)


__all__ = ["MIGRATION_NAME", "SCHEMA_SQL", "apply"]