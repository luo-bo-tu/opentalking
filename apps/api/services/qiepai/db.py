"""qiepai · DB connection helper (Phase ❷-2).

Phase ❷-2 creates ``data/qiepai-enterprise.sqlite`` — fully independent from
``data/opentalking.sqlite3`` (voice catalog) and ``data/agent_memory.sqlite``
(agent long-term memory). All access uses stdlib ``sqlite3`` (sync); async
callers (FastAPI lifespan / routes) wrap blocking operations with
``asyncio.to_thread`` to avoid stalling the event loop.

The PRAGMA defaults mirror the conventions established by the existing
``opentalking.voice.store`` / ``opentalking.agent.memory_store`` modules
(see ``apps/unified/main.py`` lifespan):
  * WAL journal mode for concurrent reads
  * ``foreign_keys=ON`` per-connection (SQLite defaults to OFF, which would
    silently disable every ``REFERENCES`` clause declared in 0001_initial)
  * ``row_factory=sqlite3.Row`` so business code can address columns by name
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

#: Default DB path (relative to cwd at lifespan startup).
_DEFAULT_DB_PATH = "./data/qiepai-enterprise.sqlite"
#: Override via env var. Mirrors the ``OPENTALKING_SQLITE_PATH`` style.
_ENV_VAR = "QIEPAI_ENTERPRISE_DB_PATH"


def get_db_path() -> Path:
    """Resolve the DB path and ensure its parent directory exists.

    Resolution order:

    1. ``$QIEPAI_ENTERPRISE_DB_PATH`` (if non-empty)
    2. ``./data/qiepai-enterprise.sqlite`` (relative to cwd)

    Returns an absolute path; the parent is created with ``mkdir -p`` so the
    very first connect() never fails on a missing directory.
    """
    raw = os.environ.get(_ENV_VAR, "").strip() or _DEFAULT_DB_PATH
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect() -> sqlite3.Connection:
    """Open a connection with the qiepai-standard PRAGMAs.

    - ``timeout=10.0`` tolerates short contention during lifespan startup
      (the ``opentalking`` voice store uses 5.0; we double that for safety).
    - ``check_same_thread=False`` mirrors ``opentalking/voice/store.py``; safe
      because every qiepai touchpoint goes through ``asyncio.to_thread`` which
      uses a single worker pool.
    - ``row_factory=sqlite3.Row`` so callers can use ``row["column_name"]``.
    - ``PRAGMA journal_mode=WAL`` for concurrent-read friendliness.
    - ``PRAGMA foreign_keys=ON`` — without this, every ``REFERENCES`` clause
      declared in 0001_initial is silently ignored by SQLite.
    """
    path = get_db_path()
    conn = sqlite3.connect(str(path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


__all__ = ["get_db_path", "connect"]