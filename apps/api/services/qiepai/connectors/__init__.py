"""qiepai · connector layer (Phase ❷-3).

Public surface:

- :class:`FileConnector` — file-backed mock connector (sync inside, async outside).
- :func:`get_connector` — registry factory keyed by metric id.
- :data:`MOCK_CONNECTORS` — path map (read-only).
- :class:`UnknownConnectorError` — narrow ``KeyError`` subclass.

No business logic lives here. Adding a new connector type in ❷-4+ (e.g.
``SqlServerConnector``) means a new module under this package + a new
factory branch in ``get_connector`` — the loader contract (``read`` +
``probe``) stays unchanged.
"""
from __future__ import annotations

from .file_connector import FileConnector
from .registry import MOCK_CONNECTORS, UnknownConnectorError, get_connector

__all__ = [
    "FileConnector",
    "MOCK_CONNECTORS",
    "UnknownConnectorError",
    "get_connector",
]
