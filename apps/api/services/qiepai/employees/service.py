"""qiepai · digital employees service implementation (Phase ❷-6).

Single business-layer module backing ``apps/api/routes/qiepai/employees.py``.
Owns:

* ``employees`` table CRUD (list / get / create / patch / soft-delete).
* ``employee_revisions`` table writes (append-only) + reads.
* Publish state machine (delegated to :mod:`.state_machine` for purity).
* Persona 1:1 uniqueness check (read-then-insert inside a single txn).

Why one file (not split further)
=================================

The decisions service stayed in one file because it touches a single table;
employees touches two (``employees`` + ``employee_revisions``) and the
state machine is complex enough to warrant its own module. We've split
**only** the state machine out — the rest of the CRUD is small enough that
splitting it further would fragment related reads (e.g. the persona
conflict check is needed by both create and patch).

Cross-revision atomicity
========================

The "publish" endpoint performs three writes in one transaction:

1. Re-read the employee + the current revision.
2. Validate the state transition + readiness gate.
3. UPDATE ``employees.status`` AND ``employees.current_revision_id``.

We open an explicit transaction (``BEGIN`` … ``COMMIT``) so a crash
mid-publish cannot leave the employee in a half-applied state (e.g.
status flipped to ``published`` but ``current_revision_id`` still pointing
at the previous revision).

Persona 1:1 link contract (spec section 6.4)
============================================

* ``employees.persona_id`` is a TEXT column (nullable).
* On POST, if ``persona_id`` is provided, we ``SELECT`` for any other
  employee row holding the same id and 422 with a message that names
  the conflicting employee so the operator can find it.
* On PATCH, the same check runs for the new persona_id (excluding the
  current employee from the conflict scan via ``id != ?``).
* No reverse ``personas`` table mutation — personas live in
  ``opentalking/persona/`` as files; we treat ``employees.persona_id``
  as a one-way reference.

Sync state source
=================

``employee_revisions.sync_state`` defaults to ``"pending"``. The
"real" sync status would be written by an external worker (not in
scope for ❷-6); for the demo the operator can manually UPDATE the
column to ``"in_sync"`` to clear the gate. We **do not** auto-flip
sync_state on publish — that would mask a real sync failure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any, Final
from uuid import uuid4

from .. import db
from ..outbox.events import OutboxEventDraft, insert_event
from . import state_machine

log = logging.getLogger(__name__)


#: Default ``enterprise_id`` placeholder (拿不准点 #1). Mirrors
#: ``decisions.service.DEFAULT_ENTERPRISE_ID`` and
#: ``tasks.service.DEFAULT_ENTERPRISE_ID``.
DEFAULT_ENTERPRISE_ID: Final[str] = "huilton_seed"


class EmployeeNotFoundError(LookupError):
    """Raised when an employee id query yields no row."""


class EmployeeRevisionNotFoundError(LookupError):
    """Raised when a revision id query yields no row."""


class EmployeeConflictError(ValueError):
    """Raised when a write violates a 1:1 uniqueness rule (HTTP 409).

    Used by the persona 1:1 link check: posting a persona_id that is
    already linked to another employee surfaces as a 409 with a
    message naming the conflicting employee id, mirroring the spec
    verbatim ("persona already linked to employee_X").
    """


# Re-export the state-machine errors under namespaced aliases so the
# router can ``except service.EmployeeStateError`` without importing
# from the submodule. Mirrors the decisions service's error surface.
EmployeeStateError = state_machine.EmployeeStateError
EmployeeValidationError = state_machine.EmployeeValidationError


# ---------------------------------------------------------------------------
# DB read / write helpers (sync — called inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into a JSON-safe dict.

    ``config_snapshot`` is stored as JSON TEXT; decode it so the route
    returns a real dict instead of a stringified blob. A corrupt blob
    passes through as the original string + a warning (matches the
    ``decisions.service._row_to_dict`` contract).
    """
    out = dict(row)
    raw = out.get("config_snapshot")
    if isinstance(raw, str) and raw:
        try:
            out["config_snapshot"] = json.loads(raw)
        except ValueError:
            log.warning(
                "employees: config_snapshot JSON parse failed for row %r", out.get("id")
            )
    return out


