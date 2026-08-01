"""qiepai · tasks router (Phase ❷-6: real business logic).

Replaces the ❷-1 stub with five real endpoints backed by
``apps.api.services.qiepai.tasks.service``.

Endpoints
=========

* ``GET    /tasks?enterprise_id=&status=&assignee_id=&decision_id=`` — list with filters
* ``GET    /tasks/{id}``                                             — single task
* ``POST   /tasks``                                                  — create
* ``PATCH  /tasks/{id}``                                             — update status / assignee_id / description
* ``DELETE /tasks/{id}``                                             — physical delete

Mount path: prefix ``/qiepai`` (set in ``apps/api/routes/qiepai/__init__.py``)
+ parent prefix ``/api`` (set in ``apps/unified/main.py``) →
final URLs are ``/api/qiepai/tasks/...``.

Error model
===========

The route maps service exceptions to HTTP semantics:

* ``BusinessTaskValidationError`` → 422 (bad body, bad filter, empty PATCH)
* ``BusinessTaskStateError``      → 409 (illegal status transition)
* ``BusinessTaskNotFoundError``   → 404 (unknown id)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.api.services.qiepai.tasks import service

router = APIRouter(tags=["qiepai-tasks"])


@router.get("/tasks")
async def list_tasks(
    enterprise_id: str | None = Query(
        default=None,
        description="企业空间 id;省略时使用默认占位 huilton_seed",
    ),
    status: str | None = Query(
        default=None,
        description="按 status 过滤;可选 todo / in_progress / done / cancelled",
    ),
    assignee_id: str | None = Query(default=None, description="按 assignee_id 过滤"),
    decision_id: str | None = Query(
        default=None,
        description="按关联的 decision_id 过滤",
    ),
) -> dict[str, Any]:
    """业务任务列表 — 支持 status / assignee_id / decision_id 过滤."""
    try:
        return await service.list_tasks(
            enterprise_id=enterprise_id,
            status=status,
            assignee_id=assignee_id,
            decision_id=decision_id,
        )
    except service.BusinessTaskValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    """单条业务任务详情."""
    try:
        return await service.get_task(task_id)
    except service.BusinessTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc


@router.post("/tasks")
async def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    """建业务任务 — 入参: {title, description?, decision_id?, assignee_id?, enterprise_id?}.

    Side effect (Phase ❸-1): 入队一条 ``task.assigned`` 飞书事件。
    """
    try:
        return await service.create_task_with_notify(payload)
    except service.BusinessTaskValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """改 status / assignee_id / description — 状态机硬约束见 service.

    Side effect (Phase ❸-1): 状态迁移到 ``done`` / ``cancelled`` 时入队
    ``task.completed`` / ``task.cancelled`` 飞书事件,中间状态
    ``in_progress`` 不入队 (避免噪声)。
    """
    try:
        return await service.patch_task_with_notify(task_id, payload)
    except service.BusinessTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc
    except service.BusinessTaskValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.BusinessTaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/tasks/{task_id}", status_code=200)
async def delete_task(task_id: str) -> dict[str, Any]:
    """物理删除业务任务 — spec 走物理删 (demo 单租户)."""
    try:
        await service.delete_task(task_id)
    except service.BusinessTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}") from exc
    return {"id": task_id, "deleted": True}
