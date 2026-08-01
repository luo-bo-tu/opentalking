"""qiepai · cockpit read service (Phase ❷-4).

Two public coroutines back the five ``/api/qiepai/cockpit/*`` endpoints:

- :func:`list_kpis` — assemble the 5 KPI cards displayed at the top of
  the cockpit dashboard. Reads ``metric_definitions`` + the matching
  ``metric_snapshots`` row from the enterprise DB; for cards that derive
  their headline number from the mock JSON's ``items`` field, also calls
  :func:`load_kpi_snapshot` to fetch the current items payload.
- :func:`get_chart` — fetch chart-ready ``items`` for a single metric.
  Always reads fresh from the connector (not from the DB) because
  ``metric_snapshots.items`` is not a stored column by design (❷-3
  documented "snapshot reflects first-boot content"; the cockpit wants
  live mock data on every dashboard load).

Three-state contract (架构 § 21.1)
==================================

This module returns raw fields (``value``, ``freshness_seconds``,
``source``) and a derived boolean ``is_stale``. The route layer and the
frontend split the rendering rules:

* ``value is None``                       → UI renders "数据暂不可用"
* ``is_stale is True`` (freshness > 86400) → UI renders "过期" badge
* ``source`` is always present when the snapshot row exists, so the UI
  can show "mock://financial-kpi/v1" verbatim (spec § 0 拿不准点 #5:
  mock sources must be visible, never silently substituted with a fake).

The threshold ``_STALE_THRESHOLD_S = 86400`` (one day) is also the value
used in the loader docstring for the same purpose; keeping one constant
in this module and referencing the loader's docs avoids drift.

Why ``asyncio.to_thread`` around the DB read
============================================

``apps/api/services/qiepai/db.connect`` is synchronous (stdlib
``sqlite3``). FastAPI's event loop must not block on a long DB call; the
project convention (established in ❷-2 ``migration_runner`` and ❷-3
``seed._seed_sync``) is to wrap every blocking DB touch in
``asyncio.to_thread``. The chart path goes through the loader, which
already does the wrapping internally.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from .. import db
from ..metrics import load_kpi_snapshot

log = logging.getLogger(__name__)

#: Canonical 5-card layout (❷-4 decision 2026-07-31 by 大总管). Order is
#: the order the cards render in the cockpit grid. Adding a new KPI to
#: the dashboard means appending to this tuple AND extending the seed
#: step (❷-3) AND extending the connector registry (❷-3).
KPI_ORDER: Final[tuple[str, ...]] = (
    "financial-kpi",
    "sales-trend",
    "customer-concentration",
    "orders-ar",
    "target-attainment",
)

#: Card-level display format hint. Lives here (not in the DB) because
#: the DB's ``metric_definitions.display_format`` describes the chart
#: family ("stacked_bar", "pie", ...) whereas this constant describes
#: how the *KPI card number* should be formatted (currency vs percent
#: vs ratio). They overlap but are not identical — e.g. orders-ar's
#: chart is "stacked_bar" while its KPI card is a "ratio".
#:
#: Recognised values (see ``apps/web/src/qiepai/cockpit/KpiCard.tsx``):
#:   - ``currency_cny``    →  "X.XX 万元 / 亿元"
#:   - ``percent_0_100``   →  "X.X%"     (value already in 0-100)
#:   - ``percent_0_1``     →  "X.X%"     (value in 0-1; multiplies by 100)
#:   - ``ratio_decimal``   →  "X.XX"     (orders / ar_outstanding, dimensionless)
CARD_FORMATS: Final[dict[str, str]] = {
    "financial-kpi": "currency_cny",
    "sales-trend": "currency_cny",
    "customer-concentration": "percent_0_100",
    "orders-ar": "ratio_decimal",
    "target-attainment": "percent_0_1",
}

#: Metric ids whose KPI card headline value is derived from the
#: connector's ``items`` payload (rather than the DB's top-level
#: ``metric_snapshots.value``). Cards NOT in this tuple (currently only
#: ``target-attainment``) fall back to the DB snapshot value, which is
#: already the canonical overall figure.
_ITEMS_DERIVED_METRICS: Final[frozenset[str]] = frozenset(
    {"financial-kpi", "sales-trend", "customer-concentration", "orders-ar"}
)

#: Freshness threshold (seconds) above which the UI tags a KPI as
#: "过期". Matches the threshold cited in the loader docstring (❷-3).
_STALE_THRESHOLD_S: Final[int] = 86400


def _read_kpi_rows_sync(scope: str) -> list[dict[str, Any]]:
    """Read metric_definitions LEFT JOIN metric_snapshots, scoped.

    Returns rows ordered by :data:`KPI_ORDER`. The join is ``LEFT`` so a
    missing snapshot row still produces a definition entry — the KPI
    card then renders ``value=None`` and the UI shows "数据暂不可用"
    instead of silently dropping the card.

    The ``ORDER BY`` uses ``CASE`` to honour ``KPI_ORDER`` (the dict
    doesn't carry an intrinsic order in SQLite). ``CASE`` keeps the
    ordering in lock-step with the canonical tuple without needing a
    second SELECT to sort client-side.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in KPI_ORDER)
        order_case = " ".join(
            f"WHEN md.id = ? THEN {idx}" for idx in range(len(KPI_ORDER))
        )
        sql = (
            "SELECT "
            "  md.id, md.name, md.display_unit, md.display_format, "
            "  md.source AS def_source, "
            "  ms.scope, ms.as_of, ms.freshness_seconds, ms.value, "
            "  ms.source AS snap_source "
            "FROM metric_definitions md "
            "LEFT JOIN metric_snapshots ms "
            "  ON md.id = ms.metric_id AND ms.scope = ? "
            f"WHERE md.id IN ({placeholders}) "
            f"ORDER BY CASE {order_case} END"
        )
        params: tuple[Any, ...] = (scope, *KPI_ORDER, *KPI_ORDER)
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _derive_card_value(
    metric_id: str, items: list[dict[str, Any]] | None
) -> tuple[Any, str | None]:
    """Compute the KPI card's headline value + Chinese label from ``items``.

    Returns ``(value, value_label)``. ``value`` is the number rendered
    in big text; ``value_label`` is a short sub-line under the KPI name
    that tells the operator *which* slice of ``items`` the value came
    from (e.g. "本年累计净利", "Top 1 客户 华信重工").

    All values come from real items in the mock JSON — no fabrication.
    If ``items`` is ``None`` (loader failed, missing snapshot), the
    tuple is ``(None, None)`` and the UI shows "数据暂不可用".

    This function is deliberately pure — no DB IO, no logging — so the
    caller can run it inside ``asyncio.to_thread`` if it grows heavier.
    """
    if items is None:
        return None, None

    if metric_id == "financial-kpi":
        for item in items:
            if item.get("name") == "net_profit_ytd":
                return item.get("value"), item.get("label")
        # The mock JSON guarantees a net_profit_ytd entry today, but if
        # a future mock drops it, fall back to "数据暂不可用" rather than
        # silently showing the gross profit (which would be a fake).
        return None, "本年累计净利"

    if metric_id == "sales-trend":
        if not items:
            return None, None
        last = items[-1]
        month = last.get("month") or ""
        return last.get("revenue"), f"最近月 {month} 营收"

    if metric_id == "customer-concentration":
        if not items:
            return None, None
        top = items[0]
        name = top.get("customer") or ""
        return top.get("share_pct"), f"Top 1 客户 {name}"

    if metric_id == "orders-ar":
        if not items:
            return None, None
        last = items[-1]
        orders = last.get("orders")
        ar = last.get("ar_outstanding")
        if orders is None or ar is None or ar == 0:
            return None, "订单 / 应收 比值"
        # orders / ar_outstanding → "AR turnover-ish" indicator:
        # larger value = orders dwarf AR = healthier cash collection.
        return orders / ar, f"最近月 {last.get('month', '')} 订单 / 应收"

    # Should not reach here — guarded by caller.
    return None, None


