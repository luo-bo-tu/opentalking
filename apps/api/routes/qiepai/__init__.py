"""qiepai business layer · aggregate router (Phase ❷-1 stub).

This package holds the 7 P0-D domain routers (老板驾驶舱 / 决策中心 / 业务任务 /
数字员工 / 数据连接器 / 本体 / 指标) plus the 右侧决策助手 router. In Phase
❷-1 every file is a stub — the route paths and `module` tag are fixed so
后续 ❷-2 ~ ❷-6 阶段可以在不破坏客户端的前提下逐个接真业务。

The aggregate `router` carries `prefix="/qiepai"` and is mounted under
`/api` by the host application, yielding final URLs like
`/api/qiepai/cockpit/kpis`. Do not add business logic here.
"""
from __future__ import annotations

from fastapi import APIRouter

from .assistant import router as assistant_router
from .cockpit import router as cockpit_router
from .connectors import router as connectors_router
from .decisions import router as decisions_router
from .employees import router as employees_router
from .integrations import feishu_router as feishu_router_routes
from .marketplace import router as marketplace_router
from .metrics import router as metrics_router
from .ontology import router as ontology_router
from .outbox_events import router as outbox_router_routes
from .tasks import router as tasks_router

router = APIRouter(prefix="/qiepai")
router.include_router(cockpit_router)
router.include_router(connectors_router)
router.include_router(decisions_router)
router.include_router(employees_router)
router.include_router(metrics_router)
router.include_router(assistant_router)
router.include_router(ontology_router)
router.include_router(tasks_router)
router.include_router(feishu_router_routes.router)
router.include_router(outbox_router_routes)
# Phase ❹: scene-template marketplace (8 endpoints). Mounted last so the
# router order stays stable for downstream clients pinning a particular
# order (the FastAPI router is order-independent for routing, but the
# OpenAPI schema lists routes in include_router order).
router.include_router(marketplace_router)

__all__ = ["router"]
