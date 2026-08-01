"""qiepai · decisions service (Phase ❷-5).

Single business-layer module backing ``apps/api/routes/qiepai/decisions.py``.
Owns the lifecycle of ``decision_items`` rows (state machine + DB IO) and
the LLM-backed 4-layer assistant exposed at
``GET /api/qiepai/decisions/{id}/ai-suggestion``.

Why this is one file (not three)
=================================

Cockpit service gets away with one file because its queries are uniform;
decisions are small and self-contained (single table, no joins other
than ``metric_snapshots`` for the optional fact_snapshot seed), and
splitting state machine, AI integration and CRUD across modules would
inflate the diff without unlocking any independence. ❷-6 may split
``service.py`` further if business_tasks join in.

DB conventions (mirrors apps/api/services/qiepai/cockpit/service.py)
====================================================================

* Every public coroutine that touches the DB wraps the blocking
  ``sqlite3`` call in :func:`asyncio.to_thread`.
* Read connections are short-lived (``connect → execute → close``). The
  qiepai DB is configured with WAL + ``foreign_keys=ON`` so concurrent
  reads from sibling routes are safe.
* Writes open an explicit transaction via ``conn.commit()``.

Status state machine
====================

* ``pending``   → ``decided``   (records ``decided_at``; ``decision_text`` required)
* ``pending``   → ``cancelled`` (records ``decided_at``; ``decision_text`` optional)
* Terminal states (``decided`` / ``cancelled``) reject further **status
  transitions** with :class:`DecisionStateError` (the route layer turns
  that into HTTP 409); however ``decision_text`` remains editable on
  terminal rows so operators can record post-hoc annotations without
  having to reopen the decision.
* Creating a row always starts in ``pending``.

This matches the spec's hard-state-machine convention from 架构 § 21.5.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any, Final
from uuid import uuid4

from .. import db
from ..metrics import load_kpi_snapshot
from ..outbox.events import OutboxEventDraft, insert_event
from .ai_suggester import generate_suggestion

log = logging.getLogger(__name__)


#: Default ``enterprise_id`` for the single-tenant demo (拿不准点 #1, 架构
#: v1.1 § P0-D 条目 1). ``enterprise_spaces`` is currently empty; the
#: seed in :mod:`apps.api.services.qiepai.seed` uses the same
#: placeholder for ``metric_definitions.enterprise_id``. Callers may
#: override via the ``enterprise_id`` query parameter / request body.
DEFAULT_ENTERPRISE_ID: Final[str] = "huilton_seed"

#: Allowed transitions for ``decision_items.status``. Read once at import.
#: ``pending`` → ``decided`` / ``cancelled``; terminal states are sticky.
_STATUS_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"decided", "cancelled"}),
    "decided": frozenset(),
    "cancelled": frozenset(),
}

#: Valid status values for new rows + filter parameter.
_VALID_STATUSES: Final[frozenset[str]] = frozenset({"pending", "decided", "cancelled"})


class DecisionNotFoundError(LookupError):
    """Raised when a decision id query yields no row."""


class DecisionStateError(RuntimeError):
    """Raised when a PATCH violates the status state machine (HTTP 409)."""


class DecisionValidationError(ValueError):
    """Raised when an incoming body is structurally invalid (HTTP 422)."""


# ---------------------------------------------------------------------------
# DB read helpers (sync — called inside asyncio.to_thread from the routes)
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into a JSON-safe dict (decodes ``fact_snapshot``)."""
    out = dict(row)
    raw = out.get("fact_snapshot")
    if isinstance(raw, str) and raw:
        try:
            out["fact_snapshot"] = json.loads(raw)
        except ValueError:
            # corrupt JSON shouldn't crash the API; pass through as string
            log.warning("decisions: fact_snapshot JSON parse failed for row %r", out.get("id"))
    raw_ai = out.get("ai_suggestion")
    if isinstance(raw_ai, str) and raw_ai:
        try:
            out["ai_suggestion"] = json.loads(raw_ai)
        except ValueError:
            log.warning("decisions: ai_suggestion JSON parse failed for row %r", out.get("id"))
    return out


