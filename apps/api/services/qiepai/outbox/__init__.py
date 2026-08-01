"""qiepai · outbox event publishing pipeline (Phase ❸-1).

This package implements the **transactional outbox** pattern for qiepai
business events:

* :mod:`.events` — typed event definitions + payload builders for each
  of the 5+1 dispatched triggers (employee publish, decision status,
  task assignment, task completion, KPI anomaly, manual demo).
* :mod:`.publisher` — async Feishu webhook delivery (token cache +
  card renderer). All network IO lives here; the worker never reaches
  out to the network directly.
* :mod:`.worker` — background asyncio loop that polls the
  ``outbox_events`` table for pending rows, dispatches them through
  the publisher, and updates ``state`` + ``attempts`` + ``next_retry_at``
  with exponential backoff.

Mount / lifecycle
=================

The worker is spawned by the host application's lifespan (currently
``apps/unified/main.py:unified_lifespan``) via
:func:`apps.api.services.qiepai.outbox.worker.start_worker` and
cancelled with :func:`stop_worker`. No external scheduler / cron is
required — qiepai runs the worker in-process.

Why in-process (rather than a separate microservice)?
-----------------------------------------------------

* The unified app already runs a single FastAPI instance with an
  in-memory task queue (``apps/unified/main.py``); adding another
  process would break the "single binary" UX.
* The outbox table itself is the durable queue — even if the process
  restarts mid-publish, an event in state ``pending`` or
  ``in_flight`` is picked up on the next boot by the simple
  ``state IN ('pending')`` claim query.
* The publisher uses an HTTP client only — no shared state with the
  web tier.
"""
from __future__ import annotations

from . import events, publisher, worker
from .events import OutboxEventDraft, build_event_payload

__all__ = [
    "events",
    "publisher",
    "worker",
    "OutboxEventDraft",
    "build_event_payload",
]
