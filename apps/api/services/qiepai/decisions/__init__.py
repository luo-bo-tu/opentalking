"""qiepai · decisions service package (Phase ❷-5).

Exposes the DB-backed CRUD layer and the 4-layer AI assistant used by the
``/api/qiepai/decisions/*`` router (see ``apps/api/routes/qiepai/decisions.py``).

Routing inside this package
===========================

``service.py`` is the only module the router imports directly — it owns the
DB lifecycle (sqlite3 via :mod:`apps.api.services.qiepai.db`). When ``service``
needs an AI suggestion it delegates to :func:`ai_suggester.generate_suggestion`,
which transparently picks between :mod:`mock_suggester` (development) and the
real OpenClaw LLM client (``opentalking.agent.openclaw_provider``) based on
whether ``OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN`` is configured.

See ``qiepai-claw-stage2-spec.md`` § 5 + 架构 v1.1 § 0.1 / § 21.2 for the
4-layer response contract (``fact`` / ``inference`` / ``suggestion`` /
``unknown``).
"""
from __future__ import annotations

from . import ai_suggester, mock_suggester, service

__all__ = ["ai_suggester", "mock_suggester", "service"]
