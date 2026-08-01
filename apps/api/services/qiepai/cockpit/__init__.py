"""qiepai · cockpit service layer (Phase ❷-4).

Houses the deterministic read logic that backs the 5 KPI cards and 4
chart endpoints in ``apps/api/routes/qiepai/cockpit.py``. The router is
intentionally a thin shim — every decision about which metric maps to
which card, how items are derived, and what counts as ``stale`` lives
here so the route layer stays declarative.

Why a separate package (not a flat module under ``services/qiepai/``)
=====================================================================

The cockpit surface is the first place in ❷-4 that needs both DB-side
state (canonical ``metric_snapshots.value``) and connector-side state
(``items`` payload for charts). Keeping all of that co-located in a
``cockpit/`` subpackage — instead of mixing into the existing flat
``connectors/`` / ``metrics/`` modules — preserves the layering
established in ❷-3 (loaders are connector-agnostic; this module is
cockpit-specific).
"""
from __future__ import annotations

from .service import KPI_ORDER, CARD_FORMATS, get_chart, list_kpis

__all__ = ["KPI_ORDER", "CARD_FORMATS", "list_kpis", "get_chart"]