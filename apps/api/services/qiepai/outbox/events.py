"""qiepai · outbox event type catalogue (Phase ❸-1).

Single source of truth for:

* The canonical ``event_type`` strings (12 recognised today, see
  :data:`EVENT_TYPES`) — these strings land verbatim in the
  ``outbox_events.event_type`` column and are matched by the worker
  to pick a Feishu card template.
* The :class:`OutboxEventDraft` + :func:`insert_event` helpers that
  callers (business services) use to enqueue an event. Insertion is
  fire-and-forget — exceptions are logged but never raised into the
  HTTP path so an outbox failure cannot break a business write
  (the foreign-key payload is preserved in the business row, the
  notification is best-effort).
* The :func:`build_event_payload` dispatcher invoked by
  :mod:`.publisher` to turn a draft into a Feishu interactive-card
  body.

Event-type catalogue (v1)
=========================

The twelve types below are the only ones we emit today; adding a new
trigger means (1) extending this catalogue + (2) adding a payload
builder. The cost of an unrecognised event_type caught at the publisher
is "skipped + warning logged" rather than "raised to the worker loop" —
that keeps an out-of-date worker from crashing the rest of the queue.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Final

from .. import db

log = logging.getLogger(__name__)


#: Set of canonical event_type strings the publisher understands. An
#: event whose type is not in this set is logged and skipped at the
#: publisher so a future-added trigger can ship without breaking the
#: running worker.
EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        # employee lifecycle
        "employee.published",
        "employee.failed_publish",
        # decision lifecycle
        "decision.created",
        "decision.decided",
        "decision.cancelled",
        # task lifecycle
        "task.assigned",
        "task.completed",
        "task.cancelled",
        # KPI / metrics
        "kpi.anomaly",
        "kpi.freshness_warning",
        # manual / demo triggers (Phase ❸ helper)
        "system.demo_notify",
        "system.heartbeat",
    }
)


@dataclass(frozen=True)
class OutboxEventDraft:
    """In-memory description of an event ready to be persisted.

    Fields mirror the :class:`outbox_events` table columns verbatim so
    the persistence helper can do a straight INSERT without remapping.

    Attributes
    ----------
    event_type
        A member of :data:`EVENT_TYPES`; an unknown value will be stored
        but the publisher will skip it (warning logged).
    aggregate_type
        Resource family — ``"employee"``, ``"decision"``, ``"task"``,
        ``"kpi"``, ``"system"``. Used by the Feishu card template to
        pick icon + colour.
    aggregate_id
        Primary key of the originating resource (string; may be
        composite-key encoded).
    payload
        Free-form JSON-serialisable dict. Stored as TEXT via
        :func:`json.dumps` and re-decoded by the publisher. Must NOT
        contain non-serialisable values (no bytes / datetime / pydantic
        models).
    """

    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]

    def validate(self) -> None:
        """Raise :class:`ValueError` for any malformed draft.

        Cheap structural check — the publisher will run its own content
        validation later. We surface obvious typos here so the business
        service sees a clear stack trace when it ships a bug.
        """
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        if not isinstance(self.aggregate_type, str) or not self.aggregate_type.strip():
            raise ValueError("aggregate_type must be a non-empty string")
        if not isinstance(self.aggregate_id, str) or not self.aggregate_id.strip():
            raise ValueError("aggregate_id must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dict")
        # Best-effort serialisation probe so the caller sees a clear
        # failure when the payload contains datetime / bytes / etc.
        try:
            json.dumps(self.payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload is not JSON-serialisable: {exc}") from exc


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _insert_sync(draft: OutboxEventDraft) -> str:
    """Persist a single event row. Returns the assigned row id.

    The ``id`` is a UUID-prefixed string (``out_<12-hex>``) — the worker
    uses it as the primary handle when it claims a batch. ``state``
    defaults to ``"pending"`` on the SQL side (via the column default).

    Sync because every callsite is already inside ``asyncio.to_thread``
    (or a test fixture). The DB is small + WAL, so contention is rare.
    """
    draft.validate()
    new_id = f"out_{uuid.uuid4().hex[:12]}"
    payload_text = json.dumps(draft.payload, ensure_ascii=False)
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO outbox_events ("
            "  id, event_type, aggregate_type, aggregate_id, payload, state"
            ") VALUES (?, ?, ?, ?, ?, 'pending')",
            (
                new_id,
                draft.event_type,
                draft.aggregate_type,
                draft.aggregate_id,
                payload_text,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise RuntimeError(
            f"outbox_events insert failed for {draft.event_type!r}: {exc}"
        ) from exc
    finally:
        conn.close()
    log.debug(
        "outbox: queued %s id=%s aggregate=%s/%s",
        draft.event_type,
        new_id,
        draft.aggregate_type,
        draft.aggregate_id,
    )
    return new_id


async def insert_event(draft: OutboxEventDraft) -> str | None:
    """Async helper: enqueue an event. Returns the row id or ``None`` on failure.

    Business code should ``await insert_event(...)`` and **ignore the
    return value**: a failure is logged at WARNING but does not raise,
    because raising into a FastAPI request handler would surface a 500
    on the originating business write (e.g. publish, PATCH). The
    outbox is best-effort by design.

    Tests that want to assert success call the lower-level
    :func:`_insert_sync` directly, which raises on persistence errors.
    """
    try:
        return await asyncio_to_thread_insert(draft)
    except Exception:  # noqa: BLE001
        log.warning(
            "outbox: insert_event failed for %s aggregate=%s/%s",
            draft.event_type,
            draft.aggregate_type,
            draft.aggregate_id,
            exc_info=True,
        )
        return None


async def asyncio_to_thread_insert(draft: OutboxEventDraft) -> str:
    """Wrap :func:`_insert_sync` in ``asyncio.to_thread``.

    Split out as its own function so test code can patch the sync helper
    directly without going through the thread pool. The function name is
    intentionally long to discourage accidental import — public callers
    should use :func:`insert_event`.
    """
    from asyncio import to_thread

    return await to_thread(_insert_sync, draft)


# ---------------------------------------------------------------------------
# Payload builders (called by the publisher when rendering Feishu cards)
# ---------------------------------------------------------------------------


def build_event_payload(
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload_text: str,
) -> dict[str, Any]:
    """Return a normalised dict for the publisher.

    Decodes the JSON ``payload`` column once and merges the dispatch
    keys up so the publisher can use ``payload['title']`` regardless
    of which trigger produced the event.
    """
    try:
        body = json.loads(payload_text) if payload_text else {}
    except ValueError:
        log.warning(
            "outbox: payload JSON parse failed for event_type=%s id=%s; "
            "using empty dict",
            event_type,
            aggregate_id,
        )
        body = {}
    if not isinstance(body, dict):
        body = {"raw": body}
    body.setdefault("_event_type", event_type)
    body.setdefault("_aggregate_type", aggregate_type)
    body.setdefault("_aggregate_id", aggregate_id)
    return body


__all__ = [
    "EVENT_TYPES",
    "OutboxEventDraft",
    "insert_event",
    "build_event_payload",
]
