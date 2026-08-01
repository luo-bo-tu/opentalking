"""qiepai · SQL migration scripts (Phase ❷-2+).

Each module in this package (excluding this ``__init__`` and any private
modules whose name starts with ``_``) declares a single migration via three
attributes:

- ``MIGRATION_NAME: str`` — unique key recorded in ``_migration_history``.
  Convention: zero-padded sequence + snake_case label, e.g.
  ``"0001_initial"``, ``"0002_seed_huilton"``.
- ``SCHEMA_SQL: str`` — DDL/DML to apply. Every DDL statement must use
  ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` so that
  re-running this module on an already-applied DB is a no-op.
- ``apply(conn: sqlite3.Connection) -> None`` — hook invoked by the runner
  inside a transaction. Should ``raise`` on failure (no swallowing).

Modules are discovered and ordered by ``pkgutil.iter_modules`` (sorted
filename). The runner applies every unapplied migration exactly once.
"""
from __future__ import annotations

__all__: list[str] = []