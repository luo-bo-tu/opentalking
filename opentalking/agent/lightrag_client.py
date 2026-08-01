"""LightRAG facade — canonical entry point for qiepai RAG integration.

qiepai ❺ wraps the in-process LightRAG Python SDK so callers do not
have to know whether the embedder is OpenAI-compatible, local-hash,
or future backends. The facade exposes four small helpers and
re-exports the public types from :mod:`opentalking.agent.knowledge_index`:

* :func:`search_relevant` — primary query helper. Calls the in-process
  index, logs elapsed time, and returns ``[]`` on any failure (the
  caller is responsible for deciding whether to fall back to SQLite
  keyword search).
* :func:`lightrag_status` — SDK availability + per-KB index status
  in one tuple, suitable for an admin/health endpoint.
* :func:`lightrag_index_config` — current embedding model + dimension
  + query-mode derived from :func:`opentalking.core.config.get_settings`.
* :func:`default_lightrag_client` — singleton accessor that lazily
  builds (and caches) a :class:`KnowledgeIndex` per ``knowledge_root``.

Why in-process (not the HTTP server)
====================================

The spec considered three flavours:

* **A (chosen) — in-process SDK.** The Python ``lightrag`` package
  is already on ``.venv`` (1.5.4) and ``lightrag-server`` /
  ``sentence-transformers`` are not. In-process keeps the API surface
  identical to a sidecar (``query()`` / ``index_document()`` /
  ``delete_document()``) but skips a separate 9621 port and the
  ``PyJWT`` dependency the HTTP server drags in.
* **B — HTTP sidecar.** Would require ``pip install`` of missing
  ``lightrag[api]`` extras (``jwt``, ``uvicorn``, ``fastapi``) and a
  long-running ``lightrag-server`` subprocess spawned from
  ``apps/unified/main.py`` lifespan. Forbidden by ❺ red-line
  ("不引新依赖") and unnecessary given A already covers the spec.
* **C — pure SQLite.** Status quo. ``search_relevant`` falls back to
  the existing ``_query_chunk_fallback_sync`` path in
  ``knowledge_store.py`` whenever LightRAG is unavailable; that
  safety net is preserved unchanged here.

Module policy
=============

* Re-exports the public types from ``knowledge_index`` so callers can
  ``from opentalking.agent.lightrag_client import KnowledgeIndex``.
* Performs all blocking work in ``asyncio`` threads via the
  existing ``_run_async`` helper inside ``knowledge_index``; this
  module itself is synchronous from the caller's perspective.
* Never imports ``lightrag`` at module top — the SDK is optional and
  every public helper tolerates its absence (returns ``[]`` /
  ``(False, "lightrag_not_installed")``).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Final

from opentalking.agent.knowledge_index import (  # re-exported below
    KnowledgeIndex,
    LightRAGKnowledgeIndex,
    LightRAGSearchResult,
    LightRAGStatus,
    default_knowledge_index,
)

_log = logging.getLogger(__name__)

__all__ = [
    "KnowledgeIndex",
    "LightRAGKnowledgeIndex",
    "LightRAGSearchResult",
    "LightRAGStatus",
    "default_knowledge_index",
    "search_relevant",
    "lightrag_status",
    "lightrag_index_config",
    "default_lightrag_client",
    "reset_lightrag_client_cache",
]


_PERF_LOG_THRESHOLD_MS: Final[float] = 500.0
_CLIENT_CACHE: dict[str, KnowledgeIndex] = {}
_CLIENT_CACHE_LOCK = threading.Lock()


def _client_for(knowledge_root: str | Path) -> KnowledgeIndex:
    """Return the cached :class:`KnowledgeIndex` for ``knowledge_root``.

    The cache is process-wide so callers across the FastAPI app +
    worker share the same in-process LightRAG storages. ``_run_async``
    inside ``knowledge_index`` already serialises individual SDK
    calls via a ``threading.Lock``; this outer cache only avoids
    re-instantiating the ``Settings``-derived wrapper.
    """
    key = str(knowledge_root)
    cached = _CLIENT_CACHE.get(key)
    if cached is not None:
        return cached
    with _CLIENT_CACHE_LOCK:
        cached = _CLIENT_CACHE.get(key)
        if cached is not None:
            return cached
        index = default_knowledge_index(knowledge_root)
        _CLIENT_CACHE[key] = index
        return index


def reset_lightrag_client_cache() -> None:
    """Drop the cached clients. Test-only helper."""
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()


def search_relevant(
    *,
    knowledge_root: str | Path,
    kb_id: str,
    query: str,
    limit: int,
    index: KnowledgeIndex | None = None,
) -> list[LightRAGSearchResult]:
    """Run a LightRAG semantic query and return matching chunks.

    Behaviour contract
    ------------------

    * Empty / blank ``query`` → ``[]`` (no work, no log).
    * ``limit <= 0`` → ``[]``.
    * SDK unavailable → ``[]`` (caller is expected to fall back to
      SQLite keyword search; matches the existing
      ``_query_lightrag_sync`` semantics).
    * Index for ``kb_id`` not yet built → ``[]``.
    * Any SDK exception is caught and logged at WARNING with full
      traceback, then ``[]`` is returned. This is the documented
      fallback contract: the caller decides whether to back-fill
      from ``knowledge_chunks``.

    Performance logging
    --------------------

    When the elapsed time exceeds ``_PERF_LOG_THRESHOLD_MS``
    (default 500 ms — the ❺ spec budget), the call is logged at
    WARNING with the actual elapsed time and the request parameters
    so an operator can investigate. Sub-budget calls are silently
    traced at DEBUG.
    """
    if not query or not query.strip() or limit <= 0:
        return []
    client = index if index is not None else _client_for(knowledge_root)
    status = client.status(kb_id=kb_id)
    if not status.available:
        _log.debug(
            "lightrag.search_relevant: kb=%s unavailable reason=%s",
            kb_id,
            status.reason or "unknown",
        )
        return []
    if not status.indexed:
        _log.debug(
            "lightrag.search_relevant: kb=%s not yet indexed reason=%s",
            kb_id,
            status.reason or "unknown",
        )
        return []
    started = time.perf_counter()
    try:
        results = client.query(kb_id=kb_id, query=query, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "lightrag.search_relevant: kb=%s query failed; returning [] for fallback",
            kb_id,
            exc_info=exc,
        )
        return []
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if elapsed_ms >= _PERF_LOG_THRESHOLD_MS:
        _log.warning(
            "lightrag.search_relevant: kb=%s elapsed=%.1fms limit=%d results=%d (>=%sms budget)",
            kb_id,
            elapsed_ms,
            limit,
            len(results),
            _PERF_LOG_THRESHOLD_MS,
        )
    else:
        _log.debug(
            "lightrag.search_relevant: kb=%s elapsed=%.1fms limit=%d results=%d",
            kb_id,
            elapsed_ms,
            limit,
            len(results),
        )
    return results


def lightrag_status(*, knowledge_root: str | Path, kb_id: str) -> LightRAGStatus:
    """Return SDK availability + index status for ``kb_id``.

    Cheap to call (no async work); the underlying
    ``LightRAGKnowledgeIndex.status`` only inspects the on-disk
    ``vdb_chunks.json`` and ``kv_store_doc_status.json`` files.
    """
    return _client_for(knowledge_root).status(kb_id=kb_id)


def lightrag_index_config() -> dict[str, Any]:
    """Return the current embedding model + dim + query-mode settings.

    Pulls from :func:`opentalking.core.config.get_settings` so an
    operator endpoint (or a debug log line) can surface what the
    next ``index_document`` call will use without spinning up the
    actual LightRAG instance. Falls back to the documented defaults
    if settings are not yet loaded (e.g. very early import).
    """
    try:
        from opentalking.core.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001
        return {
            "embedding_model": "text-embedding-v4",
            "vector_dim": 1024,
            "query_mode": "hybrid",
            "language": "Chinese",
            "uses_remote_models": False,
        }
    return {
        "embedding_model": str(
            getattr(settings, "agent_lightrag_embedding_model", "text-embedding-v4")
            or "text-embedding-v4"
        ),
        "vector_dim": int(getattr(settings, "agent_lightrag_embedding_dim", 1024) or 1024),
        "query_mode": str(getattr(settings, "agent_lightrag_query_mode", "hybrid") or "hybrid"),
        "language": str(getattr(settings, "agent_lightrag_language", "Chinese") or "Chinese"),
        "uses_remote_models": bool(
            getattr(settings, "agent_lightrag_llm_base_url", "")
            and getattr(settings, "agent_lightrag_llm_api_key", "")
            and getattr(settings, "agent_lightrag_embedding_base_url", "")
            and getattr(settings, "agent_lightrag_embedding_api_key", "")
        ),
    }


def default_lightrag_client(knowledge_root: str | Path) -> KnowledgeIndex:
    """Public alias for :func:`_client_for` so callers can grab the
    singleton without going through ``search_relevant``.

    Most code should call :func:`search_relevant` directly — this
    accessor is for endpoints that want to introspect status or run
    multiple queries against the same client instance.
    """
    return _client_for(knowledge_root)