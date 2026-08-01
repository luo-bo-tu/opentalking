"""qiepai · outbox admin router (Phase ❸-1).

Read-only endpoints over the ``outbox_events`` table — primarily for
the operator dashboard (FeishuBotPanel) to inspect what's queued,
in-flight, retried, or permanently failed. Plus a small "fire a manual
trigger" helper used by the UI's demo button.

Endpoints
=========

* ``GET  /qiepai/outbox/events``                          — paginated list (limit/offset/state filters)
* ``GET  /qiepai/outbox/events/{event_id}``              — single row by id
* ``POST /qiepai/outbox/events/trigger_demo``            — enqueue a
  ``system.demo_notify`` row (smoke-test affordance for the UI)
* ``POST /qiepai/outbox/events/{event_id}/replay``       — reset a failed
  row back to ``state='pending'`` so the worker re-attempts it.

Mount path: ``/qiepai/outbox`` (this router) → ``/api/qiepai/outbox/*``.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.api.services.qiepai import db as qiepai_db
from apps.api.services.qiepai.outbox.events import (
    EVENT_TYPES,
    OutboxEventDraft,
    build_event_payload,
    insert_event,
)

router = APIRouter(prefix="/outbox", tags=["qiepai-outbox"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    payload_text = out.get("payload")
    if isinstance(payload_text, str) and payload_text:
        try:
            out["payload"] = json.loads(payload_text)
        except ValueError:
            out["payload"] = {"_raw": payload_text}
    return out


def _list_events(
    *,
    limit: int,
    offset: int,
    state: str | None,
    event_type: str | None,
) -> tuple[list[dict[str, Any]], int]:
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        where: list[str] = []
        params: list[Any] = []
        if state:
            where.append("state = ?")
            params.append(state)
        if event_type:
            where.append("event_type = ?")
            params.append(event_type)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        cur.execute(f"SELECT COUNT(*) AS n FROM outbox_events{where_sql}", tuple(params))
        total = int(cur.fetchone()["n"])

        cur.execute(
            f"SELECT id, event_type, aggregate_type, aggregate_id, payload, state, "
            f"attempts, last_error, next_retry_at, created_at "
            f"FROM outbox_events{where_sql} "
            f"ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows], total


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


_VALID_STATES: tuple[str, ...] = ("pending", "published", "failed")


@router.get("/events")
async def list_outbox_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    state: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
) -> dict[str, Any]:
    """Paginated list of outbox events, newest first.

    Optional ``state`` / ``event_type`` filters make the endpoint
    suitable for both the "recent activity" tab and the "failed rows
    inspector" tab on the operator dashboard.
    """
    if state is not None and state not in _VALID_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"state must be one of {list(_VALID_STATES)}",
        )
    items, total = _list_events(
        limit=limit, offset=offset, state=state, event_type=event_type
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "state": state,
        "event_type": event_type,
        "event_types": sorted(EVENT_TYPES),
    }


@router.get("/events/{event_id}")
async def get_outbox_event(event_id: str) -> dict[str, Any]:
    """Return the row + the decoded payload (so the UI renders card preview)."""
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, event_type, aggregate_type, aggregate_id, payload, state, "
            "attempts, last_error, next_retry_at, created_at "
            "FROM outbox_events WHERE id = ?",
            (event_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"outbox event not found: {event_id}")
    decoded = _row_to_dict(row)
    decoded["rendered_payload"] = build_event_payload(
        decoded["event_type"],
        decoded["aggregate_type"],
        decoded["aggregate_id"],
        json.dumps(decoded.get("payload") or {}, ensure_ascii=False),
    )
    return decoded


@router.post("/events/trigger_demo", status_code=201)
async def trigger_demo_event(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Enqueue a ``system.demo_notify`` row for the operator to click.

    Used by the FeishuBotPanel "demo notification" button — gives the
    operator a way to verify the whole pipeline (insert → worker →
    publisher) without having to fire a real employee publish.
    """
    payload = payload or {}
    message = str(payload.get("message") or "phase ❸-1 demo notify").strip()
    draft = OutboxEventDraft(
        event_type="system.demo_notify",
        aggregate_type="system",
        aggregate_id=f"demo-{uuid.uuid4().hex[:8]}",
        payload={
            "display_name": "Phase ❸-1 demo",
            "message": message,
        },
    )
    event_id = await insert_event(draft)
    return {
        "id": event_id,
        "event_type": draft.event_type,
        "aggregate_type": draft.aggregate_type,
        "aggregate_id": draft.aggregate_id,
    }


