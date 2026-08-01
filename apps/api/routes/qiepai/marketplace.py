"""qiepai · marketplace router (Phase ❹: real business logic).

Replaces nothing yet (❹ is the first phase that ships the marketplace
domain). Backed by ``apps.api.services.qiepai.marketplace.service`` and
the ``apps.api.services.qiepai.marketplace.seed`` lifespan-time
bootstrap.

Endpoints
=========

* ``GET    /marketplace/templates``                                — list (paginated)
* ``GET    /marketplace/templates/{id}``                           — single template (payload included)
* ``POST   /marketplace/templates``                                — create (admin)
* ``PATCH  /marketplace/templates/{id}``                           — partial update (owner)
* ``DELETE /marketplace/templates/{id}``                           — soft-delete (enabled = 0)
* ``POST   /marketplace/templates/{id}/ratings``                  — insert/replace rating + recompute aggregates
* ``GET    /marketplace/templates/{id}/copies``                   — list copy audit rows
* ``POST   /marketplace/templates/{id}/copy``                      — copy into a new (or supplied) employee

Mount path: prefix ``/qiepai`` (set in ``apps/api/routes/qiepai/__init__.py``)
+ parent prefix ``/api`` (set in ``apps/unified/main.py``) →
final URLs are ``/api/qiepai/marketplace/templates/...``.

Error model
===========

* ``TemplateValidationError``      → 422 (bad body, out-of-range rating)
* ``TemplateNotFoundError``        → 404 (unknown template id)
* ``TargetEmployeeNotFoundError``  → 404 (copy body references unknown employee)
* ``TemplateConflictError``        → 409 (reserved; currently unused by ❹ v1
  since rating re-rating is treated as upsert; left here so the route
  surface matches the service exception vocabulary)

The mapping lives in a single ``_http_error`` helper so the error
contract can evolve in one place.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.api.services.qiepai.marketplace import service

router = APIRouter(tags=["qiepai-marketplace"])


# ---------------------------------------------------------------------------
# 1. List marketplace templates
# ---------------------------------------------------------------------------


@router.get("/marketplace/templates")
async def list_marketplace_templates(
    enterprise_id: str | None = Query(
        default=None,
        description="企业空间 id;省略时使用默认占位 huilton_seed",
    ),
    category: str | None = Query(
        default=None,
        description="按 category 过滤;可选 customer_service / sales / finance / hr / ops",
    ),
    sort: str = Query(
        default="popular",
        description="排序;popular(默认)=rating+use_count, recent=created_at",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="分页大小;上限 200",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="分页偏移",
    ),
) -> dict[str, Any]:
    """marketplace 模板列表 — 分页 + category 过滤 + sort."""
    try:
        return await service.list_templates(
            enterprise_id=enterprise_id,
            category=category,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 2. Get a single template (payload included)
# ---------------------------------------------------------------------------


@router.get("/marketplace/templates/{template_id}")
async def get_marketplace_template(template_id: str) -> dict[str, Any]:
    """单条 marketplace 模板详情 — payload 完整返回."""
    try:
        return await service.get_template(template_id)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"template not found: {template_id}"
        ) from exc


# ---------------------------------------------------------------------------
# 3. Create a template (admin)
# ---------------------------------------------------------------------------


@router.post("/marketplace/templates", status_code=201)
async def create_marketplace_template(payload: dict[str, Any]) -> dict[str, Any]:
    """建 marketplace 模板 (admin) — 入参见 service.create_template.

    Body 必填 name / category / payload (dict);可选 description /
    industry / tags / source / enabled / created_by / enterprise_id.
    ``source='builtin'`` 在 body 中会被静默降级为 ``'user'`` 以避免 admin
    谎称自己是内置模板。
    """
    try:
        return await service.create_template(payload)
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 4. Patch a template (owner)
# ---------------------------------------------------------------------------


@router.patch("/marketplace/templates/{template_id}")
async def patch_marketplace_template(
    template_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """改 marketplace 模板 (owner) — name / description / category /
    industry / payload / tags / enabled.

    ``source`` / ``created_by`` / ``enterprise_id`` 不可改(避免 row-level
    权限绕过)。
    """
    try:
        return await service.patch_template(template_id, payload)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"template not found: {template_id}"
        ) from exc
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 5. Soft-delete a template (sets enabled = 0)
# ---------------------------------------------------------------------------


@router.delete("/marketplace/templates/{template_id}")
async def delete_marketplace_template(template_id: str) -> dict[str, Any]:
    """软删 marketplace 模板 — ``enabled = 0``,行不物理删除(用于审计)。

    Returns ``{"id": ..., "deleted": true, "enabled": false}`` 以便 UI
    立即反映状态,无需后续 GET。
    """
    try:
        row = await service.delete_template(template_id)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"template not found: {template_id}"
        ) from exc
    return {
        "id": row["id"],
        "deleted": True,
        "enabled": row.get("enabled", 0),
    }


# ---------------------------------------------------------------------------
# 6. Rate a template (1-5 + optional comment)
# ---------------------------------------------------------------------------


@router.post(
    "/marketplace/templates/{template_id}/ratings",
    status_code=201,
)
async def rate_marketplace_template(
    template_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """评分 marketplace 模板 — 入参 {rating: 1-5, user_id?, comment?}。

    Side effect: 同一个 (template_id, user_id) 对重新评分时,旧评分行被
    替换 (UNIQUE 约束 + INSERT OR REPLACE),并触发父模板 ``rating_avg`` /
    ``rating_count`` 同步重算。
    """
    try:
        return await service.rate_template(template_id, payload)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"template not found: {template_id}"
        ) from exc
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 7. List copy records for a template
# ---------------------------------------------------------------------------


@router.get("/marketplace/templates/{template_id}/copies")
async def list_marketplace_copies(template_id: str) -> dict[str, Any]:
    """模板复制记录列表 (newest first) — 用于审计 + use_count 对账。"""
    try:
        return await service.list_copies(template_id)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"template not found: {template_id}"
        ) from exc


# ---------------------------------------------------------------------------
# 8. Copy a template into a (new or supplied) digital employee
# ---------------------------------------------------------------------------


@router.post("/marketplace/templates/{template_id}/copy", status_code=201)
async def copy_marketplace_template(
    template_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """复制模板 → 创建员工 + revision — 最重要的流程 (spec ❹ section 6)。

    Body 可选字段:
      * ``target_employee_id`` — 指定目标员工(已存在);省略时自动建员工。
      * ``copied_by`` — 审计用 user_id。
      * ``display_name`` / ``role`` — 自动建员工时的覆盖(默认
        ``"{template.name} (副本)"`` / ``"数字员工"``)。

    Returns ``{template_id, target_employee_id, revision_id, copy_id,
    employee, revision}``,前端可直接跳转到新员工详情。
    """
    try:
        return await service.copy_template(template_id, payload)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"template not found: {template_id}"
        ) from exc
    except service.TargetEmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]