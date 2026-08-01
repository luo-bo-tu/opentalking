"""qiepai · cockpit router (Phase ❷-4: real business logic).

Upgrades the ❷-1 stub (``/cockpit/kpis`` returned a hard-coded
``{"status": "stub", ...}`` dict) to five real endpoints backed by
``apps.api.services.qiepai.cockpit.service``. The original stub was the
only thing in this file; it has been replaced end-to-end.

Endpoints
=========

* ``GET /cockpit/kpis``                      — 5 KPI cards
* ``GET /cockpit/charts/sales-trend``         — 12-month revenue line
* ``GET /cockpit/charts/customer-concentration`` — Top 5 share pie
* ``GET /cockpit/charts/orders-ar``           — 12-month stacked bar
* ``GET /cockpit/charts/target-attainment``   — 4-quarter progress bars

All responses are ``dict[str, Any]``. Pydantic models are deliberately
not used here for ❷-4 (the loader already returns a dict shape, the
frontend renders against TS interfaces, and the ❷-1 schema package is
a placeholder — introducing typed response models now would balloon
the diff without unlocking any new behaviour). ❷-5 / ❷-6 can introduce
Pydantic for their respective domains without touching this file.

Mount path: prefix ``/qiepai`` (set in ``apps/api/routes/qiepai/__init__.py``)
+ parent prefix ``/api`` (set in ``apps/unified/main.py``) →
final URLs are ``/api/qiepai/cockpit/...``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.services.qiepai.cockpit import service

router = APIRouter(tags=["qiepai-cockpit"])


@router.get("/cockpit/kpis")
async def get_cockpit_kpis() -> dict[str, Any]:
    """老板驾驶舱 KPI 总览 — 5 张卡片."""
    return await service.list_kpis()


@router.get("/cockpit/charts/sales-trend")
async def get_sales_trend_chart() -> dict[str, Any]:
    """销售趋势 (近 12 月) — 折线图数据."""
    return await service.get_chart("sales-trend")


@router.get("/cockpit/charts/customer-concentration")
async def get_customer_concentration_chart() -> dict[str, Any]:
    """客户集中度 (Top 5) — 饼图数据."""
    return await service.get_chart("customer-concentration")


@router.get("/cockpit/charts/orders-ar")
async def get_orders_ar_chart() -> dict[str, Any]:
    """订单 / 应收结构 (近 12 月) — 堆叠柱图数据."""
    return await service.get_chart("orders-ar")


@router.get("/cockpit/charts/target-attainment")
async def get_target_attainment_chart() -> dict[str, Any]:
    """目标达成 (按季度) — 进度条数据."""
    return await service.get_chart("target-attainment")