"""qiepai · mock AI suggester (Phase ❷-5).

Returns a templated 4-layer response without making any LLM call. Selected
by :mod:`ai_suggester` when no OpenClaw gateway token is configured (i.e.
the project is running in pure demo / CI mode). The templates pivot on
``metric_id`` so different decision cards visually feel different even
though every field is hardcoded — the spec requires "varied enough that
the frontend doesn't show the same blob for every decision item".

Templates per metric
====================

For every metric we emit at most one ``fact`` row referencing the real
``metric_snapshots.value`` when present, plus one ``inference``, one
``suggestion`` and one ``unknown`` row. The frames are deliberately
terse so a future real LLM response swaps in cleanly with the same
shape.

Caching contract
================

The mock layer does NOT call out to anywhere, so caching behaviour is
trivially identical to a real call: the caller (see ``ai_suggester``)
writes the result's ``fact`` + ``inference`` rows back to
``decision_items.ai_suggestion`` and returns the full 4-layer dict to
the caller. See ``service.py`` for the persistence step.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


#: Per-metric templates. ``fact_label`` + ``fact_source`` are picked up
#: from real ``metric_snapshot`` rows when available, but the
#: ``inference`` / ``suggestion`` / ``unknown`` strings are hardcoded.
#: Keeping them per-metric (rather than one generic blob) gives the
#: frontend a reason to render slightly different cards per row.
_TEMPLATES: dict[str, dict[str, Any]] = {
    "financial-kpi": {
        "fact_label": "本年累计净利",
        "inference": "本年累计净利低于营收增速的一半,盈利能力承压",
        "confidence": 0.72,
        "suggestion": "复核毛利率与三项费用率,识别压缩空间",
        "owner_suggestion": "财务总监",
        "unknown": "需要补充: 行业基准毛利率对照、过去 12 月趋势",
    },
    "sales-trend": {
        "fact_label": "最近月营收",
        "inference": "近 3 月订单 / 营收呈温和上行,未达全年目标进度",
        "confidence": 0.65,
        "suggestion": "盘点在手订单交付节奏,锁定 Q3 加速节点",
        "owner_suggestion": "销售 VP",
        "unknown": "需要补充: 大客户回款确认单、行业景气指数",
    },
    "customer-concentration": {
        "fact_label": "Top 1 客户占比",
        "inference": "Top 1 占比偏高, 集中度风险显著",
        "confidence": 0.81,
        "suggestion": "推动腰部客户拓新, 设定 Top 1 占比上限",
        "owner_suggestion": "销售 VP",
        "unknown": "需要补充: 行业客户集中度基准、近三年变化",
    },
    "orders-ar": {
        "fact_label": "订单 / 应收 比值",
        "inference": "近期订单 / 应收比 4.34, 优于去年同期",
        "confidence": 0.70,
        "suggestion": "保持回款节奏, 关注 AR 账龄结构",
        "owner_suggestion": "财务总监",
        "unknown": "需要补充: 长账龄应收占比、信用政策",
    },
    "target-attainment": {
        "fact_label": "整体达成率",
        "inference": "整体达成率未达年中节点, 缺口集中在销售线",
        "confidence": 0.68,
        "suggestion": "分解缺口到部门 KPI, 季度复盘机制触发",
        "owner_suggestion": "总经理",
        "unknown": "需要补充: 各部门细分达成进度的明细数据",
    },
}

#: Fallback when ``metric_id`` is not in ``_TEMPLATES`` (e.g. a future
#: metric added without extending this map). Keeps the contract for the
#: frontend intact: always 4 layers, always one row each.
_DEFAULT_TEMPLATE: dict[str, Any] = {
    "fact_label": "指标当前值",
    "inference": "数据快照显示存在值得关注的异常",
    "confidence": 0.5,
    "suggestion": "复核相关业务线, 设定下一步动作",
    "owner_suggestion": "业务负责人",
    "unknown": "需要补充: 指标的时序数据与基准",
}


def _pick_template(metric_id: str | None) -> dict[str, Any]:
    if not metric_id:
        return _DEFAULT_TEMPLATE
    return _TEMPLATES.get(metric_id, _DEFAULT_TEMPLATE)


def build_mock_suggestion(
    *,
    fact_snapshot: dict[str, Any],
    decision_title: str,
    metric_id: str | None,
) -> dict[str, Any]:
    """Build a mock 4-layer suggestion payload.

    Parameters
    ----------
    fact_snapshot:
        The ``decision_items.fact_snapshot`` JSON (as parsed back into a
        dict by the caller). Only the ``fact[]`` row uses fields from
        here (``label`` + ``value`` + ``source``); the inference,
        suggestion and unknown rows come from the per-metric template.
    decision_title:
        Current decision title. Logged so an operator can confirm the
        mock was picked deliberately (rather than a silent fallback
        to OpenClaw that did nothing).
    metric_id:
        Drives template selection. ``None`` uses the default template.
    """
    template = _pick_template(metric_id)
    log.debug("mock_suggester: building 4-layer for %r (metric=%r)", decision_title, metric_id)

    # ---- fact: pull from real fact_snapshot when present, else generic
    fact_rows: list[dict[str, Any]] = []
    snapshot_items = fact_snapshot.get("items") if isinstance(fact_snapshot, dict) else None
    if isinstance(snapshot_items, list) and snapshot_items:
        for item in snapshot_items[:4]:
            if not isinstance(item, dict):
                continue
            label = item.get("label") or item.get("name") or template["fact_label"]
            value = item.get("value")
            source = item.get("source") or fact_snapshot.get("source") or "mock://unknown/v1"
            fact_rows.append({"label": str(label), "value": value, "source": str(source)})
    if not fact_rows:
        # fact_snapshot empty / unparseable — single fallback row so the
        # 4-layer contract still ships exactly one fact item.
        fact_rows.append(
            {
                "label": str(template["fact_label"]),
                "value": fact_snapshot.get("value") if isinstance(fact_snapshot, dict) else None,
                "source": "mock://decision-fallback/v1",
            }
        )

    return {
        "fact": fact_rows,
        "inference": [
            {
                "text": str(template["inference"]),
                "confidence": float(template["confidence"]),
            }
        ],
        "suggestion": [
            {
                "text": str(template["suggestion"]),
                "owner_suggestion": str(template["owner_suggestion"]),
            }
        ],
        "unknown": [
            {"text": str(template["unknown"])},
        ],
    }


__all__ = ["build_mock_suggestion"]