@router.post("/events/trigger_kpi_anomaly", status_code=201)
async def trigger_kpi_anomaly(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the lightweight KPI anomaly detector + enqueue ``kpi.anomaly`` rows.

    Phase ❸-1 trigger #4: the spec calls for "KPI snapshot 异常 (检测
    logic 单独跑) → INSERT outbox_event". We expose that as an
    on-demand endpoint instead of running a periodic loop (the demo
    dataset is too small for periodic runs to be useful). The
    detector queries :mod:`apps.api.services.qiepai.cockpit.service`
    and inserts an event per metric that crosses the operator-supplied
    threshold.

    Body (all optional)::
        {"metric_id": "financial-kpi",
         "threshold": 50.0,
         "unit": "万元"}
    """
    payload = payload or {}
    metric_id = str(payload.get("metric_id") or "").strip()
    threshold_raw = payload.get("threshold")
    unit = str(payload.get("unit") or "").strip()

    # Lazy import to avoid forcing a LoadKpiSnapshot failure during unit
    # tests that don't have the metric seed loaded.
    from apps.api.services.qiepai.cockpit import service as cockpit_service

    snapshot = await cockpit_service.list_kpis() if not metric_id else None

    anomaly_rows: list[dict[str, Any]] = []
    if snapshot and snapshot.get("kpis"):
        for card in snapshot["kpis"]:
            value = card.get("value")
            if value is None:
                continue
            if metric_id and str(card.get("id") or "") != metric_id:
                continue
            if threshold_raw is not None and not _above_threshold(value, threshold_raw):
                continue
            event = OutboxEventDraft(
                event_type="kpi.anomaly",
                aggregate_type="kpi",
                aggregate_id=str(card.get("id") or card.get("metric_id") or ""),
                payload={
                    "metric_name": str(card.get("name") or card.get("id") or ""),
                    "metric_value": value,
                    "unit": str(card.get("unit") or unit),
                    "threshold": threshold_raw if threshold_raw is not None else "auto",
                    "display_name": "KPI 异常告警",
                    "message": (
                        f"{card.get('name') or card.get('id')} 跳过阈值 "
                        f"({value} > {threshold_raw})"
                    ),
                },
            )
            event_id = await insert_event(event)
            anomaly_rows.append(
                {
                    "id": event_id,
                    "metric_id": event.aggregate_id,
                    "value": value,
                }
            )

    return {
        "detected": len(anomaly_rows),
        "rows": anomaly_rows,
        "metric_id": metric_id,
        "threshold": threshold_raw,
    }


def _above_threshold(value: Any, threshold: Any) -> bool:
    """Return True iff ``value > threshold`` (numeric comparison)."""
    try:
        return float(value) > float(threshold)
    except (TypeError, ValueError):
        return False


@router.post("/events/{event_id}/replay")
async def replay_event(event_id: str) -> dict[str, Any]:
    """Reset a failed row back to ``state='pending'``.

    Failure rows stay in the table forever (audit trail) but with
    ``state='failed'`` they won't be polled. This endpoint clears
    ``last_error`` + bumps attempts so the worker re-tries.
    """
    conn = qiepai_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE outbox_events SET state = 'pending', last_error = NULL, "
            "next_retry_at = NULL WHERE id = ? AND state = 'failed'",
            (event_id,),
        )
        conn.commit()
        rowcount = cur.rowcount
    finally:
        conn.close()
    if rowcount == 0:
        raise HTTPException(
            status_code=409,
            detail=f"event {event_id!r} is not in state='failed'; nothing to replay",
        )
    return {"id": event_id, "replayed": True}


__all__ = ["router"]
