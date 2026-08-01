"""qiepai · AI suggester dispatcher (Phase ❷-5).

Single public entry point :func:`generate_suggestion` returns the 4-layer
``{fact, inference, suggestion, unknown}`` dict for a decision item.

Resolution order
================

1. If ``OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN`` is non-empty AND the
   ``opentalking.agent.openclaw_provider`` module imports cleanly, build
   an :class:`OpenClawAgentLLMClient` and call ``chat_stream`` with a
   JSON-formatted task prompt. The LLM is asked to return **only** the
   4-layer JSON (no prose wrapper); a small post-processor wraps the
   response into the canonical dict.

2. **On any failure** (missing token, gateway unreachable, LLM error,
   JSON parse failure, timeout) fall back to
   :func:`apps.api.services.qiepai.decisions.mock_suggester.build_mock_suggestion`
   and attach a ``_warning`` string on the returned dict so the UI can
   surface "AI 降级到 mock" instead of silently misrepresenting the
   source of the answer.

The dispatcher NEVER raises; the route depends on this so a flaky LLM
can't 500 the decision board for the operator.

Caching contract
================

The CALLER (:mod:`service`) decides what to persist. This module returns
the same dict regardless of mock vs real, so caching is uniform.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from . import mock_suggester

log = logging.getLogger(__name__)


#: Sub-agent task prompt template — instructs the spawned sub-agent to
#: emit a strict JSON object and nothing else. Built and substituted via
#: :func:`_build_prompt` (NOT ``str.format``) so the literal JSON-shape
#: braces in the instructions are never interpreted as placeholders.
#: Substitutions:
#:   ``__TITLE__``       decision title
#:   ``__METRIC_ID__``   metric id (may be empty)
#:   ``__FACT_JSON__``   already-serialised fact_snapshot JSON
_TASK_PROMPT_TEMPLATE: str = """You are the right-side decision assistant for a Chinese enterprise cockpit.
Produce a JSON object with EXACTLY these four top-level keys and NOTHING else:

  "fact":        array of {"label", "value", "source"} read directly from `fact_snapshot` below; DO NOT invent numbers.
  "inference":   array of {"text", "confidence"}; one row, probability in [0, 1].
  "suggestion":  array of {"text", "owner_suggestion"}; one row, owner_suggestion is the recommended owner role (Chinese title).
  "unknown":     array of {"text"}; one row describing missing data needed for a better answer.

Decision context:
  title = __TITLE__
  metric_id = __METRIC_ID__

fact_snapshot (JSON, authoritative — do not modify):
__FACT_JSON__

