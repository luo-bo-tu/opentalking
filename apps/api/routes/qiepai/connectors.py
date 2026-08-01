"""qiepai · connectors router (Phase ❷-1 stub, no business logic).

后续 ❷-2 / ❷-3 阶段会接入: 数据连接器元数据 + 探活 + mock 资产加载.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["qiepai-connectors"])


@router.get("/connectors")
async def list_connectors() -> dict[str, str]:
    """数据连接器列表 (Phase ❷-1 stub)."""
    return {"status": "stub", "module": "connectors"}
