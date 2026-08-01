"""qiepai · marketplace service layer (Phase ❹).

Backs ``apps/api/routes/qiepai/marketplace.py``. Owns the lifecycle of
``scene_templates`` + ``scene_template_ratings`` +
``scene_template_copies`` rows (CRUD + denormalised aggregates +
copy-into-employee flow).

Modules
=======

* :mod:`.service` — CRUD + ratings + copy business logic; the public
  surface the router calls into.
* :mod:`.seed` — lifespan-time builtin template bootstrap (3-5 fixed
  rows, ``source='builtin'``).

Conventions mirror :mod:`apps.api.services.qiepai.employees.service`
and :mod:`apps.api.services.qiepai.decisions.service`: ``asyncio.to_thread``
for blocking DB calls, ``PRAGMA foreign_keys = OFF`` forward-reference
dance for the placeholder ``enterprise_id``.
"""
from __future__ import annotations

from . import service, seed

__all__ = ["service", "seed"]