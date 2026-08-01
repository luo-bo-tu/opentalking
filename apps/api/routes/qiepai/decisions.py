"""qiepai · decisions router (Phase ❷-5: real business logic).

Replaces the ❷-1 stub (which only served ``GET /decisions`` returning
``{"status": "stub", ...}``) with five real endpoints backed by
``apps.api.services.qiepai.decisions.service``.

Endpoints
=========

* ``GET    /decisions?enterprise_id=&status=&owner_id=``     — list with filters
* ``GET    /decisions/{id}``                                  — single decision detail
* ``POST   /decisions``                                        — manual creation
* ``PATCH  /decisions/{id}``                                   — update status / decision_text
* ``GET    /decisions/{id}/ai-suggestion``                     — regenerate 4-layer AI

Mount path: prefix ``/qiepai`` (set in ``apps/api/routes/qiepai/__init__.py``)
+ parent prefix ``/api`` (set in ``apps/unified/main.py``) →
final URLs are ``/api/qiepai/decisions/...``.

Error model
===========

The route uses HTTP semantics that match the service exceptions:

* ``DecisionValidationError``     → 422 (bad body, bad transition target)
* ``DecisionStateError``          → 409 (illegal transition: terminal → anything)
* ``DecisionNotFoundError``       → 404 (unknown id)

The mapping lives in a single ``_error_payload`` helper so the error
contract can evolve in one place.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.api.services.qiepai.decisions import service

router = APIRouter(tags=["qiepai-decisions"])


@router.get("/decisions")
async def list_decisions(
    enterprise_id: str | None = Query(
        default=None,
        description="企业空间 id;省略时使用默认占位 huilton_seed",
    ),
    status: str | None = Query(
        default=None,
        description="按 status 过滤;可选 pending / decided / cancelled",
    ),
    owner_id: str | None = Query(default=None, description="按 owner_id 过滤"),
) -> dict[str, Any]:
    """决策项队列 — 支持 status / owner_id 过滤."""
    try:
        return await service.list_decisions(
            enterprise_id=enterprise_id,
            status=status,
            owner_id=owner_id,
        )
    except service.DecisionValidationError as exc:
        # Bug 3 (review pass ❷-5): the service now rejects an invalid
        # ``status`` filter with :class:`DecisionValidationError`; map
        # it to HTTP 422 here so the contract matches the other routes.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/decisions/{decision_id}")
async def get_decision(decision_id: str) -> dict[str, Any]:
    """单条决策项详情."""
    try:
        return await service.get_decision(decision_id)
    except service.DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"decision not found: {decision_id}") from exc


@router.post("/decisions")
async def create_decision(payload: dict[str, Any]) -> dict[str, Any]:
    """人工建项 — 入参: {title, description?, enterprise_id?, metric_id?, owner_id?}."""
    try:
        return await service.create_decision(payload)
    except service.DecisionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/decisions/{decision_id}")
async def patch_decision(decision_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """改 status / decision_text — 状态机硬约束:pending → decided/cancelled.

    Side effect (Phase ❸-1): 状态迁移到 ``decided`` / ``cancelled`` 时
    入队一条 ``decision.decided`` / ``decision.cancelled`` 事件。
    旁注 ``decision_text`` 不入队 (同一行更新多个字段时只发一次卡)。
    """
    try:
        return await service.patch_decision_with_notify(decision_id, payload)
    except service.DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"decision not found: {decision_id}") from exc
    except service.DecisionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.DecisionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/decisions/{decision_id}/ai-suggestion")
async def get_ai_suggestion(decision_id: str) -> dict[str, Any]:
    """重新生成 4 层 AI 建议(fact / inference / suggestion / unknown).

    Always returns a 4-layer payload. OpenClaw 调用失败时降级到 mock,
    通过 `_warning` 字段告知前端。

    Side effect: 写入 ``decision_items.ai_suggestion`` 缓存
    (``{fact, inference}``) 这样后续普通 GET 也能拿到最近一次建议。
    """
    try:
        return await service.regenerate_suggestion(decision_id)
    except service.DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"decision not found: {decision_id}") from exc
