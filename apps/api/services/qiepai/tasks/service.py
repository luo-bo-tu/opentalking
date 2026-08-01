"""qiepai · business tasks service implementation (Phase ❷-6).

Single business-layer module backing ``apps/api/routes/qiepai/tasks.py``.
Owns the lifecycle of ``business_tasks`` rows (CRUD + status state machine
+ soft-delete).

Why this is one file
====================

Business tasks are a flat queue — single table, no joins (the optional
``decision_id`` is a soft reference for the operator UI; we don't enforce
referential lookups at read time, see 拿不准点 below). Splitting across
files would inflate the diff without unlocking any independence.

Tables touched
==============

* ``business_tasks`` (read + write) — the only authoritative store.

State machine (架构 § 21.5)
===========================

``_STATUS_TRANSITIONS`` is the single source of truth for legal
``status`` mutations. Terminal states (``done``, ``cancelled``) reject
further status transitions with :class:`BusinessTaskStateError` (the
route layer turns that into HTTP 409); however ``description`` and
``assignee_id`` remain editable on terminal rows so operators can add
post-hoc context without having to reopen the task. ``title`` is
immutable once created (no PATCH handler accepts it; matches the spec's
"audit-trail-friendly" tone for the decisions module).

Soft-delete contract
====================

``DELETE /tasks/{id}`` performs a **physical** delete (not soft) per the
spec's "软删或物理删 (大总管拍)" — the demo tenant is single-tenant and
the audit log (``audit_events``) lives outside this module, so physical
delete keeps the task table clean without losing forensic context. If
later phases need soft-delete (e.g. compliance retention), this is the
single place to swap in an ``is_deleted`` flag.

FK handling
===========

``business_tasks.enterprise_id REFERENCES enterprise_spaces(id)`` is
NOT NULL but the ``enterprise_spaces`` table is intentionally empty in
the single-tenant demo (拿不准点 #1). We mirror the decisions service's
``PRAGMA foreign_keys = OFF`` pattern inside the write transaction so
inserts work today; the pragma is restored in ``finally`` so other code
paths keep strict FK checks.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any, Final
from uuid import uuid4

from .. import db
from ..outbox.events import OutboxEventDraft, insert_event

log = logging.getLogger(__name__)


#: Default ``enterprise_id`` placeholder (拿不准点 #1). Mirrors
#: ``decisions.service.DEFAULT_ENTERPRISE_ID`` so cross-domain joins
#: (e.g. a future "all decisions + their tasks" report) line up.
DEFAULT_ENTERPRISE_ID: Final[str] = "huilton_seed"

#: Allowed transitions for ``business_tasks.status``. Read once at import.
#: Terminal states (``done`` / ``cancelled``) intentionally map to an
#: empty frozenset so the state-machine check below is uniform.
_STATUS_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "todo": frozenset({"in_progress", "done", "cancelled"}),
    "in_progress": frozenset({"done", "cancelled"}),
    "done": frozenset(),
    "cancelled": frozenset(),
}

#: Valid status values for new rows + filter parameter.
_VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {"todo", "in_progress", "done", "cancelled"}
)


class BusinessTaskNotFoundError(LookupError):
    """Raised when a task id query yields no row."""


class BusinessTaskStateError(RuntimeError):
    """Raised when a PATCH violates the status state machine (HTTP 409)."""


class BusinessTaskValidationError(ValueError):
    """Raised when an incoming body is structurally invalid (HTTP 422)."""


# ---------------------------------------------------------------------------
# DB read / write helpers (sync — called inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into a JSON-safe dict (no JSON columns here)."""
    return dict(row)


