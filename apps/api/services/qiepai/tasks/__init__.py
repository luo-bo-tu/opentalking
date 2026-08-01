"""qiepai · business tasks service layer (Phase ❷-6).

Backs ``apps/api/routes/qiepai/tasks.py``. Owns the lifecycle of
``business_tasks`` rows: list / get / create / patch / soft-delete.

Status state machine (架构 v1.1 § 21.5 — hard constraints)
==========================================================

* ``todo``         → ``in_progress`` / ``cancelled`` / ``done``
* ``in_progress``  → ``done`` / ``cancelled``
* ``done``         → (terminal — no further status transitions allowed;
  description / assignee remain editable for post-hoc annotation)
* ``cancelled``    → (terminal — same exemption as ``done``)

See ``service.py`` for the exact transition table + validation rules.

Cross-cutting conventions (mirrors ``decisions/service.py`` ❷-5)
================================================================

* Every public coroutine that touches the DB wraps the blocking
  ``sqlite3`` call in :func:`asyncio.to_thread`.
* Read connections are short-lived (``connect → execute → close``).
* Writes open an explicit transaction via ``conn.commit()``.
* The placeholder ``enterprise_id`` ("huilton_seed") used here matches
  ``apps/api/services/qiepai/decisions/service.py``; we relax
  ``PRAGMA foreign_keys`` inside the write transaction because the
  forward-referenced ``enterprise_spaces`` row is intentionally absent
  in the single-tenant demo (拿不准点 #1, spec section 0).
"""
from __future__ import annotations

from . import service

__all__ = ["service"]
