"""qiepai · Feishu chat-id registry (Phase ❸-1).

Stores one row per Feishu group the operator wants notifications
delivered to. The outbox worker calls :func:`first_active_chat_id`
once per cycle to pick the destination; future iterations will switch
to fan-out (one row per group, dedup by ``event_id``), but for the
v1 demo a single primary chat suffices.

Schema (``feishu_groups``)
==========================

* ``id``           TEXT PRIMARY KEY (``fgrp_<12-hex>``)
* ``name``         TEXT NOT NULL              — human label
* ``chat_id``      TEXT NOT NULL UNIQUE       — Feishu ``chat_id``
* ``enabled``      INTEGER NOT NULL DEFAULT 1 — boolean (0 / 1)
* ``created_at``   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
* ``last_used_at`` TIMESTAMP NULL             — bookkeeping for the
                                                  operator dashboard

Migration
=========

Table is created by ``apps/api/services/qiepai/migrations/0002_feishu_groups.py``,
applied on startup by :func:`apps.api.services.qiepai.migration_runner.run_pending_migrations`.

The first migration (``0001_initial``) ships an empty ``feishu_groups``
table — operators add groups via the POST endpoint or the web UI.
The single row id used by the worker (when no manual config has been
done) defaults to empty so the publisher enters dry-run.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any, Final
from uuid import uuid4

from .. import db

log = logging.getLogger(__name__)


#: Convenience constant so workers / routers don't have to compute the
#: empty-string sentinel themselves.
EMPTY_CHAT_ID: Final[str] = ""


@dataclass
class FeishuGroup:
    """In-memory representation of a ``feishu_groups`` row."""

    id: str
    name: str
    chat_id: str
    enabled: bool
    created_at: str
    last_used_at: str | None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (matches the published row shape)."""
        d = asdict(self)
        d["enabled"] = bool(d["enabled"])
        return d


def _row_to_group(row: sqlite3.Row) -> FeishuGroup:
    return FeishuGroup(
        id=str(row["id"]),
        name=str(row["name"]),
        chat_id=str(row["chat_id"]),
        enabled=bool(row["enabled"]),
        created_at=str(row["created_at"]),
        last_used_at=row["last_used_at"],
    )


# ---------------------------------------------------------------------------
# Sync IO helpers (wrapped in asyncio.to_thread by callers)
# ---------------------------------------------------------------------------


def _list_sync() -> list[FeishuGroup]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, chat_id, enabled, created_at, last_used_at "
            "FROM feishu_groups ORDER BY created_at ASC, id ASC"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_group(r) for r in rows]


def _create_sync(*, name: str, chat_id: str, enabled: bool = True) -> FeishuGroup:
    new_id = f"fgrp_{uuid4().hex[:12]}"
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO feishu_groups (id, name, chat_id, enabled) "
            "VALUES (?, ?, ?, ?)",
            (new_id, name, chat_id, 1 if enabled else 0),
        )
        conn.commit()
        cur.execute(
            "SELECT id, name, chat_id, enabled, created_at, last_used_at "
            "FROM feishu_groups WHERE id = ?",
            (new_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:  # pragma: no cover — INSERT just succeeded
        raise RuntimeError("feishu_groups row vanished after insert")
    return _row_to_group(row)


def _delete_sync(group_id: str) -> bool:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM feishu_groups WHERE id = ?", (group_id,))
        conn.commit()
        rowcount = cur.rowcount
    finally:
        conn.close()
    return rowcount > 0


def _first_active_chat_id_sync() -> str:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_id FROM feishu_groups WHERE enabled = 1 "
            "ORDER BY created_at ASC, id ASC LIMIT 1"
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return EMPTY_CHAT_ID
    return str(row["chat_id"])


def _touch_used_sync(group_id: str) -> None:  # pragma: no cover — bookkeeping
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE feishu_groups SET last_used_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (group_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public async helpers
# ---------------------------------------------------------------------------


class ChatIdRegistry:
    """Tiny façade exposing the common operations on the ``feishu_groups`` table.

    Two design decisions worth flagging:

    1. Every DB call goes through ``asyncio.to_thread`` because the
       underlying ``sqlite3`` connection is sync (per the qiepai
       convention). Callers (routes + worker) already expect async
       signatures.
    2. The class is **not** a singleton — :func:`get_registry` returns
       a module-level instance, but tests can construct a fresh one
       if they need a clean slate (current tests pass via the env
       var override + per-test temp DB).
    """

    async def list_groups(self) -> list[FeishuGroup]:
        return await asyncio.to_thread(_list_sync)

    async def create_group(
        self, *, name: str, chat_id: str, enabled: bool = True
    ) -> FeishuGroup:
        if not name.strip():
            raise ValueError("group name must be non-empty")
        if not chat_id.strip():
            raise ValueError("chat_id must be non-empty")
        return await asyncio.to_thread(
            _create_sync, name=name.strip(), chat_id=chat_id.strip(), enabled=enabled
        )

    async def delete_group(self, group_id: str) -> bool:
        return await asyncio.to_thread(_delete_sync, group_id)


_REGISTRY = ChatIdRegistry()


def get_registry() -> ChatIdRegistry:
    """Process-singleton accessor — used by routers and tests."""
    return _REGISTRY


async def first_active_chat_id() -> str:
    """Return the chat_id of the first enabled Feishu group, or ``""``.

    The empty-string sentinel tells the publisher to enter dry-run,
    which logs the message body instead of POSTing it — this is the
    expected behaviour when the operator hasn't configured any
    destination yet.
    """
    return await asyncio.to_thread(_first_active_chat_id_sync)


__all__ = [
    "EMPTY_CHAT_ID",
    "FeishuGroup",
    "ChatIdRegistry",
    "get_registry",
    "first_active_chat_id",
]
