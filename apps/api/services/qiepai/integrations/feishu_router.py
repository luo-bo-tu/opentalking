"""qiepai · Feishu integration REST routes (Phase ❸-1).

Three endpoints back the web UI's ``FeishuBotPanel``:

* ``GET  /integrations/feishu/groups``        — list bound chat ids.
* ``POST /integrations/feishu/groups``        — add a new chat id.
* ``POST /integrations/feishu/groups/{id}/delete`` — remove a chat id.
* ``POST /integrations/feishu/test``          — fire a one-shot
  ``system.heartbeat`` event through the publisher (for the operator
  to verify the token + chat_id + outbound connectivity end-to-end).

Mount path
==========

Each service module under ``apps.api.routes.qiepai`` is wired into the
aggregate ``router`` in ``apps.api.routes.qiepai.__init__``. The
``integrations`` module follows the same convention: the underlying
``feishu_router`` is rooted at ``/integrations/feishu`` and the
aggregate ``/qiepai`` prefix (from ``apps.api.routes.qiepai.__init__``)
+ the global ``/api`` prefix (mounted in ``apps.unified.main``) gives
final URLs like ``/api/qiepai/integrations/feishu/groups``.

Error model
===========

Validation errors (missing name / chat_id) → 422.
Unknown group on delete → 404.
Publisher errors → 502 with the Feishu code so the UI can render the
exact reason to the operator.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from . import feishu_settings as feishu_settings_module
from .registry import get_registry

# NOTE: ``outbox.events`` / ``outbox.publisher`` are imported lazily inside
# the handlers to avoid a circular import: ``outbox.publisher`` imports
# ``integrations.feishu_settings`` which traverses this module before
# publisher is fully initialised.

log = logging.getLogger(__name__)


router = APIRouter(prefix="/integrations/feishu", tags=["qiepai-integrations-feishu"])


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------


@router.get("/groups")
async def list_groups() -> dict[str, Any]:
    """Return all bound Feishu groups.

    Response shape: ``{"items": [...], "total": int, "configured": bool}``.

    ``configured`` reflects whether the publisher has credentials
    available (``QIEPAI_FEISHU_APP_ID`` + ``QIEPAI_FEISHU_APP_SECRET``),
    so the UI can render a prominent CTA when the operator hasn't set
    up the env vars yet.
    """
    items = await get_registry().list_groups()
    settings = feishu_settings_module.feishu_settings()
    return {
        "items": [g.to_dict() for g in items],
        "total": len(items),
        "configured": settings.is_configured(),
        "webhook_url_configured": bool(settings.webhook_url),
    }


@router.post("/groups", status_code=201)
async def create_group(payload: dict[str, Any]) -> dict[str, Any]:
    """Add a new Feishu group binding.

    Body::

        {
          "name": "老板群",
          "chat_id": "oc_xxxxxxxxxxxx",
          "enabled": true
        }
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object")

    name_raw = payload.get("name")
    name = str(name_raw or "").strip() if isinstance(name_raw, str) else ""
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    chat_id_raw = payload.get("chat_id")
    chat_id = str(chat_id_raw or "").strip() if isinstance(chat_id_raw, str) else ""
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    enabled_raw = payload.get("enabled", True)
    enabled = bool(enabled_raw) if isinstance(enabled_raw, bool) else True

    try:
        group = await get_registry().create_group(
            name=name, chat_id=chat_id, enabled=enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return group.to_dict()


@router.post("/groups/{group_id}/delete")
async def delete_group(group_id: str) -> dict[str, Any]:
    """Remove a Feishu group binding. 404 if the id is unknown."""
    ok = await get_registry().delete_group(group_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"feishu group not found: {group_id}")
    return {"id": group_id, "deleted": True}


# ---------------------------------------------------------------------------
# Test delivery (synchronous fire-and-forget for the operator)
# ---------------------------------------------------------------------------


@router.post("/test")
async def test_delivery(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fire a one-shot ``system.heartbeat`` event straight through the publisher.

    The endpoint deliberately bypasses the outbox so the operator can
    see a result in < 5s rather than waiting for the worker loop.
    Returns ``{ok, mode, info, event_type}`` — same shape the worker
    sees, so the UI can render the response uniformly.

    Body (optional)::

        {"chat_id": "oc_..."}
    """
    payload = payload or {}
    chat_id = ""
    if isinstance(payload, dict):
        chat_id_raw = payload.get("chat_id")
        if isinstance(chat_id_raw, str):
            chat_id = chat_id_raw.strip()
    # Fall back to the first registered group.
    if not chat_id:
        from .registry import first_active_chat_id

        chat_id = await first_active_chat_id()

    import json as _json
    from ..outbox.events import OutboxEventDraft, insert_event
    from ..outbox.publisher import PublishError, publish_outbox_event

    event = OutboxEventDraft(
        event_type="system.heartbeat",
        aggregate_type="system",
        aggregate_id="integration-test",
        payload={
            "display_name": "Feishu 通道测试",
            "message": "如果能看到这条卡片,说明飞书通道已联通。",
            "operator": str(payload.get("operator") or "operator"),
        },
    )
    try:
        outcome = await publish_outbox_event(
            None,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_text=_json.dumps(event.payload, ensure_ascii=False),
            chat_id=chat_id,
        )
    except PublishError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "status_code": exc.status_code,
                "retryable": exc.retryable,
            },
        ) from exc

    # Also enqueue an outbox row for the eventual worker sweep so the
    # operator can see the same event in the dashboard table.
    event_id = await insert_event(event)
    outcome["event_id"] = event_id
    outcome["event_type"] = event.event_type
    return outcome


__all__ = ["router"]
