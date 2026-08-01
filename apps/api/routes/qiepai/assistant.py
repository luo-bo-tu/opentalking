"""qiepai · assistant router (Phase ❷-1 stub, no business logic).

后续 ❷-5 阶段会接入: 右侧只读决策助手 (fact / inference / suggestion / unknown 分层).
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["qiepai-assistant"])


@router.get("/assistant/chat")
async def get_assistant_chat() -> dict[str, str]:
    """右侧决策助手会话 (Phase ❷-1 stub)."""
    return {"status": "stub", "module": "assistant"}
