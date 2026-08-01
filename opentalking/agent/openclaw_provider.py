"""OpenClaw gateway-backed LLM client.

This module implements an LLM provider that delegates each chat turn to an
OpenClaw sub-agent via the gateway's ``sessions_spawn`` tool, then streams the
sub-agent's final reply back to the qiepai runner the same way the
``OpenAICompatibleLLMClient`` streams chat completions.

Wire details
============

The OpenClaw gateway exposes a single HTTP endpoint for invoking built-in
tools directly:

- ``POST /tools/invoke`` (same port as the WS gateway, default 18789)
- Auth: ``Authorization: Bearer <gateway-token>`` (shared-secret token mode)
- Body: ``{"tool": "sessions_spawn", "args": {...}, "sessionKey": "...",
  "idempotencyKey": "..."}``

By default the gateway's HTTP deny list blocks ``sessions_spawn`` (it is
classified as a "session orchestration / RCE" surface). Operators must opt
in by adding it to ``gateway.tools.allow`` in the gateway config; otherwise
``/tools/invoke`` returns 404 with a "tool not available" detail.

Once spawned, ``sessions_spawn`` is non-blocking and returns::

    {"status": "accepted", "runId": "...", "childSessionKey": "agent:<id>:subagent:<uuid>"}

The sub-agent's completion is push-based back to the requester chat channel.
From an external caller's perspective the only way to observe the final
reply is to poll the child's session transcript via ``sessions_history``
until the most recent assistant message is terminal. We yield that final
reply text as a single chunk (split by sentence boundaries via the existing
``SentenceSplitter``) so the qiepai TTS pipeline can stream it.

The implementation intentionally avoids the WebSocket protocol because the
HTTP /tools/invoke path is simpler, easier to test, and equally faithful to
the user's "call sessions_spawn" requirement.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx


log = logging.getLogger(__name__)


_DEFAULT_POLL_INTERVAL = 1.5
_DEFAULT_REQUEST_TIMEOUT = 65.0
_DEFAULT_RUN_TIMEOUT = 600
_DEFAULT_HISTORY_LIMIT = 50


class OpenClawAgentConfigError(RuntimeError):
    """Raised when the OpenClaw provider is missing required configuration."""


def _render_prompt(template: str, user_text: str, system_text: str, messages: list[dict[str, Any]]) -> str:
    """Render the task prompt template.

    The template may reference ``{prompt}`` (last user message), ``{system}``
    (system prompt, may be empty) or ``{messages}`` (the full conversation
    joined as ``role: content`` lines). Unknown placeholders are left as-is
    so user-provided templates can contain literal ``{}`` braces.
    """
    if not template:
        return user_text
    safe_user = user_text or ""
    safe_system = system_text or ""
    safe_messages = ""
    if "{messages}" in template:
        lines: list[str] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip()
            content = str(m.get("content") or "").strip()
            if not role or not content:
                continue
            lines.append(f"{role}: {content}")
        safe_messages = "\n".join(lines)
    return template.format(prompt=safe_user, system=safe_system, messages=safe_messages)


def _extract_last_user(messages: list[dict[str, Any]]) -> str:
    """Return the content of the last user-role message, or '' if none."""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _extract_system(messages: list[dict[str, Any]]) -> str:
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


class OpenClawAgentLLMClient:
    """LLM client that delegates to an OpenClaw sub-agent via ``sessions_spawn``.

    The client speaks the gateway's HTTP ``/tools/invoke`` API. It calls
    ``sessions_spawn`` to launch an isolated sub-agent for the current turn,
    then polls ``sessions_history`` until the child produces a terminal
    assistant reply. The final reply text is yielded as a single chunk (or
    pre-split on sentence boundaries) so the qiepai TTS pipeline can stream
    it through the same code path as ordinary chat completions.

    Parameters
    ----------
    gateway_url:
        Base URL of the OpenClaw gateway (e.g. ``http://127.0.0.1:18789``).
    gateway_token:
        Bearer token used to authenticate against the gateway. Maps to the
        gateway's ``OPENCLAW_GATEWAY_TOKEN`` env or ``gateway.auth.token``.
    agent_id:
        Target sub-agent id passed to ``sessions_spawn`` as ``args.agentId``.
    task_prompt_template:
        Template for the sub-agent's task. ``{prompt}`` is replaced with the
        last user message; ``{system}`` is replaced with the system prompt;
        ``{messages}`` is replaced with the whole conversation.
    model:
        Optional model override forwarded to ``sessions_spawn``.
    session_key:
        Optional session key for the requester side. Defaults to
        ``"agent:<agent_id>:main"`` so each provider instance has a stable
        routing key.
    run_timeout_seconds:
        Maximum total wall-clock seconds to wait for the sub-agent to finish.
    poll_interval_seconds:
        Initial polling interval for ``sessions_history``; doubled on each
        consecutive empty poll up to a 5x cap.
    request_timeout_seconds:
        Per-HTTP-request timeout for the gateway.
    thinking:
        Optional thinking-level override forwarded to ``sessions_spawn``.
    context:
        Sub-agent context mode (``"isolated"`` or ``"fork"``). Defaults to
        ``"isolated"`` so the child starts clean.
    """

    def __init__(
        self,
        *,
        gateway_url: str,
        gateway_token: str,
        agent_id: str,
        task_prompt_template: str = "{prompt}",
        model: str = "",
        session_key: str = "",
        run_timeout_seconds: int = _DEFAULT_RUN_TIMEOUT,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT,
        thinking: str = "",
        context: str = "isolated",
        requester_session_key: str | None = None,
    ) -> None:
        self.base_url = (gateway_url or "").rstrip("/")
        self.token = (gateway_token or "").strip()
        self.agent_id = (agent_id or "").strip()
        self.task_prompt_template = task_prompt_template or "{prompt}"
        self.model = (model or "").strip()
        # ``session_key`` is retained as a configurable field for backwards
        # compatibility but is no longer used to route ``sessions_spawn`` /
        # ``sessions_history`` calls; that role moved to ``requester_session_key``
        # which is resolved per chat turn (see ``chat_stream``).
        explicit_session_key = (session_key or "").strip()
        if explicit_session_key:
            self.session_key: str = explicit_session_key
        elif self.agent_id:
            self.session_key = f"agent:{self.agent_id}:main"
        else:
            self.session_key = ""
        # Default requester-side routing key; callers may pass a different
        # value per chat turn (e.g. ``f"qiepai:{session_id}"``) to keep
        # concurrent qiepai sessions isolated.
        explicit_requester_session_key = (requester_session_key or "").strip()
        if explicit_requester_session_key:
            self._default_requester_session_key: str = explicit_requester_session_key
        elif self.agent_id:
            self._default_requester_session_key = f"agent:{self.agent_id}:main"
        else:
            self._default_requester_session_key = ""
        self.run_timeout_seconds = max(1, int(run_timeout_seconds))
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.request_timeout_seconds = max(5.0, float(request_timeout_seconds))
        self.thinking = (thinking or "").strip()
        self.context = (context or "").strip() or "isolated"

        # Validate eagerly so configuration errors surface at construction
        # time (matches the OpenAICompat client's "raise on missing base_url"
        # behaviour the rest of the runner relies on).
        self._validate()

    def _validate(self) -> None:
        if not self.base_url:
            raise OpenClawAgentConfigError(
                "openclaw_agent provider is missing `gateway_url`; "
                "set OPENTALKING_LLM_OPENCLAW_GATEWAY_URL"
            )
        if not self.token:
            raise OpenClawAgentConfigError(
                "openclaw_agent provider is missing `gateway_token`; "
                "set OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN"
            )
        if not self.agent_id:
            raise OpenClawAgentConfigError(
                "openclaw_agent provider is missing `agent_id`; "
                "set OPENTALKING_LLM_OPENCLAW_AGENT_ID"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _invoke_tool(
        self,
        client: httpx.AsyncClient,
        *,
        tool: str,
        args: dict[str, Any],
        session_key: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Invoke one gateway tool and return the parsed ``result`` payload.

        Raises ``httpx.HTTPStatusError`` for non-2xx responses with a
        message that includes the gateway's error payload so failures are
        easy to diagnose.
        """
        url = f"{self.base_url}/tools/invoke"
        body: dict[str, Any] = {
            "tool": tool,
            "args": args,
            "sessionKey": session_key,
            "idempotencyKey": idempotency_key,
        }
        response = await client.post(url, headers=self._headers(), json=body)
        if response.status_code >= 400:
            # Surface the gateway's error payload if it returned one.
            # ``response.text`` may be empty or non-JSON when the request
            # is intercepted by a proxy or load-balancer; fall back to the
            # raw bytes (truncated to 4 KiB) for a clear error message.
            try:
                error_payload: Any = response.json()
            except Exception:
                try:
                    raw_text = response.text
                except Exception:
                    raw_text = "<unreadable body>"
                if len(raw_text) > 4096:
                    raw_text = raw_text[:4096] + "...(truncated)"
                error_payload = {"raw": raw_text}
            raise httpx.HTTPStatusError(
                f"OpenClaw gateway {tool} failed: "
                f"status={response.status_code} body={json.dumps(error_payload, ensure_ascii=False)}",
                request=response.request,
                response=response,
            )
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise OpenClawAgentConfigError(
                f"OpenClaw gateway {tool} returned non-ok payload: {payload!r}"
            )
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    def _compose_task(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Return (user_text, system_text) extracted from the conversation."""
        return _extract_last_user(messages), _extract_system(messages)

    def _build_spawn_args(self, task: str) -> dict[str, Any]:
        args: dict[str, Any] = {
            "task": task,
            "context": self.context,
        }
        if self.agent_id:
            args["agentId"] = self.agent_id
        if self.model:
            args["model"] = self.model
        if self.thinking:
            args["thinking"] = self.thinking
        return args

    async def _spawn_subagent(
        self,
        client: httpx.AsyncClient,
        *,
        task: str,
        session_key: str,
        idempotency_key: str,
    ) -> str:
        """Call sessions_spawn and return the child session key."""
        result = await self._invoke_tool(
            client,
            tool="sessions_spawn",
            args=self._build_spawn_args(task),
            session_key=session_key,
            idempotency_key=idempotency_key,
        )
        status = result.get("status")
        if status not in ("accepted", "ok"):
            raise OpenClawAgentConfigError(
                f"sessions_spawn returned unexpected status: {status!r} result={result!r}"
            )
        child_key = result.get("childSessionKey") or result.get("sessionKey")
        if not isinstance(child_key, str) or not child_key.strip():
            raise OpenClawAgentConfigError(
                f"sessions_spawn did not return a childSessionKey: {result!r}"
            )
        return child_key.strip()

    async def _poll_history(
        self,
        client: httpx.AsyncClient,
        *,
        child_key: str,
        session_key: str,
        idempotency_key: str,
        deadline: float,
    ) -> str:
        """Poll sessions_history until the child produces a final reply.

        Returns the last assistant text content. Raises ``asyncio.TimeoutError``
        if the deadline is exceeded.
        """
        interval = self.poll_interval_seconds
        max_interval = self.poll_interval_seconds * 5.0
        attempts = 0
        last_text: str = ""
        terminal_status: str = ""
        while True:
            attempts += 1
            try:
                result = await self._invoke_tool(
                    client,
                    tool="sessions_history",
                    args={"sessionKey": child_key, "limit": _DEFAULT_HISTORY_LIMIT},
                    session_key=session_key,
                    # ``sessions_history`` is read-only so it doesn't require
                    # an idempotency key, but we still pass a per-attempt
                    # key so the gateway can dedupe accidental retries.
                    idempotency_key=f"{idempotency_key}-poll-{attempts}",
                )
            except httpx.HTTPStatusError as exc:
                # Transient gateway error: log and keep polling.
                log.warning(
                    "openclaw_agent sessions_history poll failed (attempt %d): %s",
                    attempts,
                    exc,
                )
            else:
                terminal_status = str(result.get("status") or "")
                current_text = _extract_last_assistant_text(result.get("messages"))
                # Prefer the most recent assistant text. We don't reset
                # ``last_text`` on empty polls so that a partial reply we
                # already observed isn't lost if the child later returns to
                # a "still running" state.
                if current_text:
                    last_text = current_text
                # If the gateway reports the child as done (and we've
                # already collected *something*) we're finished. We also
                # treat a terminal payload with no text as a clean stop
                # so we don't keep polling an empty transcript.
                is_terminal = (
                    terminal_status in ("done", "completed", "ok", "ready")
                    or _is_terminal_payload(result)
                )
                if is_terminal:
                    if last_text:
                        return last_text
                    # Terminal but empty: stop polling and let the caller
                    # decide what to do (the chat_stream will yield nothing).
                    return ""
            now = asyncio.get_event_loop().time()
            if now >= deadline:
                break
            await asyncio.sleep(min(interval, max(0.05, deadline - now)))
            interval = min(max_interval, interval * 1.5)
        # Deadline reached. If we have any text at all, yield it; otherwise raise.
        if last_text:
            log.warning(
                "openclaw_agent run timed out after %ds; returning partial reply",
                self.run_timeout_seconds,
            )
            return last_text
        raise asyncio.TimeoutError(
            f"sessions_spawn child {child_key!r} did not produce a reply within "
            f"{self.run_timeout_seconds}s"
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        requester_session_key: str | None = None,
    ) -> AsyncIterator[str]:
        self._validate()
        user_text, system_text = self._compose_task(messages)
        if not user_text:
            # No user message → nothing to delegate; yield empty to keep the
            # pipeline alive (the runner will skip empty prompts upstream).
            return
        task = _render_prompt(self.task_prompt_template, user_text, system_text, messages)
        if not task.strip():
            return

        # Priority: per-turn override > ``__init__`` default > per-agent fallback.
        explicit_key = (requester_session_key or "").strip()
        if explicit_key:
            session_key: str = explicit_key
        elif self._default_requester_session_key:
            session_key = self._default_requester_session_key
        else:
            session_key = f"agent:{self.agent_id}:main" if self.agent_id else f"qiepai-openclaw-agent-{uuid4().hex[:8]}"
        idempotency_key = uuid4().hex
        timeout = httpx.Timeout(
            connect=10.0,
            read=self.request_timeout_seconds,
            write=30.0,
            pool=10.0,
        )

        # NOTE: if the surrounding runner cancels this coroutine (e.g. user
        # interrupts the speech), the spawned sub-agent on the gateway
        # continues to run until it finishes or its own timeout kicks in.
        # The gateway can be configured with ``maxConcurrent`` to prevent
        # runaway children; we don't try to ``subagents kill`` from here
        # because the sub-agent's announce step is push-based and would
        # fail anyway once the requester is gone.
        async with httpx.AsyncClient(timeout=timeout) as client:
            child_key = await self._spawn_subagent(
                client,
                task=task,
                session_key=session_key,
                idempotency_key=idempotency_key,
            )
            log.info(
                "openclaw_agent spawned child session=%s agent=%s",
                child_key,
                self.agent_id,
            )
            loop = asyncio.get_event_loop()
            deadline = loop.time() + self.run_timeout_seconds
            final_text = await self._poll_history(
                client,
                child_key=child_key,
                session_key=session_key,
                idempotency_key=idempotency_key,
                deadline=deadline,
            )

        final_text = final_text.strip()
        if not final_text:
            return

        # Yield as a single chunk for the existing TTS pipeline. The runner
        # already wraps a SentenceSplitter around the stream so we don't
        # need to split here. We still keep the chunk non-empty so the
        # sentinel-based flow control works.
        yield final_text


def _extract_last_assistant_text(messages: Any) -> str:
    """Best-effort extraction of the last assistant text from a history payload.

    The gateway's ``sessions_history`` payload shape is not strictly
    documented; we accept either a list of message objects or a dict with
    a ``messages`` key, and look for the last ``role == "assistant"`` entry
    whose ``content`` is a non-empty string. Multi-part content arrays
    (e.g. ``[{"type": "text", "text": "..."}]``) are flattened.
    """
    if isinstance(messages, dict):
        messages = messages.get("messages") or messages.get("items") or []
    if not isinstance(messages, list):
        return ""
    for entry in reversed(messages):
        if not isinstance(entry, dict):
            continue
        if entry.get("role") != "assistant":
            continue
        content = entry.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        elif isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") in (None, "text") and isinstance(part.get("text"), str):
                        parts.append(part["text"])
                    elif isinstance(part.get("content"), str):
                        parts.append(part["content"])
                elif isinstance(part, str):
                    parts.append(part)
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                return joined
    return ""


def _is_terminal_payload(payload: dict[str, Any]) -> bool:
    """Heuristic: did the gateway report the spawned run as finished?"""
    if not isinstance(payload, dict):
        return False
    if payload.get("done") is True:
        return True
    if payload.get("completed") is True:
        return True
    status = payload.get("status")
    return status in ("done", "completed", "finished", "ok")


def build_openclaw_agent_client(
    *,
    gateway_url: str,
    gateway_token: str,
    agent_id: str,
    task_prompt_template: str = "{prompt}",
    model: str = "",
    run_timeout_seconds: int = _DEFAULT_RUN_TIMEOUT,
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL,
    request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT,
    thinking: str = "",
    context: str = "isolated",
) -> OpenClawAgentLLMClient:
    """Factory kept for symmetry with ``build_tts_adapter`` patterns."""
    return OpenClawAgentLLMClient(
        gateway_url=gateway_url,
        gateway_token=gateway_token,
        agent_id=agent_id,
        task_prompt_template=task_prompt_template,
        model=model,
        run_timeout_seconds=run_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        request_timeout_seconds=request_timeout_seconds,
        thinking=thinking,
        context=context,
    )


# Side-effect: register this provider in the capability registry so that
# ``opentalking.core.registry.resolve("llm", "openclaw_agent")`` works
# after ``opentalking.providers.bootstrap()`` is called.
from opentalking.core.registry import register  # noqa: E402

register("llm", "openclaw_agent")(OpenClawAgentLLMClient)


__all__ = [
    "OpenClawAgentLLMClient",
    "OpenClawAgentConfigError",
    "build_openclaw_agent_client",
]