async def list_kpis(scope: str = "default") -> dict[str, Any]:
    """Assemble the 5-card KPI grid for the cockpit dashboard.

    Response shape::

        {
          "kpis": [
            {
              "id":              "financial-kpi",
              "name":            "财务 KPI 总览",
              "value":           612840.0,    # number | None
              "value_label":     "本年累计净利",
              "unit":            "CNY",       # from metric_definitions.display_unit
              "card_format":     "currency_cny",
              "trend":           null,        # always null in ❷-4 (no trend math)
              "source":          "mock://financial-kpi/v1",
              "as_of":           "2026-07-31T09:00:00+00:00",
              "freshness_seconds": 3600,
              "is_stale":        false        # freshness > 86400
            },
            ...
          ]
        }

    The 4 ``items``-derived cards are read concurrently via
    ``asyncio.gather`` so a slow connector on one metric doesn't stall
    the whole cockpit load. ``target-attainment`` skips the loader
    entirely (its DB ``value`` field already carries the headline
    number 0.78).
    """
    rows = await asyncio.to_thread(_read_kpi_rows_sync, scope)

    # Concurrent load for the 4 cards that need items.
    items_results = await asyncio.gather(
        *(load_kpi_snapshot(mid, scope=scope) for mid in KPI_ORDER if mid in _ITEMS_DERIVED_METRICS),
        return_exceptions=False,
    )
    items_map: dict[str, list[dict[str, Any]] | None] = {}
    for mid, snap in zip(
        (mid for mid in KPI_ORDER if mid in _ITEMS_DERIVED_METRICS),
        items_results,
    ):
        if isinstance(snap, dict) and isinstance(snap.get("items"), list):
            items_map[mid] = snap["items"]
        else:
            items_map[mid] = None

    kpis: list[dict[str, Any]] = []
    for row in rows:
        metric_id = row["id"]
        snap_value = row["value"]
        snap_source = row["snap_source"] or row["def_source"]
        as_of = row["as_of"]
        freshness = int(row["freshness_seconds"]) if row["freshness_seconds"] is not None else 0

        if metric_id in _ITEMS_DERIVED_METRICS:
            display_value, value_label = _derive_card_value(metric_id, items_map.get(metric_id))
        else:
            # target-attainment: DB value IS the headline (0.78).
            display_value = snap_value
            value_label = "整体达成率"

        kpis.append(
            {
                "id": metric_id,
                "name": row["name"],
                "value": display_value,
                "value_label": value_label,
                "unit": row["display_unit"] or "",
                "card_format": CARD_FORMATS[metric_id],
                "trend": None,
                "source": snap_source,
                "as_of": as_of,
                "freshness_seconds": freshness,
                "is_stale": freshness > _STALE_THRESHOLD_S,
            }
        )
    return {"kpis": kpis}