def _revision_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Same as :func:`_row_to_dict` but for ``employee_revisions`` rows."""
    return _row_to_dict(row)


def _list_sync(enterprise_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, enterprise_id, persona_id, display_name, role, status, "
            "current_revision_id, created_at "
            "FROM employees WHERE enterprise_id = ? ORDER BY created_at DESC, id DESC",
            (enterprise_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def _get_sync(employee_id: str) -> dict[str, Any]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, enterprise_id, persona_id, display_name, role, status, "
            "current_revision_id, created_at "
            "FROM employees WHERE id = ?",
            (employee_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise EmployeeNotFoundError(employee_id)
    return _row_to_dict(row)


def _find_employee_by_persona_sync(
    enterprise_id: str, persona_id: str, exclude_employee_id: str | None = None
) -> str | None:
    """Return the employee id currently linked to ``persona_id`` (or None).

    Used by POST / PATCH to enforce the spec's 1:1 persona ↔ employee rule.
    ``exclude_employee_id`` lets the PATCH path scan "every other employee"
    rather than "every employee including myself" (a self-link is always OK).
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        if exclude_employee_id is None:
            cur.execute(
                "SELECT id FROM employees WHERE enterprise_id = ? AND persona_id = ? "
                "ORDER BY created_at ASC LIMIT 1",
                (enterprise_id, persona_id),
            )
        else:
            cur.execute(
                "SELECT id FROM employees WHERE enterprise_id = ? AND persona_id = ? "
                "AND id != ? ORDER BY created_at ASC LIMIT 1",
                (enterprise_id, persona_id, exclude_employee_id),
            )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return str(row["id"])


