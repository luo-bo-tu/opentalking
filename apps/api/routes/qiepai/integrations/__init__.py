"""qiepai · Feishu integration router package (Phase ❸-1).

Re-exports the FastAPI ``router`` from
:mod:`apps.api.services.qiepai.integrations.feishu_router` so the
aggregate ``qiepai_router`` only needs a single ``include_router``
call to mount the endpoints.

Mount path
==========

* Router prefix (this package): ``/qiepai/integrations/feishu``  →
  final URLs ``/api/qiepai/integrations/feishu/*``.
* Service module path:
  ``apps.api.services.qiepai.integrations.feishu_router.router``.

Why a thin wrapper module rather than including the service router
directly? Because we want to keep the route layer and the service
layer on separate import paths (the ❷-domain convention): services
live under ``apps.api.services.qiepai.*``; routes live under
``apps.api.routes.qiepai.*``. The route layer here is a near-empty
shim that imports the service's router and re-exports it.
"""
from __future__ import annotations

from apps.api.services.qiepai.integrations import feishu_router
from apps.api.services.qiepai.integrations.feishu_router import router

__all__ = ["router", "feishu_router"]