Output requirements:
- Reply with ONLY the JSON object. No prose, no markdown fences, no trailing commentary.
- All Chinese language strings.
- Numbers must reference fact_snapshot verbatim; if a value isn't there, set its value to null.
"""


def _gateway_token_available() -> bool:
    return bool(os.environ.get("OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN", "").strip())


def _build_prompt(*, title: str, metric_id: str | None, fact_snapshot: dict[str, Any]) -> str:
    """Render the task prompt with safe JSON embedding.

    Uses plain ``str.replace`` rather than ``str.format`` so any literal
    braces in the prompt body (e.g. JSON-shape examples) are preserved
    verbatim and not interpreted as ``str.format`` placeholders.
    """
    safe_snapshot = json.dumps(fact_snapshot, ensure_ascii=False, sort_keys=True)
    return (
        _TASK_PROMPT_TEMPLATE
        .replace("__TITLE__", title or "(未命名决策)")
        .replace("__METRIC_ID__", metric_id or "(无关联指标)")
        .replace("__FACT_JSON__", safe_snapshot)
    )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """Best-effort extraction of a single JSON object from an LLM reply.

    Strips ```json ... ``` fences if present, then attempts
    ``json.loads``. Returns ``None`` if no valid JSON object can be
    recovered — the caller will then fall back to the mock suggester.
    """
    text = raw.strip()
    if not text:
        return None
    # strip leading ```json / ``` and trailing ``` if present
    if text.startswith("```"):
        # drop first line (```json or ```)
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
        text = text.strip()
    # Some LLMs prefix with a sentence — find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_4_layer(payload: Any) -> dict[str, Any] | None:
    """Return a normalised 4-layer dict, or ``None`` if the payload is malformed.

    Each layer must be a list of dicts. Missing layers are filled with
    empty lists so the contract is always satisfied — the caller has
    sensible empty-handling in the UI for "no rows" cases.
    """
    if not isinstance(payload, dict):
        return None
    out: dict[str, list[Any]] = {}
    for key in ("fact", "inference", "suggestion", "unknown"):
        layer = payload.get(key)
        if isinstance(layer, list):
            out[key] = [item for item in layer if isinstance(item, dict)]
        else:
            out[key] = []
    if not out["fact"] and not out["inference"] and not out["suggestion"] and not out["unknown"]:
        return None
    return out


async def _call_openclaw(
    *,
    prompt: str,
    title: str,
    metric_id: str | None,
) -> dict[str, Any] | None:
    """Call the configured OpenClaw sub-agent; return parsed 4-layer or None.

    Imports the provider lazily so a missing / uninstalled dependency
    degrades cleanly to mock mode (matching the "never raise" contract).
    """
    try:
        from opentalking.agent.openclaw_provider import OpenClawAgentLLMClient
    except Exception as exc:  # noqa: BLE001
        log.warning("ai_suggester: openclaw_provider import failed (%s); falling back to mock", exc)
        return None

    gateway_url = os.environ.get("OPENTALKING_LLM_OPENCLAW_GATEWAY_URL", "").strip()
    gateway_token = os.environ.get("OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN", "").strip()
    agent_id = os.environ.get("OPENTALKING_LLM_OPENCLAW_AGENT_ID", "").strip()
    if not (gateway_url and gateway_token and agent_id):
        log.info("ai_suggester: OpenClaw env not fully configured (url/token/agent_id); falling back to mock")
        return None

    try:
        client = OpenClawAgentLLMClient(
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            agent_id=agent_id,
            task_prompt_template="{prompt}",
            run_timeout_seconds=30,
            poll_interval_seconds=1.0,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("ai_suggester: client init failed (%s); falling back to mock", exc)
        return None

    # Drain chat_stream into a single string. The provider yields one
    # chunk (the full reply) per the provider's TTS-friendly contract.
    chunks: list[str] = []
    try:
        async for piece in client.chat_stream(
            [{"role": "user", "content": prompt}],
            requester_session_key=f"qiepai-decisions:{metric_id or 'none'}",
        ):
            chunks.append(piece)
    except Exception as exc:  # noqa: BLE001
        log.warning("ai_suggester: openclaw chat_stream failed (%s); falling back to mock", exc)
        return None

    raw_reply = "".join(chunks).strip()
    if not raw_reply:
        log.warning("ai_suggester: openclaw returned empty reply for %r; falling back to mock", title)
        return None

    parsed = _extract_json_object(raw_reply)
    if parsed is None:
        log.warning("ai_suggester: openclaw reply not parseable as JSON for %r; falling back to mock", title)
        return None
    validated = _validate_4_layer(parsed)
    if validated is None:
        log.warning("ai_suggester: openclaw reply passed JSON parse but failed 4-layer validation for %r", title)
        return None
    return validated


async def generate_suggestion(
    *,
    decision_id: str,
    decision_title: str,
    metric_id: str | None,
    fact_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return the 4-layer suggestion for a decision item. Never raises.

    The returned dict always contains the four keys ``fact``, ``inference``,
    ``suggestion``, ``unknown``. When the real LLM path is unavailable
    or errors out, a ``_warning`` field is added so the UI can surface
    "AI 降级为 mock" verbatim. When the real LLM path is used the
    ``_warning`` field is absent.

    Parameters
    ----------
    decision_id:
        The decision row id; logged but currently unused by the LLM
        prompt (kept for future tracing).
    decision_title:
        Forwarded to both the real prompt and the mock template header.
    metric_id:
        Drives mock template selection AND becomes the requester
        session-key namespace so concurrent suggestions for different
        metrics don't cross-pollute the gateway's child sessions.
    fact_snapshot:
        The decision row's fact_snapshot JSON (already-parsed). For the
        real path: forwarded verbatim to the LLM; for the mock path:
        drives the ``fact`` layer's first row when present.
    """
    prompt = _build_prompt(
        title=decision_title,
        metric_id=metric_id,
        fact_snapshot=fact_snapshot,
    )

    used_mock = False
    layers: dict[str, Any] | None = None
    if _gateway_token_available():
        layers = await _call_openclaw(
            prompt=prompt,
            title=decision_title,
            metric_id=metric_id,
        )
    if layers is None:
        used_mock = True
        layers = mock_suggester.build_mock_suggestion(
            fact_snapshot=fact_snapshot,
            decision_title=decision_title,
            metric_id=metric_id,
        )

    out = dict(layers)
    out["_used_mock"] = used_mock
    if used_mock:
        # Provide a stable, human-readable warning the frontend can
        # render verbatim if it wants. None when the real path was used.
        out["_warning"] = (
            "AI 实时建议不可用，已返回模拟建议 "
            "(OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN 未配置或调用失败)"
        )
    return out


__all__ = ["generate_suggestion"]
