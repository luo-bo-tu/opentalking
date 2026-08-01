"""qiepai · integrations package (Phase ❸-1).

Backs ``apps/api/routes/qiepai/integrations/*``. Owns:

* :mod:`.feishu_settings` — typed config singleton (``QIEPAI_FEISHU_*``
  env vars) the Feishu publisher reads at every call. Kept out of the
  OpenClaw settings module so the qiepai half of the codebase can
  rotate creds without touching the broader platform.
* :mod:`.registry` — minimal SQLite-backed ``feishu_groups`` table
  storing the chat_id list the publisher fans out to. Read by the
  worker to pick a destination; written by
  ``POST /api/qiepai/integrations/feishu/groups``.
* :mod:`.feishu_router` — three endpoints:

  * ``GET    /api/qiepai/integrations/feishu/groups``
  * ``POST   /api/qiepai/integrations/feishu/groups``
  * ``POST   /api/qiepai/integrations/feishu/test``

  All three return JSON; ``POST .../test`` short-circuits to the
  publisher's dry-run branch so the operator can verify the Feishu
  configuration end-to-end without waiting for a real trigger.

Lifecycle
=========

Same pattern as the rest of qiepai: the migration is created
synchronously at lifespan startup (see ``0002_feishu_groups.py``) and
the routes are mounted by the aggregate ``qiepai_router``.

No background tasks live here — the Feishu delivery is the outbox
worker's job (see :mod:`apps.api.services.qiepai.outbox.worker`).
"""
from __future__ import annotations

from . import feishu_settings, feishu_router, registry
from .feishu_settings import FeishuSettings
from .registry import FeishuGroup, first_active_chat_id, get_registry

__all__ = [
    "feishu_settings",
    "feishu_router",
    "registry",
    "FeishuSettings",
    "FeishuGroup",
    "first_active_chat_id",
    "get_registry",
]
