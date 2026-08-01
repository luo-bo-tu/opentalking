"""qiepai · digital employees service layer (Phase ❷-6).

Backs ``apps/api/routes/qiepai/employees.py``. Owns:

* The lifecycle of ``employees`` rows (CRUD + persona 1:1 link check).
* The ``employee_revisions`` table (append-only revision history).
* The publish **state machine** — ``draft → configuring → ready → published``
  → ``suspended`` → ``retired`` — including the readiness gates
  (``readiness_p0 / p1`` + ``sync_state != error/drifted``) the spec calls
  out as hard constraints.

Modules
=======

* :mod:`.service` — CRUD + revisions + persona conflict check.
* :mod:`.state_machine` — pure functions for status transitions + readiness
  validation; no DB access so it can be unit-tested in isolation.

Cross-cutting conventions mirror ``decisions/service.py`` and
``tasks/service.py``: ``asyncio.to_thread`` for blocking DB calls, the
``PRAGMA foreign_keys = OFF`` forward-reference dance for the empty
``enterprise_spaces`` table in the single-tenant demo.
"""
from __future__ import annotations

from . import service, state_machine

__all__ = ["service", "state_machine"]