def _list_sync(
    enterprise_id: str,
    status: str | None,
    assignee_id: str | None,
    decision_id: str | None,
) -> list[dict[str, Any]]:
    """List business tasks filtered by optional ``status`` / ``assignee_id`` / ``decision_id``."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        sql = (
            "SELECT id, enterprise_id, decision_id, title, description, assignee_id, "
            "status, runtime_task_id, session_key, run_id, created_at "
            "FROM business_tasks WHERE enterprise_id = ?"
        )
        params: list[Any] = [enterprise_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if assignee_id is not None:
            sql += " AND assignee_id = ?"
            params.append(assignee_id)
        if decision_id is not None:
            sql += " AND decision_id = ?"
            params.append(decision_id)
        sql += " ORDER BY created_at DESC, id DESC"
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def _get_sync(task_id: str) -> dict[str, Any]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, enterprise_id, decision_id, title, description, assignee_id, "
            "status, runtime_task_id, session_key, run_id, created_at "
            "FROM business_tasks WHERE id = ?",
            (task_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise BusinessTaskNotFoundError(task_id)
    return _row_to_dict(row)


def _insert_sync(
    *,
    enterprise_id: str,
    decision_id: str | None,
    title: str,
    description: str | None,
    assignee_id: str | None,
) -> dict[str, Any]:
    """Insert a new business task row. Status defaults to ``todo``."""
    conn = db.connect()
    try:
        # Mirror decisions/service.py: relax FK only inside this connection's
        # lifetime so the forward-reference to ``enterprise_spaces(id)``
        # doesn't reject the placeholder "huilton_seed" enterprise id.
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        new_id = f"bt_{uuid4().hex[:12]}"
        try:
            cur.execute(
                "INSERT INTO business_tasks ("
                "  id, enterprise_id, decision_id, title, description,"
                "  assignee_id, status"
                ") VALUES (?, ?, ?, ?, ?, ?, 'todo')",
                (
                    new_id,
                    enterprise_id,
                    decision_id,
                    title,
                    description,
                    assignee_id,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise BusinessTaskValidationError(
                f"invalid FK or constraint: {exc}"
            ) from exc
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()
    return _get_sync(new_id)


def _patch_sync(
    task_id: str,
    *,
    status: str | None,
    assignee_id: str | None,
    description: str | None,
) -> dict[str, Any]:
    """Apply a status transition + optional assignee / description update.

    Status transitions are gated by ``_STATUS_TRANSITIONS``; terminal rows
    may still receive ``description`` / ``assignee_id`` updates so operators
    can annotate a closed task without reopening it.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM business_tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if row is None:
            raise BusinessTaskNotFoundError(task_id)
        current_status = row["status"]
        next_status = status or current_status
        if next_status != current_status:
            allowed = _STATUS_TRANSITIONS.get(current_status, frozenset())
            if next_status not in allowed:
                raise BusinessTaskStateError(
                    f"illegal status transition {current_status!r} -> {next_status!r}; "
                    f"allowed: {sorted(allowed) or 'none (terminal)'}"
                )

        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if assignee_id is not None:
            updates.append("assignee_id = ?")
            params.append(assignee_id)
        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if not updates:
            raise BusinessTaskValidationError(
                "PATCH body must include at least one of: status, assignee_id, description"
            )

        params.append(task_id)
        cur.execute(
            f"UPDATE business_tasks SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()
    return _get_sync(task_id)


def _delete_sync(task_id: str) -> None:
    """Physical delete by id; raises if no row matched."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM business_tasks WHERE id = ?", (task_id,))
        if cur.rowcount == 0:
            raise BusinessTaskNotFoundError(task_id)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public coroutines (routes call these)
# ---------------------------------------------------------------------------


async def list_tasks(
    enterprise_id: str | None = None,
    *,
    status: str | None = None,
    assignee_id: str | None = None,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """List business tasks with optional filters.

    Returns ``{"items": [...], "total": int}``. ``total`` mirrors the array
    length because the v1 task queue is not paginated (demo-scale bounded).

    Raises :class:`BusinessTaskValidationError` (HTTP 422) when ``status``
    is provided but not one of the four valid task statuses.
    """
    eid = enterprise_id or DEFAULT_ENTERPRISE_ID
    if status is not None and status not in _VALID_STATUSES:
        raise BusinessTaskValidationError(
            f"invalid status filter: {status!r}; "
            f"expected one of {sorted(_VALID_STATUSES)}"
        )
    items = await asyncio.to_thread(
        _list_sync, eid, status, assignee_id, decision_id
    )
    return {"items": items, "total": len(items)}


async def get_task(task_id: str) -> dict[str, Any]:
    """Fetch a single business task by id. Raises :class:`BusinessTaskNotFoundError`."""
    return await asyncio.to_thread(_get_sync, task_id)


async def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a new business task and return the row.

    ``payload`` keys:

    * ``enterprise_id`` (str) — optional; defaults to :data:`DEFAULT_ENTERPRISE_ID`.
    * ``title`` (str) — **required**, non-empty.
    * ``description`` (str) — optional.
    * ``decision_id`` (str) — optional; soft reference to ``decision_items.id``.
      Not FK-validated (the decisions service owns that table); a dangling
      reference is a UI concern, not a 422.
    * ``assignee_id`` (str) — optional; free-form identifier.

    Raises :class:`BusinessTaskValidationError` when required fields are
    missing or contain invalid types.
    """
    if not isinstance(payload, dict):
        raise BusinessTaskValidationError("request body must be a JSON object")

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise BusinessTaskValidationError(
            "title is required and must be a non-empty string"
        )

    eid_raw = payload.get("enterprise_id")
    eid = str(eid_raw or "").strip() or DEFAULT_ENTERPRISE_ID

    description_raw = payload.get("description")
    description: str | None
    if description_raw is None:
        description = None
    elif isinstance(description_raw, str):
        description = description_raw
    else:
        raise BusinessTaskValidationError("description, when provided, must be a string")

    decision_id_raw = payload.get("decision_id")
    decision_id: str | None
    if decision_id_raw is None:
        decision_id = None
    elif isinstance(decision_id_raw, str) and decision_id_raw.strip():
        decision_id = decision_id_raw.strip()
    else:
        raise BusinessTaskValidationError(
            "decision_id, when provided, must be a non-empty string"
        )

    assignee_id_raw = payload.get("assignee_id")
    assignee_id: str | None
    if assignee_id_raw is None:
        assignee_id = None
    elif isinstance(assignee_id_raw, str) and assignee_id_raw.strip():
        assignee_id = assignee_id_raw.strip()
    else:
        raise BusinessTaskValidationError(
            "assignee_id, when provided, must be a non-empty string"
        )

    return await asyncio.to_thread(
        _insert_sync,
        enterprise_id=eid,
        decision_id=decision_id,
        title=title.strip(),
        description=description,
        assignee_id=assignee_id,
    )


async def create_task_with_notify(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap :func:`create_task` to enqueue a ``task.assigned`` event.

    Phase ❸-1 hook: 创建任务后立刻给飞书群发一条通知,让看板 / 群
    消息保持同步。错误时抛出同原始 ``create_task`` 一样的异常。
    """
    row = await create_task(payload)
    assignee_id = str(row.get("assignee_id") or "") or ""
    await insert_event(
        OutboxEventDraft(
            event_type="task.assigned",
            aggregate_type="task",
            aggregate_id=str(row.get("id") or ""),
            payload={
                "task_title": str(row.get("title") or ""),
                "assignee_id": assignee_id,
                "status": str(row.get("status") or "todo"),
            },
        )
    )
    return row


async def patch_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update (status transition + optional assignee / description).

    At least one of ``status``, ``assignee_id``, ``description`` must be present.
    Status transitions are gated by the state machine; assignee / description
    are free-form edits on any row (including terminal rows).

    Raises:
      * :class:`BusinessTaskNotFoundError` — unknown id.
      * :class:`BusinessTaskValidationError` — invalid body, unknown status,
        or empty body.
      * :class:`BusinessTaskStateError` — illegal status transition.
    """
    if not isinstance(payload, dict):
        raise BusinessTaskValidationError("request body must be a JSON object")

    status_raw = payload.get("status")
    status: str | None
    if status_raw is None:
        status = None
    elif isinstance(status_raw, str) and status_raw in _VALID_STATUSES:
        status = status_raw
    else:
        raise BusinessTaskValidationError(
            f"status, when provided, must be one of {sorted(_VALID_STATUSES)}"
        )

    assignee_id_raw = payload.get("assignee_id")
    assignee_id: str | None
    if assignee_id_raw is None:
        assignee_id = None
    elif isinstance(assignee_id_raw, str):
        assignee_id = assignee_id_raw
    else:
        raise BusinessTaskValidationError("assignee_id, when provided, must be a string")

    description_raw = payload.get("description")
    description: str | None
    if description_raw is None:
        description = None
    elif isinstance(description_raw, str):
        description = description_raw
    else:
        raise BusinessTaskValidationError("description, when provided, must be a string")

    return await asyncio.to_thread(
        _patch_sync,
        task_id,
        status=status,
        assignee_id=assignee_id,
        description=description,
    )


async def patch_task_with_notify(
    task_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Wrap :func:`patch_task` to enqueue a ``task.completed`` / ``task.cancelled`` event.

    Phase ❸-1 hook: 状态迁移到 ``done`` / ``cancelled`` 才入队,中间状态
    ``in_progress`` 不入队 (噪声会淹没真正的事件)。
    """
    prior = await get_task(task_id)
    prior_status = str(prior.get("status") or "")
    row = await patch_task(task_id, payload)
    next_status = str(row.get("status") or "")
    event_type: str | None = None
    if next_status != prior_status:
        if next_status == "done":
            event_type = "task.completed"
        elif next_status == "cancelled":
            event_type = "task.cancelled"
    if event_type is not None:
        await insert_event(
            OutboxEventDraft(
                event_type=event_type,
                aggregate_type="task",
                aggregate_id=task_id,
                payload={
                    "task_title": str(row.get("title") or ""),
                    "assignee_id": str(row.get("assignee_id") or "") or "",
                    "status": next_status,
                },
            )
        )
    return row


async def delete_task(task_id: str) -> None:
    """Physical delete the row (spec "软删或物理删 — 大总管拍" 走物理删).

    Raises :class:`BusinessTaskNotFoundError` when no row matches.
    """
    await asyncio.to_thread(_delete_sync, task_id)


__all__ = [
    "DEFAULT_ENTERPRISE_ID",
    "BusinessTaskNotFoundError",
    "BusinessTaskStateError",
    "BusinessTaskValidationError",
    "list_tasks",
    "get_task",
    "create_task",
    "create_task_with_notify",
    "patch_task",
    "patch_task_with_notify",
    "delete_task",
]
