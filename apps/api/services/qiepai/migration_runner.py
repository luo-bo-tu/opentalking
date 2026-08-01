"""qiepai · migration runner (Phase ❷-2).

Idempotently applies every pending migration in
``apps.api.services.qiepai.migrations`` to the qiepai enterprise database.

This module is a **sibling** of the ``migrations`` package — not a child —
so it is not itself picked up by ``pkgutil.iter_modules(migrations.__path__)``
as a candidate migration. The discovery code would correctly skip files
whose name starts with ``_`` (the convention for internal helpers), but
keeping the runner outside the migrations package is semantically cleaner:
the runner is the engine, not a migration script.

Public entry point:

- ``run_pending_migrations()`` — async, safe to call from FastAPI lifespan.
  Wraps the sync sqlite3 work in ``asyncio.to_thread`` so the event loop is
  not blocked during initial startup.

Lifecycle:

1. Resolve the DB path (env-overridable) and open a connection.
2. Bootstrap ``_migration_history`` (idempotent ``CREATE TABLE IF NOT EXISTS``)
   so future migrations don't have to (re)create the bookkeeping table.
3. Read already-applied migration names.
4. Iterate the migrations package in sorted-name order; for each unapplied
   module, call ``apply(conn)`` then record the history row + commit.
5. Close the connection.

Failure semantics: any exception inside a migration is re-raised after the
in-flight transaction is rolled back. The lifespan wrapper logs and continues
so OpenTalking routes still boot — only the qiepai routes will 500 until the
migration is fixed on a subsequent restart.
"""
from __future__ import annotations

import asyncio
import logging
import pkgutil
import sqlite3
from importlib import import_module
from types import ModuleType
from typing import Final

from apps.api.services.qiepai import db

log = logging.getLogger(__name__)

MIGRATIONS_PACKAGE: Final[str] = "apps.api.services.qiepai.migrations"
#: Bookkeeping table tracking applied migrations. Lives independently of the
#: business tables so the history survives even if every business table is
#: dropped during ❷-3+ iteration.
HISTORY_TABLE: Final[str] = "_migration_history"
HISTORY_DDL: Final[str] = (
    "CREATE TABLE IF NOT EXISTS _migration_history ("
    "  id INTEGER PRIMARY KEY,"
    "  name TEXT UNIQUE NOT NULL,"
    "  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ")"
)


def _iter_migration_modules() -> list[ModuleType]:
    """Discover and import migration modules in sorted ``MIGRATION_NAME`` order.

    Skips the package ``__init__`` and any private modules whose name starts
    with ``_``. Discovery uses ``pkgutil.iter_modules`` which respects the
    package's ``__path__`` and is robust to bytecode-only stubs.

    Sorting by ``MIGRATION_NAME`` (rather than import order) means the on-disk
    order of files is irrelevant — e.g. ``0009_seed.py`` correctly runs after
    ``0010_initial.py`` if someone accidentally renames it.
    """
    package = import_module(MIGRATIONS_PACKAGE)
    modules: list[ModuleType] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        name = module_info.name
        if name.startswith("_"):
            continue
        full_name = f"{MIGRATIONS_PACKAGE}.{name}"
        modules.append(import_module(full_name))
    modules.sort(key=lambda m: getattr(m, "MIGRATION_NAME", m.__name__))
    return modules


def _list_applied(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(f"SELECT name FROM {HISTORY_TABLE}").fetchall()
    return {r["name"] for r in rows}


def _apply_one(conn: sqlite3.Connection, module: ModuleType) -> str:
    """Apply a single migration module; return its ``MIGRATION_NAME``.

    Validates the required ``MIGRATION_NAME`` attribute is a non-empty string
    so we fail fast on misconfigured modules.
    """
    name = getattr(module, "MIGRATION_NAME", None)
    if not isinstance(name, str) or not name:
        raise RuntimeError(
            f"migration {module.__name__!r} missing MIGRATION_NAME str attribute"
        )
    log.info("qiepai migration: applying %s", name)
    module.apply(conn)
    conn.execute(
        f"INSERT INTO {HISTORY_TABLE} (name) VALUES (?)",
        (name,),
    )
    return name


def _run_pending_sync() -> list[str]:
    """Synchronous core. Returns the list of newly-applied migration names."""
    path = db.get_db_path()
    log.info("qiepai migration: target db = %s", path)
    conn = db.connect()
    try:
        # Bootstrap history table — independent of any business migration so
        # future migrations don't have to recreate it.
        conn.executescript(HISTORY_DDL)
        conn.commit()
        applied_before = _list_applied(conn)
        log.info(
            "qiepai migration: %d already applied: %s",
            len(applied_before),
            sorted(applied_before) or "(none)",
        )
        newly_applied: list[str] = []
        for module in _iter_migration_modules():
            raw_name = getattr(module, "MIGRATION_NAME", None)
            if not isinstance(raw_name, str) or not raw_name:
                raise RuntimeError(
                    f"migration {module.__name__!r} missing MIGRATION_NAME str attribute"
                )
            name: str = raw_name
            if name in applied_before:
                continue
            _apply_one(conn, module)
            conn.commit()
            newly_applied.append(name)
        return newly_applied
    finally:
        conn.close()


async def run_pending_migrations() -> list[str]:
    """Apply every pending qiepai migration; return the list of newly-applied names.

    Safe to call multiple times — already-applied migrations are skipped.
    Re-raises on any DDL / data error so the caller (lifespan) can log and
    decide whether to fail-fast.
    """
    return await asyncio.to_thread(_run_pending_sync)


__all__ = ["run_pending_migrations"]