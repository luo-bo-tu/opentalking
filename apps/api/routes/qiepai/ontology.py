"""qiepai · ontology router (Phase ❷-1 stub, no business logic).

后续 ❷-2 / ❷-3 阶段会接入: 本体类型/关系/属性.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["qiepai-ontology"])


@router.get("/ontology/types")
async def list_ontology_types() -> dict[str, str]:
    """本体类型列表 (Phase ❷-1 stub)."""
    return {"status": "stub", "module": "ontology"}
