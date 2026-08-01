"""qiepai · metrics layer (Phase ❷-3).

Public surface:

- :func:`load_kpi_snapshot` — async loader that returns a normalised
  four-key dict (``value``, ``as_of``, ``freshness_seconds``, ``source``)
  or ``None`` when the metric is unavailable.

The loader hides the connector abstraction so cockpit routes (❷-4) and
the seed step (this phase) talk to one stable function.
"""
from __future__ import annotations

from .loader import load_kpi_snapshot

__all__ = ["load_kpi_snapshot"]
