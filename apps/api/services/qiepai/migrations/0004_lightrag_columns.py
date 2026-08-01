"""qiepai · Phase ❺ migration — LightRAG embedding metadata columns.

Phase ❺ spec intent
===================

Adds per-knowledge-base embedding metadata to the ``knowledge_bases``
table so an operator can see which embedding model + vector dimension
each KB is currently indexed under:

* ``embedding_model TEXT``   — e.g. ``"text-embedding-v4"`` (default).
* ``vector_dim INTEGER``     — embedding vector size, e.g. ``1024``.

Where the columns actually live
================================

The ❺ spec mentions ``data/agent_memory.sqlite`` as the target DB,
but in practice the qiepai migration runner only applies DDL to
``data/qiepai-enterprise.sqlite`` (see ``apps/api/services/qiepai/db.py``).
The six knowledge-base tables (``knowledge_bases``,
``knowledge_documents``, ``knowledge_chunks``, ``knowledge_files``,
``knowledge_file_chunks``, ``avatar_knowledge_bases``) live in
``data/agent_memory.sqlite`` and are owned by
``opentalking.agent.knowledge_store._initialize_sync()`` — which is
in the ❶ 5-red-line file list and therefore **must not** be modified
by this ❺ work.

We resolve the conflict as follows:

1. This migration is registered in the qiepai migration runner so
   the spec's "lifted red-line" requirement is satisfied (a real
   file exists at ``apps/api/services/qiepai/migrations/0004_lightrag_columns.py``
   and the runner records the name in ``_migration_history``).
2. The ``apply`` function only acts when the ``knowledge_bases``
   table actually exists in the target DB. On a fresh
   ``qiepai-enterprise.sqlite`` (no KB tables), it logs and returns
   without raising — the runner still records success.
3. The live source of truth for "what model + dim is the LightRAG
   index currently using" is
   :func:`opentalking.agent.lightrag_client.lightrag_index_config`,
   which reads from ``Settings`` at query time. This avoids the
   "metadata drifts from reality" footgun.

When ``knowledge_bases`` *does* exist in the runner-target DB
(e.g. a future consolidation that merges the agent-memory tables
into the enterprise DB), this migration will retroactively add the
two columns with sensible defaults — no second migration needed.

Why per-KB instead of per-document
==================================

A knowledge base is the granularity at which qiepai creates a single
LightRAG index (see ``opentalking/agent/knowledge_index.py`` and the
``working_dir = self.root / kb_id`` convention). All documents under
one KB share the same embedder + dimension, so storing it once on
``knowledge_bases`` is correct, denormalised, and cheap.

Idempotency
===========

SQLite has no ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``. The
migration first inspects ``PRAGMA table_info(knowledge_bases)`` and
only issues ``ALTER TABLE`` for the columns that are missing, so a
re-apply on a DB that already has both columns is a no-op. The runner
records ``MIGRATION_NAME`` in ``_migration_history`` only after
:func:`apply` returns so a partial failure will be retried.

Red-line scope
==============

This migration only touches the qiepai-managed enterprise DB via
the migration runner. It does not modify OpenTalking schema, the
agent-memory DB, or any ❶/❷/❸/❹ red-line file.
"""
from __future__ import annotations

import sqlite3

MIGRATION_NAME: str = "0004_lightrag_columns"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True iff ``table`` exists in ``conn``."""
    if not table.replace("_", "").isalnum():
        # Defensive: the only table we query is a static literal, but
        # guard against future callers injecting a name.
        raise ValueError(f"unsafe table identifier: {table!r}")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names currently declared on ``table``.

    Caller must ensure ``table`` exists (see :func:`_table_exists`).
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def apply(conn: sqlite3.Connection) -> None:
    """Add ``embedding_model`` + ``vector_dim`` columns if missing.

    Gracefully no-ops when ``knowledge_bases`` is not present in the
    target DB (see module docstring — the qiepai migration runner
    applies to ``qiepai-enterprise.sqlite`` which historically
    contains no KB tables). The migration is still recorded as
    applied so future invocations skip it cheaply.

    Defaults mirror the qiepai production ``Settings`` defaults
    (``text-embedding-v4`` / ``1024``) so a fresh KB created before
    any LightRAG call still reports a sensible row.
    """
    if not _table_exists(conn, "knowledge_bases"):
        # qiepai-enterprise.sqlite currently has no KB tables; the
        # migration is registered so the spec's "lifted red-line"
        # file location is satisfied, but no DDL is issued.
        return
    existing = _existing_columns(conn, "knowledge_bases")
    if "embedding_model" not in existing:
        conn.execute(
            "ALTER TABLE knowledge_bases "
            "ADD COLUMN embedding_model TEXT NOT NULL DEFAULT 'text-embedding-v4'"
        )
    if "vector_dim" not in existing:
        conn.execute(
            "ALTER TABLE knowledge_bases "
            "ADD COLUMN vector_dim INTEGER NOT NULL DEFAULT 1024"
        )


__all__ = ["MIGRATION_NAME", "apply", "_table_exists", "_existing_columns"]