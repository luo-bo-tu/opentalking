"""qiepai · metrics router (Phase ❷-1 stub, no business logic).

后续 ❷-2 / ❷-3 阶段会接入: 指标定义 + 快照 + freshness/source 标签.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["qiepai-metrics"])


@router.get("/metrics")
async def list_metrics() -> dict[str, str]:
    """指标定义列表 (Phase ❷-1 stub)."""
    return {"status": "stub", "module": "metrics"}
