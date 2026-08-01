"""qiepai · mock connector registry (Phase ❷-3).

Single source of truth for "which mock JSON asset backs which KPI". The
registry is intentionally a *path-as-key* ``dict[str, Path]`` — the key is
the metric identifier (matches the JSON filename stem and the eventual
``metric_definitions.id`` row inserted by ``seed_initial_metrics``), the
value is the absolute ``Path`` to the JSON asset on disk.

Why path-as-key (not ``dict[str, FileConnector]``)? Because the factory
``get_connector`` constructs ``FileConnector`` instances on demand. This
keeps the registry picklable / serializable (handy for future test
fixtures) and avoids the registry owning process-local state.

Path resolution
===============

All paths are anchored at the **repository root** — resolved once at
import time via ``Path(__file__).resolve().parents[4]`` — so the registry
works regardless of the current working directory at process start.
Cwd-relative paths would silently break when uvicorn is launched from a
different directory (a recurring foot-gun in this project; see the
``OPENTALKING_UNIFIED_*`` env-var convention in ``apps/unified/main.py``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Final

from .file_connector import FileConnector

#: Absolute repository root — derived once, used for every mock asset.
#: Path layout: ``.../qiepai/apps/api/services/qiepai/connectors/registry.py``,
#: so ``parents[5]`` is the repo root (``.../qiepai/``).
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]

#: Five mock JSON assets shipped with Phase ❷-3. The key string is the
#: canonical metric id and is used as ``metric_definitions.id`` by the
#: seed step; ``loader.load_kpi_snapshot`` keys into the same map.
#:
#: Adding a new mock in ❷-3+? Add it here AND add a seed row in
#: ``seed._METRIC_DEFS`` so the registry and the DB stay in sync.
MOCK_CONNECTORS: Final[dict[str, Path]] = {
    "financial-kpi": _REPO_ROOT / "data" / "qiepai-mock" / "financial-kpi.json",
    "sales-trend": _REPO_ROOT / "data" / "qiepai-mock" / "sales-trend.json",
    "customer-concentration": _REPO_ROOT / "data" / "qiepai-mock" / "customer-concentration.json",
    "orders-ar": _REPO_ROOT / "data" / "qiepai-mock" / "orders-ar.json",
    "target-attainment": _REPO_ROOT / "data" / "qiepai-mock" / "target-attainment.json",
}


class UnknownConnectorError(KeyError):
    """Raised when ``get_connector`` is asked for a metric id not in the registry.

    Subclasses ``KeyError`` so existing ``except KeyError`` callers keep
    working, but lets new callers narrow the catch without relying on
    string-matching the message.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        known = ", ".join(sorted(MOCK_CONNECTORS)) or "(none)"
        return f"unknown mock connector {self.name!r}; known: [{known}]"


def get_connector(name: str) -> FileConnector:
    """Factory: return a fresh ``FileConnector`` for ``name``.

    A new instance per call is intentional. ``FileConnector`` is cheap
    (no IO at construction) and ``last_probe_at`` mutates per-instance —
    the loader wants independent probe timestamps per request, not
    accidentally shared state.
    """
    path = MOCK_CONNECTORS.get(name)
    if path is None:
        raise UnknownConnectorError(name)
    return FileConnector(path)


__all__ = ["MOCK_CONNECTORS", "UnknownConnectorError", "get_connector"]