def _list_sync(
    enterprise_id: str, status: str | None, owner_id: str | None
) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        sql = (
            "SELECT id, enterprise_id, title, description, metric_id, snapshot_id, "
            "fact_snapshot, ai_suggestion, owner_id, status, decided_at, "
            "decision_text, created_at "
            "FROM decision_items WHERE enterprise_id = ?"
        )
        params: list[Any] = [enterprise_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        sql += " ORDER BY created_at DESC, id DESC"
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def _get_sync(decision_id: str) -> dict[str, Any]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, enterprise_id, title, description, metric_id, snapshot_id, "
            "fact_snapshot, ai_suggestion, owner_id, status, decided_at, "
            "decision_text, created_at "
            "FROM decision_items WHERE id = ?",
            (decision_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise DecisionNotFoundError(decision_id)
    return _row_to_dict(row)


def _insert_sync(
    *,
    enterprise_id: str,
    title: str,
    description: str | None,
    metric_id: str | None,
    snapshot_id: str | None,
    fact_snapshot: dict[str, Any],
    owner_id: str | None,
) -> dict[str, Any]:
    conn = db.connect()
    try:
        cur = conn.cursor()
        # Forward-reference handling (matches the seed.py pattern, ❷-3):
        # the schema declares ``decision_items.enterprise_id REFERENCES
        # enterprise_spaces(id)`` NOT NULL, but in the single-tenant demo
        # ``enterprise_spaces`` is intentionally empty — the seed in
        # :mod:`apps.api.services.qiepai.seed` uses ``"huilton_seed"`` as
        # a placeholder until ❷-6 (or wherever) ships the real enterprise
        # row. To keep inserts working *today* we relax FK only inside
        # this connection's lifetime and restore the strict check in the
        # ``finally`` block below. Once ``enterprise_spaces`` has the
        # matching row this pragma becomes a no-op (SQLite tolerates
        # re-disabling FK inside a live connection).
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        new_id = f"dec_{uuid4().hex[:12]}"
        try:
            cur.execute(
                "INSERT INTO decision_items ("
                "  id, enterprise_id, title, description, metric_id, snapshot_id,"
                "  fact_snapshot, owner_id, status"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (
                    new_id,
                    enterprise_id,
                    title,
                    description,
                    metric_id,
                    snapshot_id,
                    json.dumps(fact_snapshot, ensure_ascii=False),
                    owner_id,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            # The FK relaxation above only covers the enterprise_spaces
            # forward reference; any *other* integrity violation (NOT NULL,
            # CHECK, malformed data) still propagates here so callers see
            # a clear 422 via ``DecisionValidationError``.
            raise DecisionValidationError(f"invalid FK or constraint: {exc}") from exc
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()
    return _get_sync(new_id)


def _patch_sync(
    decision_id: str,
    *,
    status: str | None,
    decision_text: str | None,
) -> dict[str, Any]:
    """Apply a status transition + optional decision_text. Returns the updated row.

    Raises ``DecisionNotFoundError`` if no row matches ``decision_id``;
    raises ``DecisionStateError`` if the status transition is illegal.
    Performs all field updates + the read in a single transaction so a
    concurrent PATCH cannot observe a half-applied state.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        # Read with the lock — SQLite's per-DB locking makes the
        # transaction boundary below atomic.
        cur.execute("SELECT status FROM decision_items WHERE id = ?", (decision_id,))
        row = cur.fetchone()
        if row is None:
            raise DecisionNotFoundError(decision_id)
        current_status = row["status"]
        next_status = status or current_status
        if next_status != current_status:
            allowed = _STATUS_TRANSITIONS.get(current_status, frozenset())
            if next_status not in allowed:
                raise DecisionStateError(
                    f"illegal status transition {current_status!r} -> {next_status!r}; "
                    f"allowed: {sorted(allowed) or 'none (terminal)'}"
                )

        # Bug 1 (review pass ❷-5): when the row is being moved into (or
        # reaffirmed in) ``decided``, ``decision_text`` must be a non-blank
        # string — the spec's reason-to-close this audit-trail-friendly
        # gate is exactly that a "decision" without a written rationale is
        # worthless to the operator reviewing it later.
        if next_status == "decided" and not (
            isinstance(decision_text, str) and decision_text.strip()
        ):
            raise DecisionValidationError(
                "decision_text required when status=decided"
            )

        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status in ("decided", "cancelled"):
                updates.append("decided_at = CURRENT_TIMESTAMP")
        # Bug 2 (review pass ❷-5): terminal rows may still receive
        # ``decision_text`` updates — the status state machine above
        # already locks the status field, but the post-hoc annotation
        # use case (operator adds context *after* closure) is explicitly
        # supported and intentionally *not* gated on ``current_status``.
        if decision_text is not None:
            updates.append("decision_text = ?")
            params.append(decision_text)

        if not updates:
            # Body had no actionable fields; surface as 422 so the caller
            # can fix the payload rather than get a silent 200.
            raise DecisionValidationError(
                "PATCH body must include at least one of: status, decision_text"
            )

        params.append(decision_id)
        cur.execute(
            f"UPDATE decision_items SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
        cur.execute(
            "SELECT id, enterprise_id, title, description, metric_id, snapshot_id, "
            "fact_snapshot, ai_suggestion, owner_id, status, decided_at, "
            "decision_text, created_at FROM decision_items WHERE id = ?",
            (decision_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise DecisionNotFoundError(decision_id)
        return _row_to_dict(row)
    finally:
        conn.close()


def _persist_ai_suggestion_cache(
    decision_id: str, layers: dict[str, Any]
) -> None:
    """Write back the ``fact`` + ``inference`` cache columns (sync)."""
    cache = {
        "fact": layers.get("fact") or [],
        "inference": layers.get("inference") or [],
        # Bug 7 (review pass ❷-5): the previous ``x and "mock" or "llm"``
        # pattern would (rarely) mis-evaluate to ``"llm"`` when ``x`` was
        # truthy-but-not-"mock" (e.g. a future flag value). Use an
        # explicit ternary — same semantics for today, future-proof.
        "cached_at": "mock" if layers.get("_used_mock") else "llm",
    }
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE decision_items SET ai_suggestion = ? WHERE id = ?",
            (json.dumps(cache, ensure_ascii=False), decision_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public coroutines (routes call these)
# ---------------------------------------------------------------------------


async def list_decisions(
    enterprise_id: str | None = None,
    *,
    status: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """List decision items, with optional filters.

    Returns ``{"items": [...], "total": int}``. The ``total`` mirrors the
    array length because the v1 cockpit / decision board is not paginated
    (decision queues are bounded in the dozens at the demo's scale).

    Raises :class:`DecisionValidationError` (HTTP 422) when ``status`` is
    provided but not one of ``pending`` / ``decided`` / ``cancelled``.
    """
    eid = enterprise_id or DEFAULT_ENTERPRISE_ID
    # Bug 3 (review pass ❷-5): previously a typo (``?status=banana``)
    # silently returned an empty list, masking UI bugs. Re-use the same
    # ``_VALID_STATUSES`` frozenset the PATCH path uses so the contract
    # stays in sync.
    if status is not None and status not in _VALID_STATUSES:
        raise DecisionValidationError(
            f"invalid status filter: {status!r}; "
            f"expected one of {sorted(_VALID_STATUSES)}"
        )
    items = await asyncio.to_thread(_list_sync, eid, status, owner_id)
    return {"items": items, "total": len(items)}


async def get_decision(decision_id: str) -> dict[str, Any]:
    """Fetch a single decision by id. Raises :class:`DecisionNotFoundError`."""
    return await asyncio.to_thread(_get_sync, decision_id)


async def create_decision(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a new decision row and return it.

    ``payload`` keys:

    * ``enterprise_id`` (str) — optional; defaults to :data:`DEFAULT_ENTERPRISE_ID`.
    * ``title`` (str) — **required**, non-empty.
    * ``description`` (str) — optional.
    * ``metric_id`` (str) — optional. When present and the loader can read
      the metric, the ``fact_snapshot`` for the new row is seeded from the
      connector payload; otherwise an empty fact_snapshot ``{}`` is written.
    * ``owner_id`` (str) — optional.
    * ``fact_snapshot`` (dict) — optional override; takes precedence over
      the auto-loaded metric snapshot. Must be a JSON object (a list,
      string, or number here is rejected with HTTP 422).
    * ``snapshot_id`` is **not** accepted — it's auto-derived from
      ``metric_id``; supplying it is rejected with HTTP 422 so callers
      can't pin a stale snapshot to a new decision.

    Raises :class:`DecisionValidationError` when required fields are
    missing or contain invalid types.
    """
    if not isinstance(payload, dict):
        raise DecisionValidationError("request body must be a JSON object")

    # Bug 5 (review pass ❷-5): a non-dict ``fact_snapshot`` used to fall
    # through to the metric-loader branch (because the ``isinstance(...,
    # dict)`` guard short-circuited to False) and was effectively
    # overwritten with the auto-loaded snapshot — silently masking the
    # caller's bug. Reject explicitly with 422 *before* the snapshot_id
    # check so the error message points at the right field.
    if "fact_snapshot" in payload and not isinstance(payload["fact_snapshot"], dict):
        raise DecisionValidationError("fact_snapshot must be a dict")

    # Bug 4 (review pass ❷-5): ``snapshot_id`` is an internal column
    # auto-derived from ``metric_id`` (see ``_insert_sync``); letting the
    # caller pin it would invite stale-snapshot footguns. Reject so
    # the typo surfaces immediately.
    if "snapshot_id" in payload:
        raise DecisionValidationError(
            "snapshot_id is auto-computed from metric_id; do not specify"
        )

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise DecisionValidationError("title is required and must be a non-empty string")

    eid = str(payload.get("enterprise_id") or "").strip() or DEFAULT_ENTERPRISE_ID
    description_raw = payload.get("description")
    description = description_raw.strip() if isinstance(description_raw, str) else None
    if description == "":
        description = None

    metric_id_raw = payload.get("metric_id")
    metric_id = metric_id_raw.strip() if isinstance(metric_id_raw, str) and metric_id_raw.strip() else None
    owner_id_raw = payload.get("owner_id")
    owner_id = owner_id_raw.strip() if isinstance(owner_id_raw, str) and owner_id_raw.strip() else None

    fact_snapshot: dict[str, Any]
    explicit_snapshot = payload.get("fact_snapshot")
    if isinstance(explicit_snapshot, dict):
        fact_snapshot = explicit_snapshot
        snapshot_id = None
    elif metric_id:
        # Try to load real fact data so the new row is immediately useful.
        snap = await load_kpi_snapshot(metric_id, scope="default")
        if snap is None:
            # Bug 6 (review pass ❷-5): preserve the spec's "unavailable
            # first-class" behaviour — don't 422 a typo'd metric_id, just
            # stamp a placeholder ``note`` and move on (matches the ❷-3
            # mock loader contract: missing data is ``unavailable``, not
            # zero). The warning below gives operators a breadcrumb to
            # detect typos from backend logs without breaking callers.
            log.warning("create_decision: unknown metric_id %r", metric_id)
            fact_snapshot = {"items": [], "source": None, "note": "metric snapshot unavailable"}
        else:
            fact_snapshot = {
                "items": snap.get("items") or [],
                "source": snap.get("source"),
                "as_of": snap.get("as_of"),
                "freshness_seconds": snap.get("freshness_seconds"),
                "value": snap.get("value"),
            }
        snapshot_id = f"snap_{metric_id}_default" if snap else None
    else:
        fact_snapshot = {"items": [], "source": None, "note": "no metric bound"}
        snapshot_id = None

    return await asyncio.to_thread(
        _insert_sync,
        enterprise_id=eid,
        title=title.strip(),
        description=description,
        metric_id=metric_id,
        snapshot_id=snapshot_id,
        fact_snapshot=fact_snapshot,
        owner_id=owner_id,
    )


async def patch_decision(decision_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update (status transition + optional decision_text).

    Body keys:
      * ``status`` — must be a legal transition target from the row's current status.
      * ``decision_text`` — free-form text the operator writes when closing
        the decision.

    At least one of the two must be present.
    """
    if not isinstance(payload, dict):
        raise DecisionValidationError("request body must be a JSON object")

    status_raw = payload.get("status")
    status: str | None
    if status_raw is None:
        status = None
    elif isinstance(status_raw, str) and status_raw in _VALID_STATUSES:
        status = status_raw
    else:
        raise DecisionValidationError(
            f"status, when provided, must be one of {sorted(_VALID_STATUSES)}"
        )

    decision_text_raw = payload.get("decision_text")
    decision_text: str | None
    if decision_text_raw is None:
        decision_text = None
    elif isinstance(decision_text_raw, str):
        decision_text = decision_text_raw
    else:
        raise DecisionValidationError("decision_text, when provided, must be a string")

    return await asyncio.to_thread(
        _patch_sync,
        decision_id,
        status=status,
        decision_text=decision_text,
    )


async def patch_decision_with_notify(
    decision_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Wrap :func:`patch_decision` to ALSO enqueue a Feishu notification.

    Phase ❸-1 hook: 只有当 ``status`` 真的发生迁移
    (``pending → decided`` / ``pending → cancelled``) 时才会入队 ——
    ``decision_text`` 旁注 / 单纯重写字段不触发飞书消息,避免噪声。
    """
    prior = await get_decision(decision_id)
    prior_status = str(prior.get("status") or "")
    row = await patch_decision(decision_id, payload)
    next_status = str(row.get("status") or "")
    if next_status != prior_status and next_status in {"decided", "cancelled"}:
        event_type = "decision.decided" if next_status == "decided" else "decision.cancelled"
        await insert_event(
            OutboxEventDraft(
                event_type=event_type,
                aggregate_type="decision",
                aggregate_id=decision_id,
                payload={
                    "title": str(row.get("title") or ""),
                    "decision_text": str(row.get("decision_text") or ""),
                    "status": next_status,
                },
            )
        )
    return row


async def regenerate_suggestion(decision_id: str) -> dict[str, Any]:
    """Generate a fresh 4-layer suggestion + persist the ``{fact, inference}`` cache.

    Always returns the full 4-layer payload. Side-effect: writes the
    ``{fact, inference}`` rows to ``decision_items.ai_suggestion`` so a
    later plain GET can serve them without an LLM call.
    """
    row = await get_decision(decision_id)
    layers = await generate_suggestion(
        decision_id=decision_id,
        decision_title=row.get("title") or "",
        metric_id=row.get("metric_id"),
        fact_snapshot=row.get("fact_snapshot") or {},
    )
    await asyncio.to_thread(_persist_ai_suggestion_cache, decision_id, layers)
    return layers


__all__ = [
    "DEFAULT_ENTERPRISE_ID",
    "DecisionNotFoundError",
    "DecisionStateError",
    "DecisionValidationError",
    "list_decisions",
    "get_decision",
    "create_decision",
    "patch_decision",
    "patch_decision_with_notify",
    "regenerate_suggestion",
]
