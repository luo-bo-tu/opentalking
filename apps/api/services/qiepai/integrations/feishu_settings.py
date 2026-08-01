"""qiepai · Feishu configuration singleton (Phase ❸-1).

A tiny typed-config layer that reads ``QIEPAI_FEISHU_*`` env vars on
demand. Lives outside ``opentalking.core.config.Settings`` because that
module ships a ``model_config(env_prefix='OPENTALKING_')`` — adding a
``QIEPAI_*`` field there would leak into every OpenTalking process,
which violates the "qiepai boundary" cut at the apps/api level (the
qiepai services must remain loadable on a clean Python path without
importing the OpenTalking settings module if someone trims the
runtime down for an embedded deployment).

Why a singleton (``feishu_settings``) rather than a free function?
=====================================================================

* Two callsites (publisher + smoke tests) both need the same value
  per-process; ``Settings()`` would re-read the env every call,
  which is not the desired behaviour under a config hot-reload test.
* The :func:`is_configured` predicate is part of the public surface
  of the package (``registry.py`` + tests) and benefits from being a
  method on a type-stable handle rather than a function call.

Public surface
==============

* :class:`FeishuSettings` — the typed record (frozen dataclass for
  immutability + cheap hashing).
* :func:`feishu_settings` — the module-level accessor; returns a
  singleton via ``@lru_cache``.

If a future deploy needs to hot-reload creds, the right move is to
add a ``reload()`` method that re-reads the env (called from a
FastAPI ``PUT /runtime-config`` equivalent) — not to expose a mutable
``Settings`` instance.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeishuSettings:
    """Read-only view of the ``QIEPAI_FEISHU_*`` environment.

    Attributes
    ----------
    app_id
        Feishu app id (mandatory for live mode; empty string ⇒ dry-run).
    app_secret
        Feishu app secret (mandatory for live mode; empty string ⇒
        dry-run).
    webhook_url
        Optional incoming-webhook fallback for environments that prefer
        it over the OpenAPI tenant_access_token flow. Empty by default;
        when non-empty the publisher will prefer the webhook and skip
        the token dance.
    token_ttl_s
        How long an issued ``tenant_access_token`` is trusted before
        refresh (default 2 hours, matching the Feishu recommended
        7200-second TTL).
    poll_interval_s
        Optional: defaults to 2.0 if the env var is missing.
    batch_size
        Optional: defaults to 50 if the env var is missing.
    """

    app_id: str = ""
    app_secret: str = ""
    webhook_url: str = ""
    token_ttl_s: int = 7200
    poll_interval_s: float = 2.0
    batch_size: int = 50

    def is_configured(self) -> bool:
        """True iff the publisher can attempt a *live* delivery.

        Requires either ``app_id`` + ``app_secret`` (for the tenant
        token path) OR a non-empty ``webhook_url`` (for the incoming
        webhook path). Anything else leaves the publisher in dry-run.
        """
        return bool(
            (self.app_id and self.app_secret) or self.webhook_url
        )


def _load() -> FeishuSettings:
    def _str(name: str, default: str = "") -> str:
        return os.environ.get(name, default).strip()

    def _int(name: str, default: int) -> int:
        raw = _str(name)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            log.warning(
                "feishu_settings: invalid %s=%r; using default %s",
                name,
                raw,
                default,
            )
            return default

    def _float(name: str, default: float) -> float:
        raw = _str(name)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            log.warning(
                "feishu_settings: invalid %s=%r; using default %s",
                name,
                raw,
                default,
            )
            return default

    return FeishuSettings(
        app_id=_str("QIEPAI_FEISHU_APP_ID"),
        app_secret=_str("QIEPAI_FEISHU_APP_SECRET"),
        webhook_url=_str("QIEPAI_FEISHU_WEBHOOK_URL"),
        token_ttl_s=_int("QIEPAI_FEISHU_TOKEN_TTL_S", 7200),
        poll_interval_s=_float("QIEPAI_OUTBOX_POLL_S", 2.0),
        batch_size=_int("QIEPAI_OUTBOX_BATCH", 50),
    )


@lru_cache(maxsize=1)
def feishu_settings() -> FeishuSettings:
    """Return the process-singleton Feishu config.

    Memoised via ``@lru_cache`` so the env-var churn above happens at
    most once per process. Tests that want a fresh view call
    :func:`reload_settings` instead.
    """
    return _load()


def reload_settings() -> FeishuSettings:
    """Discard the cached view and re-read env vars.

    Used by the integration "test delivery" endpoint (so the operator
    can drop a credential into the env and re-run the test without
    restarting the server) and by tests that need a clean slate.
    """
    feishu_settings.cache_clear()
    return feishu_settings()


__all__ = ["FeishuSettings", "feishu_settings", "reload_settings"]