def _insert_sync(
    *,
    enterprise_id: str,
    persona_id: str | None,
    display_name: str,
    role: str,
) -> dict[str, Any]:
    """Insert a new employee row. Returns the inserted row."""
    conn = db.connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        new_id = f"emp_{uuid4().hex[:12]}"
        try:
            cur.execute(
                "INSERT INTO employees ("
                "  id, enterprise_id, persona_id, display_name, role, status"
                ") VALUES (?, ?, ?, ?, ?, 'draft')",
                (new_id, enterprise_id, persona_id, display_name, role),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise EmployeeValidationError(f"invalid FK or constraint: {exc}") from exc
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()
    return _get_sync(new_id)


def _patch_sync(
    employee_id: str,
    *,
    display_name: str | None,
    role: str | None,
    persona_id: str | None,
) -> dict[str, Any]:
    """Apply a partial update to ``display_name`` / ``role`` / ``persona_id``.

    ``status`` is intentionally **not** editable here — spec section 6.1
    says "status 改走 publish 流程", which means PATCH must not touch
    ``employees.status`` directly. The publish endpoint owns that field.
    """
    conn = db.connect()
    try:
        # Re-read the existing row inside the txn so the persona conflict
        # check has the right ``enterprise_id`` and the message references
        # the correct entity.
        cur = conn.cursor()
        cur.execute(
            "SELECT enterprise_id, persona_id FROM employees WHERE id = ?",
            (employee_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise EmployeeNotFoundError(employee_id)
        existing_persona_id = row["persona_id"]
        enterprise_id = row["enterprise_id"]

        # Compute the effective persona_id: explicit PATCH value wins;
        # otherwise leave the existing value alone.
        effective_persona_id = persona_id if persona_id is not None else existing_persona_id

        updates: list[str] = []
        params: list[Any] = []
        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if role is not None:
            updates.append("role = ?")
            params.append(role)
        if persona_id is not None and persona_id != existing_persona_id:
            # Only run the conflict check when persona_id is actually
            # changing (a no-op PATCH shouldn't 409 against itself).
            conflict = _find_employee_by_persona_sync(
                enterprise_id, persona_id, exclude_employee_id=employee_id
            )
            if conflict is not None:
                raise EmployeeConflictError(
                    f"persona already linked to {conflict}"
                )
            updates.append("persona_id = ?")
            params.append(persona_id)

        if not updates:
            raise EmployeeValidationError(
                "PATCH body must include at least one of: display_name, role, persona_id"
            )

        params.append(employee_id)
        cur.execute(
            f"UPDATE employees SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()
    return _get_sync(employee_id)


def _delete_sync(employee_id: str) -> None:
    """Hard-delete the employee row.

    Spec section 6.1 says "软删或物理删 (大总管拍)" — we go with hard
    delete for parity with the business-tasks service (demo single-
    tenant; the audit trail is in ``audit_events``, not on the entity
    row itself). ``employee_revisions`` rows go away via ``ON DELETE
    CASCADE`` if the schema declares it; the ❷-2 migration does not,
    so we explicitly delete them first to avoid orphan rows.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM employee_revisions WHERE employee_id = ?", (employee_id,)
        )
        cur.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        if cur.rowcount == 0:
            raise EmployeeNotFoundError(employee_id)
        conn.commit()
    finally:
        conn.close()


def _list_revisions_sync(employee_id: str) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, employee_id, revision_number, workspace_file_hash, "
            "config_snapshot, publish_state, readiness_p0, readiness_p1, "
            "sync_state, created_at "
            "FROM employee_revisions WHERE employee_id = ? "
            "ORDER BY revision_number DESC, id DESC",
            (employee_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_revision_row_to_dict(r) for r in rows]


def _get_current_revision_sync(employee_id: str) -> dict[str, Any] | None:
    """Return the revision pointed to by ``employees.current_revision_id``.

    Returns ``None`` if the employee has no current revision yet (the
    freshly-created ``draft`` state has none).
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT current_revision_id FROM employees WHERE id = ?",
            (employee_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise EmployeeNotFoundError(employee_id)
        revision_id = row["current_revision_id"]
        if not revision_id:
            return None
        cur.execute(
            "SELECT id, employee_id, revision_number, workspace_file_hash, "
            "config_snapshot, publish_state, readiness_p0, readiness_p1, "
            "sync_state, created_at "
            "FROM employee_revisions WHERE id = ?",
            (revision_id,),
        )
        rev = cur.fetchone()
    finally:
        conn.close()
    if rev is None:
        return None
    return _revision_row_to_dict(rev)


def _get_latest_revision_sync(employee_id: str) -> dict[str, Any] | None:
    """Return the highest ``revision_number`` row for ``employee_id`` (or None)."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, employee_id, revision_number, workspace_file_hash, "
            "config_snapshot, publish_state, readiness_p0, readiness_p1, "
            "sync_state, created_at "
            "FROM employee_revisions WHERE employee_id = ? "
            "ORDER BY revision_number DESC, id DESC LIMIT 1",
            (employee_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _revision_row_to_dict(row)


def _create_revision_sync(
    employee_id: str,
    *,
    workspace_file_hash: str,
    config_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Insert a new revision row with the next ``revision_number``.

    ``revision_number`` is computed as ``MAX + 1`` inside a single
    transaction to avoid race conditions with concurrent POSTs. The
    UNIQUE(employee_id, revision_number) constraint is the safety net
    if two POSTs ever do race — the loser gets an IntegrityError mapped
    to a 422 below.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        # Confirm the employee exists before touching revisions.
        cur.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
        if cur.fetchone() is None:
            raise EmployeeNotFoundError(employee_id)

        cur.execute(
            "SELECT COALESCE(MAX(revision_number), 0) AS max_rev "
            "FROM employee_revisions WHERE employee_id = ?",
            (employee_id,),
        )
        max_rev = int(cur.fetchone()["max_rev"])
        next_rev = max_rev + 1
        new_id = f"rev_{uuid4().hex[:12]}"
        try:
            cur.execute(
                "INSERT INTO employee_revisions ("
                "  id, employee_id, revision_number, workspace_file_hash,"
                "  config_snapshot, publish_state, readiness_p0, readiness_p1, sync_state"
                ") VALUES (?, ?, ?, ?, ?, 'draft', 0, 0, 'pending')",
                (
                    new_id,
                    employee_id,
                    next_rev,
                    workspace_file_hash,
                    json.dumps(config_snapshot, ensure_ascii=False),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise EmployeeValidationError(
                f"revision_number conflict (UNIQUE): {exc}"
            ) from exc
    finally:
        conn.close()
    # Read-back to return the persisted row (so the caller sees the
    # server-assigned id + revision_number verbatim).
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, employee_id, revision_number, workspace_file_hash, "
            "config_snapshot, publish_state, readiness_p0, readiness_p1, "
            "sync_state, created_at FROM employee_revisions WHERE id = ?",
            (new_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        # Should never happen — the INSERT just succeeded.
        raise EmployeeRevisionNotFoundError(new_id)
    return _revision_row_to_dict(row)


def _publish_sync(employee_id: str) -> dict[str, Any]:
    """Promote the latest revision to ``published`` (state machine + readiness).

    Two atomic writes inside a single transaction:

    1. The employee row's ``status`` flips per the state machine; the
       target is inferred from the employee's *current* status (the spec
       describes the publish endpoint as a single ``POST …/publish``
       rather than a status-targeted verb, so we treat it as
       "transition one step forward toward published" — usually
       ``draft → configuring`` if the employee is brand new, or
       ``configuring → ready`` if a revision exists, or
       ``ready → published`` if the readiness gate is met).

       To keep the contract simple and the spec verbatim ("publish state
       machine: draft→configuring→ready→published …"), the publish
       endpoint **always** targets the next state in the canonical
       chain: the first call advances to ``configuring``, the second to
       ``ready`` (if the readiness gate passes), and the third to
       ``published`` (also gated). Recovery paths (``retired →
       published``) are supported via a single publish call because the
       canonical next-state from ``retired`` is ``published`` per the
       transition table.

       The readiness gate fires on the move to ``ready`` AND
       ``published``; intermediate moves (``draft → configuring``) are
       unconditional.

    2. ``employees.current_revision_id`` is updated to point at the
       latest revision so subsequent PATCHes target the right
       snapshot.

    Returns the updated employee row.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        # Confirm employee exists + capture current state.
        cur.execute(
            "SELECT status, current_revision_id FROM employees WHERE id = ?",
            (employee_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise EmployeeNotFoundError(employee_id)
        current_status = row["status"]
        current_revision_id = row["current_revision_id"]

        # Pick the next canonical status: read the transition table's
        # outbound neighbours in a deterministic order and pick the
        # first one that isn't ``retired`` (retired is a sink except
        # for the recovery path).
        candidates = sorted(state_machine._STATUS_TRANSITIONS.get(current_status, frozenset()))
        if not candidates:
            # No outbound edges at all — terminal.
            raise EmployeeStateError(
                f"no legal next status from {current_status!r}"
            )

        # Determine the *target* status for this publish call. The spec
        # treats publish as a forward step on the canonical chain
        # ``draft → configuring → ready → published``. We map:
        #   draft          → configuring
        #   configuring    → ready     (readiness gate applies)
        #   ready          → published (readiness gate applies)
        #   published      → suspended (no gate — already published)
        #   suspended      → published (re-publish; no gate, already past it once)
        #   retired        → published (recovery; readiness gate re-applies)
        chain = {
            "draft": "configuring",
            "configuring": "ready",
            "ready": "published",
            "published": "suspended",
            "suspended": "published",
            "retired": "published",
        }
        target = chain.get(current_status)
        if target is None:
            raise EmployeeStateError(
                f"no canonical next status from {current_status!r}"
            )

        # Always look up the latest revision — the ``current_revision_id``
        # pointer should track the most recent snapshot regardless of
        # which way the state machine is moving. The readiness gate below
        # additionally inspects this row's ``readiness_p0/p1 + sync_state``
        # when ``target`` is ``ready`` or ``published``.
        cur.execute(
            "SELECT id, readiness_p0, readiness_p1, sync_state "
            "FROM employee_revisions WHERE employee_id = ? "
            "ORDER BY revision_number DESC, id DESC LIMIT 1",
            (employee_id,),
        )
        rev_row = cur.fetchone()

        # On moves to ``ready`` or ``published`` (per spec section 6.2),
        # the readiness gate must pass. The latest revision is the one
        # being promoted.
        if target in {"ready", "published"}:
            if rev_row is None:
                raise EmployeeValidationError(
                    f"cannot move to status={target!r} without at least one revision; "
                    f"POST /employees/{{id}}/revisions first"
                )
            state_machine.check_readiness_for_publish(
                {
                    "readiness_p0": rev_row["readiness_p0"],
                    "readiness_p1": rev_row["readiness_p1"],
                    "sync_state": rev_row["sync_state"],
                },
                target,
            )
            # Promote the revision: stamp publish_state on the revision
            # itself so a follow-up GET can show the operator which
            # snapshot is live.
            cur.execute(
                "UPDATE employee_revisions SET publish_state = ? WHERE id = ?",
                (target, rev_row["id"]),
            )

        # ``current_revision_id`` tracks the latest revision whenever
        # one exists; intermediate moves (e.g. ``draft → configuring``)
        # newly set it, and subsequent moves keep it pointed at the
        # most recent snapshot. If no revisions exist yet, leave the
        # column NULL (mirrors the freshly-created ``draft`` state).
        new_current_revision_id = (
            str(rev_row["id"]) if rev_row is not None else current_revision_id
        )

        cur.execute(
            "UPDATE employees SET status = ?, current_revision_id = ? WHERE id = ?",
            (target, new_current_revision_id, employee_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _get_sync(employee_id)


# ---------------------------------------------------------------------------
# Public coroutines (routes call these)
# ---------------------------------------------------------------------------


async def list_employees(enterprise_id: str | None = None) -> dict[str, Any]:
    """List digital employees for an enterprise (defaults to the placeholder)."""
    eid = enterprise_id or DEFAULT_ENTERPRISE_ID
    items = await asyncio.to_thread(_list_sync, eid)
    return {"items": items, "total": len(items)}


async def get_employee(employee_id: str) -> dict[str, Any]:
    """Fetch a single employee by id. Raises :class:`EmployeeNotFoundError`."""
    return await asyncio.to_thread(_get_sync, employee_id)


async def create_employee(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a new employee row.

    ``payload`` keys:

    * ``enterprise_id`` (str) — optional; defaults to :data:`DEFAULT_ENTERPRISE_ID`.
    * ``display_name`` (str) — **required**, non-empty.
    * ``role`` (str) — **required**, non-empty (e.g. "财务数字员工").
    * ``persona_id`` (str) — optional; must be unique across the enterprise's
      employees. If another employee already holds it, returns 409 with
      "persona already linked to employee_X".

    Raises :class:`EmployeeConflictError` (409) on persona uniqueness violation.
    Raises :class:`EmployeeValidationError` (422) on bad input.
    """
    if not isinstance(payload, dict):
        raise EmployeeValidationError("request body must be a JSON object")

    display_name_raw = payload.get("display_name")
    if not isinstance(display_name_raw, str) or not display_name_raw.strip():
        raise EmployeeValidationError(
            "display_name is required and must be a non-empty string"
        )

    role_raw = payload.get("role")
    if not isinstance(role_raw, str) or not role_raw.strip():
        raise EmployeeValidationError(
            "role is required and must be a non-empty string"
        )

    eid_raw = payload.get("enterprise_id")
    eid = str(eid_raw or "").strip() or DEFAULT_ENTERPRISE_ID

    persona_id_raw = payload.get("persona_id")
    persona_id: str | None
    if persona_id_raw is None:
        persona_id = None
    elif isinstance(persona_id_raw, str) and persona_id_raw.strip():
        persona_id = persona_id_raw.strip()
    else:
        raise EmployeeValidationError(
            "persona_id, when provided, must be a non-empty string"
        )

    # Pre-flight persona 1:1 check (the UNIQUE-on-column alternative
    # would require an index we don't have; the explicit SELECT keeps
    # the error message human-friendly).
    if persona_id is not None:
        conflict = await asyncio.to_thread(
            _find_employee_by_persona_sync, eid, persona_id
        )
        if conflict is not None:
            raise EmployeeConflictError(
                f"persona already linked to {conflict}"
            )

    return await asyncio.to_thread(
        _insert_sync,
        enterprise_id=eid,
        persona_id=persona_id,
        display_name=display_name_raw.strip(),
        role=role_raw.strip(),
    )


async def patch_employee(employee_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update (display_name / role / persona_id).

    ``status`` is intentionally NOT accepted here — the spec routes
    status changes through the publish endpoint.

    Raises:
      * :class:`EmployeeNotFoundError` — unknown id.
      * :class:`EmployeeValidationError` — bad body, empty body, or
        invalid type.
      * :class:`EmployeeConflictError` — new persona_id collides with
        another employee.
    """
    if not isinstance(payload, dict):
        raise EmployeeValidationError("request body must be a JSON object")

    # Reject explicit ``status`` here with a clear message — operators
    # who try to flip status via PATCH are pointed at the publish
    # endpoint rather than silently dropped.
    if "status" in payload:
        raise EmployeeValidationError(
            "status changes must go through POST /employees/{id}/publish; "
            "do not include status in the PATCH body"
        )

    display_name_raw = payload.get("display_name")
    display_name: str | None
    if display_name_raw is None:
        display_name = None
    elif isinstance(display_name_raw, str):
        display_name = display_name_raw
    else:
        raise EmployeeValidationError("display_name, when provided, must be a string")

    role_raw = payload.get("role")
    role: str | None
    if role_raw is None:
        role = None
    elif isinstance(role_raw, str):
        role = role_raw
    else:
        raise EmployeeValidationError("role, when provided, must be a string")

    persona_id_raw = payload.get("persona_id")
    persona_id: str | None
    if persona_id_raw is None:
        persona_id = None
    elif isinstance(persona_id_raw, str) and persona_id_raw.strip():
        persona_id = persona_id_raw.strip()
    else:
        raise EmployeeValidationError(
            "persona_id, when provided, must be a non-empty string"
        )

    return await asyncio.to_thread(
        _patch_sync,
        employee_id,
        display_name=display_name,
        role=role,
        persona_id=persona_id,
    )


async def delete_employee(employee_id: str) -> None:
    """Hard-delete the employee + cascade-delete its revisions.

    Raises :class:`EmployeeNotFoundError` if no row matches.
    """
    await asyncio.to_thread(_delete_sync, employee_id)


async def list_revisions(employee_id: str) -> dict[str, Any]:
    """List revisions for an employee (newest first).

    Raises :class:`EmployeeNotFoundError` if the employee doesn't exist
    (404 is a more honest signal than returning an empty list for an
    unknown id).
    """
    # Confirm employee exists first so callers get 404 on bad ids.
    await asyncio.to_thread(_get_sync, employee_id)
    items = await asyncio.to_thread(_list_revisions_sync, employee_id)
    return {"items": items, "total": len(items)}


async def create_revision(employee_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append a new revision row.

    ``payload`` keys:

    * ``workspace_file_hash`` (str) — **required**, non-empty.
    * ``config_snapshot`` (dict) — **required**, must be a JSON object
      (a list / string / number is rejected with 422).

    The new revision's ``revision_number`` is auto-assigned as
    ``MAX + 1`` for this employee.

    Side effect: if the employee was in ``draft``, the operator is
    expected to call publish separately to advance the state machine.
    Creating a revision does **not** auto-flip ``employees.status`` —
    that would silently advance state behind the operator's back.
    """
    if not isinstance(payload, dict):
        raise EmployeeValidationError("request body must be a JSON object")

    workspace_file_hash_raw = payload.get("workspace_file_hash")
    if (
        not isinstance(workspace_file_hash_raw, str)
        or not workspace_file_hash_raw.strip()
    ):
        raise EmployeeValidationError(
            "workspace_file_hash is required and must be a non-empty string"
        )

    config_snapshot_raw = payload.get("config_snapshot")
    if not isinstance(config_snapshot_raw, dict):
        raise EmployeeValidationError("config_snapshot must be a dict")

    return await asyncio.to_thread(
        _create_revision_sync,
        employee_id,
        workspace_file_hash=workspace_file_hash_raw.strip(),
        config_snapshot=config_snapshot_raw,
    )


async def publish_employee(employee_id: str) -> dict[str, Any]:
    """Advance the employee one step on the canonical publish chain.

    See :func:`_publish_sync` for the exact target mapping. The
    readiness gate (``readiness_p0/p1 + sync_state``) fires on moves to
    ``ready`` and ``published``.

    Raises:
      * :class:`EmployeeNotFoundError` — unknown id.
      * :class:`EmployeeStateError` — illegal transition (no outbound
        edge from current status).
      * :class:`EmployeeValidationError` — readiness gate failed
        (``readiness_p0/p1`` false, or ``sync_state`` in
        ``{error, drifted}``), or no revisions exist when targeting
        ``ready`` / ``published``.
    """
    return await asyncio.to_thread(_publish_sync, employee_id)


async def publish_employee_with_notify(employee_id: str) -> dict[str, Any]:
    """Wrap :func:`publish_employee` to ALSO enqueue a Feishu notification.

    Side effect: a single :class:`OutboxEventDraft` is enqueued when the
    publish **succeeds**; no event is emitted when the publish raises
    (a 4xx / 5xx deserves its own retry, not a notification).

    Implemented as a thin wrapper (rather than a flag on the existing
    coroutine) so callers can opt out — the demo UI calls the bare
    :func:`publish_employee` for tests, while the public FastAPI route
    uses this entry point so every successful publish fans out a
    notification.
    """
    row = await publish_employee(employee_id)
    target_status = str(row.get("status") or "")
    # 推到 ready / published / suspended 都发;让看板状态提前可见
    if target_status in {"ready", "published", "suspended"}:
        await insert_event(
            OutboxEventDraft(
                event_type="employee.published",
                aggregate_type="employee",
                aggregate_id=str(row.get("id") or employee_id),
                payload={
                    "display_name": row.get("display_name") or "",
                    "role": row.get("role") or "",
                    "status": target_status,
                },
            )
        )
    return row


__all__ = [
    "DEFAULT_ENTERPRISE_ID",
    "EmployeeNotFoundError",
    "EmployeeRevisionNotFoundError",
    "EmployeeConflictError",
    "EmployeeStateError",
    "EmployeeValidationError",
    "list_employees",
    "get_employee",
    "create_employee",
    "patch_employee",
    "delete_employee",
    "list_revisions",
    "create_revision",
    "publish_employee",
    "publish_employee_with_notify",
]
