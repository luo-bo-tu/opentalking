"""qiepai · employees router (Phase ❷-6: real business logic).

Replaces the ❷-1 stub with seven real endpoints backed by
``apps.api.services.qiepai.employees.service`` and the pure
:mod:`apps.api.services.qiepai.employees.state_machine` module.

Endpoints
=========

* ``GET    /employees?enterprise_id=``                       — list
* ``GET    /employees/{id}``                                 — single employee
* ``POST   /employees``                                      — create
* ``PATCH  /employees/{id}``                                 — display_name / role / persona_id
* ``DELETE /employees/{id}``                                 — hard delete (cascades revisions)
* ``POST   /employees/{id}/revisions``                       — append a revision
* ``GET    /employees/{id}/revisions``                       — list revisions
* ``POST   /employees/{id}/publish``                         — advance the state machine

Mount path: prefix ``/qiepai`` (set in ``apps/api/routes/qiepai/__init__.py``)
+ parent prefix ``/api`` (set in ``apps/unified/main.py``) →
final URLs are ``/api/qiepai/employees/...``.

Error model
===========

* ``EmployeeValidationError``  → 422 (bad body, readiness gate fail)
* ``EmployeeStateError``       → 409 (illegal status transition)
* ``EmployeeConflictError``    → 409 (persona 1:1 violation)
* ``EmployeeNotFoundError``    → 404 (unknown employee)
* ``EmployeeRevisionNotFoundError`` → 404 (unknown revision)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.api.services.qiepai.employees import service

router = APIRouter(tags=["qiepai-employees"])


@router.get("/employees")
async def list_employees(
    enterprise_id: str | None = Query(
        default=None,
        description="企业空间 id;省略时使用默认占位 huilton_seed",
    ),
) -> dict[str, Any]:
    """数字员工列表."""
    return await service.list_employees(enterprise_id=enterprise_id)


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str) -> dict[str, Any]:
    """单条数字员工详情."""
    try:
        return await service.get_employee(employee_id)
    except service.EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"employee not found: {employee_id}") from exc


@router.post("/employees")
async def create_employee(payload: dict[str, Any]) -> dict[str, Any]:
    """建数字员工 — 入参: {display_name, role, persona_id?, enterprise_id?}.

    ``persona_id`` 1:1 校验: 已关联其他 employee → 409.
    """
    try:
        return await service.create_employee(payload)
    except service.EmployeeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.EmployeeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/employees/{employee_id}")
async def patch_employee(employee_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """改 display_name / role / persona_id. ``status`` 改走 publish 流程."""
    try:
        return await service.patch_employee(employee_id, payload)
    except service.EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"employee not found: {employee_id}") from exc
    except service.EmployeeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.EmployeeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/employees/{employee_id}", status_code=200)
async def delete_employee(employee_id: str) -> dict[str, Any]:
    """物理删除数字员工 + cascade 删 revisions."""
    try:
        await service.delete_employee(employee_id)
    except service.EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"employee not found: {employee_id}") from exc
    return {"id": employee_id, "deleted": True}


@router.get("/employees/{employee_id}/revisions")
async def list_revisions(employee_id: str) -> dict[str, Any]:
    """revision 列表 (newest first)."""
    try:
        return await service.list_revisions(employee_id)
    except service.EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"employee not found: {employee_id}") from exc


@router.post("/employees/{employee_id}/revisions", status_code=201)
async def create_revision(employee_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """建新 revision — 入参: {workspace_file_hash, config_snapshot}.

    ``revision_number`` 自动递增 (UNIQUE per employee).
    """
    try:
        return await service.create_revision(employee_id, payload)
    except service.EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"employee not found: {employee_id}") from exc
    except service.EmployeeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/employees/{employee_id}/publish")
async def publish_employee(employee_id: str) -> dict[str, Any]:
    """推进 publish state machine — 拒绝跳跃 + readiness 硬约束.

    每次调用推进 1 步规范链:
      draft → configuring → ready → published → suspended → retired
    (``retired → published`` 是误操作恢复路径)

    推到 ``ready`` / ``published`` 时强制 readiness_p0/p1 全过 + sync_state != error/drifted.

    Side effect (Phase ❸-1): 每次成功推进一步都会向 ``outbox_events``
    入队一条 ``employee.published`` 事件,飞书群机器人会在下一次轮询
    时送出。失败的状态变更 (4xx) 不会入队 — 调试阶段不需要这种噪声。
    """
    try:
        return await service.publish_employee_with_notify(employee_id)
    except service.EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"employee not found: {employee_id}") from exc
    except service.EmployeeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.EmployeeStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