async def get_chart(metric_id: str) -> dict[str, Any]:
    """Return chart-ready payload for ``metric_id``.

    Reads items **fresh from the connector** every call. The DB snapshot
    intentionally does not store ``items`` (the column doesn't exist on
    ``metric_snapshots``); storing it would mean a ❷-3 seed-time copy
    that the operator might forget to refresh when the mock JSON
    changes. For the cockpit dashboard "show me what's there right now"
    is the right semantics.

    Response shape::

        {
          "metric_id":        "sales-trend",
          "items":            [...],         # list[dict] | None
          "source":           "mock://sales-trend/v1",
          "as_of":            "2026-07-31T09:00:00+00:00",
          "freshness_seconds": 7200
        }

    Returns ``items=None`` when the loader reports unavailable (route
    callers should treat that as "暂不可用", not as an error).
    """
    snapshot = await load_kpi_snapshot(metric_id, scope="default")
    if snapshot is None:
        return {
            "metric_id": metric_id,
            "items": None,
            "source": None,
            "as_of": None,
            "freshness_seconds": None,
        }
    items_value = snapshot.get("items")
    return {
        "metric_id": metric_id,
        "items": items_value if isinstance(items_value, list) else None,
        "source": snapshot.get("source"),
        "as_of": snapshot.get("as_of"),
        "freshness_seconds": snapshot.get("freshness_seconds"),
    }


__all__ = [
    "KPI_ORDER",
    "CARD_FORMATS",
    "list_kpis",
    "get_chart",
]