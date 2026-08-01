"""qiepai · file-backed mock connector (Phase ❷-3).

Phase ❷-3 ships five hand-authored mock JSON assets under
``data/qiepai-mock/*.json`` (one per KPI / chart). The connector layer wraps
each file behind a uniform async interface so the loader (and downstream
cockpit endpoints in ❷-4) treats them identically to future real backends
(``sql_server``, ``rest``, ...).

Design notes
============

* **Sync stdlib inside, async outside.** Mirrors the convention set by
  ``apps.api.services.qiepai.db`` and the OpenTalking ``voice_store`` /
  ``memory_store`` helpers: every blocking call uses stdlib
  ``sqlite3`` / ``json`` / ``Path``; the public ``read`` / ``probe``
  coroutines wrap that work in ``asyncio.to_thread`` so the FastAPI
  event loop is never stalled during initial seed or dashboard requests.

* **No third-party deps.** ``aiofiles`` is *not* installed in the project
  venv, so we deliberately avoid it. ``asyncio.to_thread`` (stdlib since
  3.9) is sufficient for the small mock JSONs and matches the pattern
  already used by ``migration_runner.run_pending_migrations``.

* **Probe != Read.** ``probe()`` answers "is the file reachable and
  parseable as JSON right now?" cheaply (re-uses the read path's parse).
  ``read()`` returns the parsed payload and raises on hard failure.
  Probe records ``last_probe_at`` so the three-state rendering contract
  (ok / stale / unavailable / error) can be evaluated from the data
  store later in ❷-4.

* **State semantics.** ``probe()['state']`` returns one of:
    - ``"ok"``       — file exists, readable, JSON parsed cleanly
    - ``"error"``    — file missing, permission denied, or JSON malformed
    - ``"timeout"``  — IO took longer than ``_PROBE_TIMEOUT_S`` seconds
  ``"timeout"`` is reserved for future use (e.g. network-backed connectors);
  the file connector currently never returns it because ``Path.read_*`` is
  non-blocking on macOS for sub-megabyte files. The slot exists so
  ``state`` stays a stable 3-value enum for downstream consumers.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: Probe timeout (seconds). File IO on local SSD is essentially instant, but
#: keeping a positive upper bound means a future swap to e.g. ``http://``
#: backed connectors inherits the same envelope.
_PROBE_TIMEOUT_S: Final[float] = 5.0


class FileConnector:
    """Read a single mock JSON asset on disk.

    The connector is **stateful** in exactly one way: ``last_probe_at`` is
    updated on every ``probe()`` call so business code (cockpit UI in ❷-4)
    can decide whether to flag the source as ``stale`` based on how long
    ago the last successful probe happened, independent of the payload's
    own ``freshness_seconds`` field.

    Instances are intentionally cheap — one per file — and the registry
    (``registry.py``) is the canonical owner. Do not construct ad-hoc
    inside request handlers.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        # ``last_probe_at`` is None until the first probe() call. It is a
        # plain attribute (not a property) because writes are intra-class
        # only and we want callers to read it freely.
        self.last_probe_at: _dt.datetime | None = None

    @property
    def path(self) -> Path:
        """Absolute path to the JSON asset (read-only)."""
        return self._path

    # ------------------------------------------------------------------ sync

    def _read_sync(self) -> dict[str, Any]:
        """Blocking read + parse. Raises on hard failure.

        Uses ``encoding="utf-8"`` explicitly so the venv default encoding
        does not silently mangle non-ASCII customer names in the mock data.
        """
        with self._path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        if not isinstance(payload, dict):
            raise ValueError(
                f"FileConnector {self._path}: top-level must be a JSON object, "
                f"got {type(payload).__name__}"
            )
        return payload

    def _probe_sync(self) -> dict[str, str]:
        """Synchronous probe — see class docstring for state semantics.

        Updates ``last_probe_at`` to the UTC moment of the probe (whether
        the probe succeeded or failed). This is intentional: the UI in ❷-4
        needs to display "上次探活时间" regardless of outcome so operators
        can tell whether the failure is fresh or stale.
        """
        probe_at = _dt.datetime.now(tz=_dt.timezone.utc)
        try:
            self._read_sync()
        except FileNotFoundError as exc:
            self.last_probe_at = probe_at
            return {"state": "error", "detail": f"missing: {exc}"}
        except PermissionError as exc:
            self.last_probe_at = probe_at
            return {"state": "error", "detail": f"permission: {exc}"}
        except json.JSONDecodeError as exc:
            self.last_probe_at = probe_at
            return {"state": "error", "detail": f"json_decode: {exc.msg} (line {exc.lineno})"}
        except ValueError as exc:
            self.last_probe_at = probe_at
            return {"state": "error", "detail": str(exc)}
        except OSError as exc:
            self.last_probe_at = probe_at
            return {"state": "error", "detail": f"os_error: {exc}"}
        self.last_probe_at = probe_at
        return {"state": "ok", "detail": "read_ok"}

    # ----------------------------------------------------------------- async

    async def read(self) -> dict[str, Any]:
        """Async read — returns the parsed JSON payload.

        Raises on hard failure (propagates whatever ``_read_sync`` raises).
        Callers (loader) decide whether to treat the exception as
        unavailable or escalate to the route layer.
        """
        return await asyncio.to_thread(self._read_sync)

    async def probe(self) -> dict[str, str]:
        """Async probe — returns ``{state, detail}`` and updates ``last_probe_at``.

        Currently the file connector cannot produce ``state == "timeout"``
        because ``Path.read_text`` is fast and non-blocking for the mock
        asset sizes (each JSON is <2 KB). The timeout state is reserved
        in the contract so future network-backed connectors can share the
        same ``state`` enum with the UI.

        Wraps the sync probe in ``asyncio.wait_for`` so that if a future
        connector implementation swaps in a slow IO primitive (e.g. an
        HTTP fetch), the event loop is still bounded.
        """
        async def _runner() -> dict[str, str]:
            return await asyncio.to_thread(self._probe_sync)

        try:
            return await asyncio.wait_for(_runner(), timeout=_PROBE_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("FileConnector %s probe timed out after %.1fs", self._path, _PROBE_TIMEOUT_S)
            return {
                "state": "timeout",
                "detail": f"probe exceeded {_PROBE_TIMEOUT_S:.1f}s budget",
            }


__all__ = ["FileConnector"]
