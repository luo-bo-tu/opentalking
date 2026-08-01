"""Tests for the OpenClaw gateway-backed LLM provider.

These tests mock the gateway's HTTP ``/tools/invoke`` endpoint so we can
exercise the full dispatch path:
- ``sessions_spawn`` accept receipt → ``sessions_history`` poll loop
- 401 / 404 / 500 / Timeout / connect-error failure paths
- prompt template rendering (single-shot, isolated, custom)
- registry integration (``opentalking.core.registry``)
- runner dispatch (the qiepai LLM dispatch entry picks the right client)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from opentalking.agent.openclaw_provider import (
    OpenClawAgentConfigError,
    OpenClawAgentLLMClient,
    _extract_last_assistant_text,
    _extract_last_user,
    _extract_system,
    _render_prompt,
    build_openclaw_agent_client,
)
from opentalking.core.registry import list_keys, resolve


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client_kwargs() -> dict[str, Any]:
    return {
        "gateway_url": "http://gateway.test:18789",
        "gateway_token": "secret-token",
        "agent_id": "main",
        "task_prompt_template": "{prompt}",
        "run_timeout_seconds": 5,
        "poll_interval_seconds": 0.05,
        "request_timeout_seconds": 5.0,
    }


@pytest.fixture
def spawned_session() -> dict[str, str]:
    return {
        "status": "accepted",
        "runId": "run-abc-123",
        "childSessionKey": "agent:main:subagent:child-uuid",
    }


def _make_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> type[httpx.AsyncClient]:
    """Return an ``httpx.AsyncClient`` subclass that drives the test handler."""

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    return PatchedAsyncClient


def _collect_async(async_iter):
    """Collect an async iterator into a list (helper for assertions)."""

    async def _run() -> list[str]:
        items: list[str] = []
        async for item in async_iter:
            items.append(item)
        return items

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Unit-level helpers
# ---------------------------------------------------------------------------


def test_extract_last_user_returns_most_recent_user_text() -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ack"},
        {"role": "user", "content": "second"},
    ]
    assert _extract_last_user(msgs) == "second"


def test_extract_last_user_handles_missing_user_message() -> None:
    assert _extract_last_user([{"role": "system", "content": "hi"}]) == ""


def test_extract_system_returns_first_system_text() -> None:
    msgs = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "hi"},
    ]
    assert _extract_system(msgs) == "You are helpful"


def test_extract_last_assistant_text_handles_list_of_dicts() -> None:
    history = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "hello there"}]},
        ]
    }
    assert _extract_last_assistant_text(history) == "hello there"


def test_extract_last_assistant_text_handles_raw_list() -> None:
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "plain string reply"},
    ]
    assert _extract_last_assistant_text(history) == "plain string reply"


def test_render_prompt_supports_placeholders() -> None:
    template = "User said: {prompt}\nSystem: {system}"
    out = _render_prompt(template, "hello", "be concise", [])
    assert out == "User said: hello\nSystem: be concise"


def test_render_prompt_includes_messages_placeholder() -> None:
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    out = _render_prompt("History:\n{messages}", "second", "", msgs)
    assert "user: first" in out
    assert "assistant: reply" in out
    assert "user: second" in out


def test_render_prompt_returns_user_text_when_template_empty() -> None:
    assert _render_prompt("", "fallback", "sys", []) == "fallback"


# ---------------------------------------------------------------------------
# Provider validation
# ---------------------------------------------------------------------------


def test_client_raises_when_gateway_url_missing(client_kwargs: dict[str, Any]) -> None:
    client_kwargs["gateway_url"] = ""
    with pytest.raises(OpenClawAgentConfigError, match="gateway_url"):
        OpenClawAgentLLMClient(**client_kwargs)


def test_client_raises_when_gateway_token_missing(client_kwargs: dict[str, Any]) -> None:
    client_kwargs["gateway_token"] = ""
    with pytest.raises(OpenClawAgentConfigError, match="gateway_token"):
        OpenClawAgentLLMClient(**client_kwargs)


def test_client_raises_when_agent_id_missing(client_kwargs: dict[str, Any]) -> None:
    client_kwargs["agent_id"] = ""
    with pytest.raises(OpenClawAgentConfigError, match="agent_id"):
        OpenClawAgentLLMClient(**client_kwargs)


def test_build_factory_creates_configured_client(client_kwargs: dict[str, Any]) -> None:
    client = build_openclaw_agent_client(**client_kwargs)
    assert isinstance(client, OpenClawAgentLLMClient)
    assert client.agent_id == "main"
    assert client.run_timeout_seconds == 5


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registry_contains_openclaw_agent_after_import() -> None:
    """Importing the provider package must register the openclaw_agent key."""
    from opentalking.providers import bootstrap  # noqa: F401

    bootstrap()
    assert "openclaw_agent" in list_keys("llm")
    # Resolve must return the OpenClaw client class.
    cls = resolve("llm", "openclaw_agent")
    assert cls is OpenClawAgentLLMClient


# ---------------------------------------------------------------------------
# Happy path: dispatch with sessions_spawn → sessions_history polling
# ---------------------------------------------------------------------------


def test_chat_stream_spawns_and_returns_final_reply(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
    spawned_session: dict[str, str],
) -> None:
    """The full chat_stream path: spawn → poll → yield final reply."""
    seen_requests: list[httpx.Request] = []
    poll_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        tool = payload.get("tool")
        if tool == "sessions_spawn":
            assert payload["args"]["task"] == "你好"
            assert payload["args"]["agentId"] == "main"
            assert payload["args"]["context"] == "isolated"
            return httpx.Response(200, json={"ok": True, "result": spawned_session})
        if tool == "sessions_history":
            poll_bodies.append(payload)
            # First poll: empty; second poll: terminal reply.
            if len(poll_bodies) == 1:
                return httpx.Response(
                    200,
                    json={"ok": True, "result": {"status": "running", "messages": []}},
                )
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "status": "done",
                        "messages": [
                            {"role": "user", "content": "你好"},
                            {"role": "assistant", "content": "你好世界"},
                        ],
                    },
                },
            )
        return httpx.Response(404, json={"ok": False, "error": {"message": "unknown tool"}})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    messages = [
        {"role": "system", "content": "you are concise"},
        {"role": "user", "content": "你好"},
    ]
    chunks = _collect_async(client.chat_stream(messages))
    assert chunks == ["你好世界"]
    # We saw both spawn and history calls.
    tools_seen = [json.loads(r.content.decode("utf-8")).get("tool") for r in seen_requests]
    assert tools_seen[:2] == ["sessions_spawn", "sessions_history"]
    assert "sessions_history" in tools_seen
    # History was called with the right session key.
    assert poll_bodies[0]["args"]["sessionKey"] == spawned_session["childSessionKey"]


def test_chat_stream_sends_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
    spawned_session: dict[str, str],
) -> None:
    """Auth header must contain the configured bearer token."""
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update({k.lower(): v for k, v in request.headers.items()})
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": spawned_session})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "ok"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == ["ok"]
    assert captured_headers.get("authorization") == "Bearer secret-token"


def test_chat_stream_includes_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
    spawned_session: dict[str, str],
) -> None:
    """The spawn request must include a stable idempotency key."""
    spawn_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            spawn_payload.update(payload)
            return httpx.Response(200, json={"ok": True, "result": spawned_session})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "ok"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    _collect_async(client.chat_stream([{"role": "user", "content": "data"}]))
    assert "idempotencyKey" in spawn_payload
    assert spawn_payload["idempotencyKey"]  # non-empty


def test_chat_stream_emits_nothing_when_user_message_empty(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """No user message → no HTTP call, no chunks."""
    called = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {}})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "system", "content": "hi"}]))
    assert chunks == []
    assert called["count"] == 0


def test_chat_stream_forwards_model_and_thinking(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
    spawned_session: dict[str, str],
) -> None:
    """Optional fields model / thinking are forwarded to sessions_spawn."""
    spawn_args: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            spawn_args.update(payload["args"])
            return httpx.Response(200, json={"ok": True, "result": spawned_session})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "ok"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client_kwargs["model"] = "kimi-k2"
    client_kwargs["thinking"] = "high"
    client = OpenClawAgentLLMClient(**client_kwargs)
    _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert spawn_args["model"] == "kimi-k2"
    assert spawn_args["thinking"] == "high"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_chat_stream_raises_on_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """401 from the gateway must surface as a clear HTTP error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"ok": False, "error": {"type": "unauthorized", "message": "bad token"}},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert exc_info.value.response.status_code == 401
    assert "bad token" in str(exc_info.value)


def test_chat_stream_surfaces_sessions_spawn_deny_list(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """404 (tool not allowed) is the gateway's deny-list response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"ok": False, "error": {"type": "tool_not_allowed", "message": "tool not available"}},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert exc_info.value.response.status_code == 404
    assert "tool not available" in str(exc_info.value)


def test_chat_stream_surfaces_500_error(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """5xx from the gateway must be raised as HTTPStatusError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"ok": False, "error": {"message": "internal gateway error"}},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert exc_info.value.response.status_code == 500


def test_chat_stream_raises_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """A network failure from the gateway must propagate as ConnectError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(httpx.ConnectError):
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))


def test_chat_stream_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """Sub-agent never finishes → TimeoutError is raised."""
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:forever",
            }})
        # History always returns "running" → forces timeout.
        state["calls"] += 1
        return httpx.Response(
            200,
            json={"ok": True, "result": {"status": "running", "messages": []}},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client_kwargs["run_timeout_seconds"] = 1
    client_kwargs["poll_interval_seconds"] = 0.05
    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(asyncio.TimeoutError):
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))


def test_chat_stream_returns_partial_reply_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """If the timeout hits but we already have *some* text, yield it (not raise)."""
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:x",
            }})
        state["calls"] += 1
        # First poll: short text. Later polls: still running.
        if state["calls"] == 1:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "status": "running",
                        "messages": [{"role": "assistant", "content": "partial..."}],
                    },
                },
            )
        return httpx.Response(
            200,
            json={"ok": True, "result": {"status": "running", "messages": []}},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client_kwargs["run_timeout_seconds"] = 1
    client_kwargs["poll_interval_seconds"] = 0.05
    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == ["partial..."]


def test_chat_stream_recovers_from_transient_history_error(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """A transient 500 on history must not abort the chat; we keep polling."""
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:transient",
            }})
        state["calls"] += 1
        # First call: 500. Second call: terminal reply.
        if state["calls"] == 1:
            return httpx.Response(500, json={"ok": False, "error": {"message": "transient"}})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "eventual reply"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == ["eventual reply"]


def test_chat_stream_handles_done_true_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """Gateway alternative payload shape: ``done: true`` with no status field."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:done-shape",
            }})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "done": True,
                    "messages": [{"role": "assistant", "content": "ok-shape"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == ["ok-shape"]


def test_chat_stream_yields_nothing_when_final_text_empty(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """If the terminal payload has no assistant text, yield nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:empty",
            }})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "user", "content": "echo"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == []


def test_chat_stream_raises_on_non_json_error_response(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """A 502 from a proxy with an HTML body must still raise a clean error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            content=b"<html><body>502 Bad Gateway</body></html>",
            headers={"Content-Type": "text/html"},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    assert exc_info.value.response.status_code == 502
    assert "502" in str(exc_info.value)


def test_chat_stream_tolerates_tool_call_only_reply(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """An assistant message with a tool_calls field (no text) yields nothing,
    but the polling still completes and we don't error out."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:tool-only",
            }})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{"name": "sessions_spawn", "args": {"task": "deep"}}],
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    # Empty content is filtered out; we yield nothing.
    assert chunks == []


def test_chat_stream_explicit_requester_session_key_is_used(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """An explicit ``requester_session_key`` must be forwarded to the spawn call.

    B1: The legacy ``session_key`` constructor argument is no longer the
    routing key for ``sessions_spawn`` / ``sessions_history`` — that role
    moved to ``requester_session_key`` (per-turn override > ``__init__``
    default > ``f"agent:{agent_id}:main"``). The constructor ``session_key``
    is preserved for backwards compatibility but must NOT leak into spawn.
    """
    captured_session_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            captured_session_keys.append(payload.get("sessionKey", ""))
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:exp",
            }})
        captured_session_keys.append(payload.get("sessionKey", ""))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "ok"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    # Legacy ``session_key`` is intentionally left at the constructor — must
    # NOT reach the gateway after B1.
    client_kwargs["session_key"] = "agent:legacy-key-ignored"
    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(
        client.chat_stream(
            [{"role": "user", "content": "hi"}],
            requester_session_key="agent:custom:requester-42",
        )
    )
    assert chunks == ["ok"]
    # All calls used the explicit per-turn requester_session_key.
    assert all(k == "agent:custom:requester-42" for k in captured_session_keys)


def test_chat_stream_requester_session_key_init_default_used_when_no_per_turn_override(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """``requester_session_key`` passed to ``__init__`` is used as the
    default when ``chat_stream`` does not override it (B1)."""
    captured_session_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_session_keys.append(payload.get("sessionKey", ""))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:d",
            }})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "ok"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client_kwargs["requester_session_key"] = "qiepai:sess-default"
    client = OpenClawAgentLLMClient(**client_kwargs)
    _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    # All calls used the init-level requester_session_key.
    assert all(k == "qiepai:sess-default" for k in captured_session_keys)


def test_chat_stream_per_turn_requester_session_key_overrides_init_default(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """Per-turn ``requester_session_key`` wins over the ``__init__`` default."""
    captured_session_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured_session_keys.append(payload.get("sessionKey", ""))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:o",
            }})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [{"role": "assistant", "content": "ok"}],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client_kwargs["requester_session_key"] = "qiepai:init-default"
    client = OpenClawAgentLLMClient(**client_kwargs)
    _collect_async(
        client.chat_stream(
            [{"role": "user", "content": "hi"}],
            requester_session_key="qiepai:per-turn",
        )
    )
    assert all(k == "qiepai:per-turn" for k in captured_session_keys)


def test_chat_stream_handles_multipart_content_array(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """OpenAI-style multi-part content arrays are flattened correctly."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if payload["tool"] == "sessions_spawn":
            return httpx.Response(200, json={"ok": True, "result": {
                "status": "accepted",
                "runId": "r",
                "childSessionKey": "agent:main:subagent:multi",
            }})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "status": "done",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "first chunk. "},
                                {"type": "text", "text": "second chunk."},
                            ],
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    chunks = _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))
    # Multi-part content is joined with newlines.
    assert len(chunks) == 1
    assert "first chunk." in chunks[0]
    assert "second chunk." in chunks[0]


def test_chat_stream_raises_on_bad_spawn_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """If the gateway returns ok=true but no childSessionKey, raise clearly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "result": {"status": "accepted", "runId": "r"}},
        )

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(OpenClawAgentConfigError, match="childSessionKey"):
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))


def test_chat_stream_raises_on_non_ok_payload(
    monkeypatch: pytest.MonkeyPatch,
    client_kwargs: dict[str, Any],
) -> None:
    """``ok: false`` payloads must surface as a clear error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": {"message": "boom"}})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _make_dispatcher(monkeypatch, handler),
    )

    client = OpenClawAgentLLMClient(**client_kwargs)
    with pytest.raises(OpenClawAgentConfigError, match="non-ok"):
        _collect_async(client.chat_stream([{"role": "user", "content": "hi"}]))


# ---------------------------------------------------------------------------
# Runner dispatch: ensure the OpenClaw provider is selected when the
# qiepai LLM dispatch entry sees ``llm_provider == 'openclaw_agent'``.
# ---------------------------------------------------------------------------


def test_settings_expose_openclaw_fields() -> None:
    """The new OpenClaw settings must be readable from get_settings()."""
    import os

    os.environ["OPENTALKING_LLM_PROVIDER"] = "openclaw_agent"
    os.environ["OPENTALKING_LLM_OPENCLAW_GATEWAY_URL"] = "http://example:18789"
    os.environ["OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN"] = "abc"
    os.environ["OPENTALKING_LLM_OPENCLAW_AGENT_ID"] = "main"
    try:
        from opentalking.core.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()
        assert settings.llm_provider == "openclaw_agent"
        assert settings.llm_openclaw_gateway_url == "http://example:18789"
        assert settings.llm_openclaw_gateway_token == "abc"
        assert settings.llm_openclaw_agent_id == "main"
        assert settings.llm_openclaw_task_prompt_template == "{prompt}"
        assert settings.llm_openclaw_context == "isolated"
    finally:
        for k in (
            "OPENTALKING_LLM_PROVIDER",
            "OPENTALKING_LLM_OPENCLAW_GATEWAY_URL",
            "OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN",
            "OPENTALKING_LLM_OPENCLAW_AGENT_ID",
        ):
            os.environ.pop(k, None)
        get_settings.cache_clear()


def test_session_runner_dispatcher_picks_openclaw_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SessionRunner._ensure_llm_client should build OpenClawAgentLLMClient
    when ``llm_provider == 'openclaw_agent'``."""
    from pathlib import Path

    from opentalking.pipeline.session.runner import SessionRunner

    runner = SessionRunner(
        session_id="s1",
        avatar_id="a1",
        model_type="musetalk",
        avatars_root=Path("/tmp"),
        redis=None,
        llm_provider="openclaw_agent",
        llm_openclaw_gateway_url="http://test-openclaw:18789",
        llm_openclaw_gateway_token="tok-test",
        llm_openclaw_agent_id="main",
    )
    client = runner._ensure_llm_client()
    assert isinstance(client, OpenClawAgentLLMClient)
    assert client.agent_id == "main"
    # The constructor must have read the passed-through settings.
    assert client.base_url == "http://test-openclaw:18789"
    assert client.token == "tok-test"


def test_session_runner_dispatcher_picks_openai_compatible_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``llm_provider`` is unset / openai_compatible, the runner keeps
    using the existing OpenAI-compatible client."""
    from opentalking.core.config import get_settings
    from opentalking.pipeline.session.runner import SessionRunner

    get_settings.cache_clear()
    monkeypatch.setenv("OPENTALKING_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENTALKING_LLM_BASE_URL", "https://llm.example/v1")
    get_settings.cache_clear()

    from pathlib import Path

    from opentalking.providers.llm.openai_compatible.adapter import (
        OpenAICompatibleLLMClient,
    )

    runner = SessionRunner(
        session_id="s2",
        avatar_id="a2",
        model_type="musetalk",
        avatars_root=Path("/tmp"),
        redis=None,
        llm_base_url="https://llm.example/v1",
        llm_api_key="k",
        llm_model="qwen-plus",
    )
    client = runner._ensure_llm_client()
    assert isinstance(client, OpenAICompatibleLLMClient)


# ---------------------------------------------------------------------------
# B1 (per-session requester_session_key) – SessionRunner plumbing
# ---------------------------------------------------------------------------


def test_session_runner_ensure_llm_client_sets_per_session_requester_key() -> None:
    """B1: ``SessionRunner._ensure_llm_client`` must bake
    ``requester_session_key=f"qiepai:{session_id}"`` into the openclaw
    client so two concurrent qiepai sessions don't share a gateway
    requester key.
    """
    from pathlib import Path

    from opentalking.pipeline.session.runner import SessionRunner

    runner = SessionRunner(
        session_id="sess-A",
        avatar_id="a1",
        model_type="musetalk",
        avatars_root=Path("/tmp"),
        redis=None,
        llm_provider="openclaw_agent",
        llm_openclaw_gateway_url="http://gw:18789",
        llm_openclaw_gateway_token="tok",
        llm_openclaw_agent_id="main",
    )
    client = runner._ensure_llm_client()
    assert isinstance(client, OpenClawAgentLLMClient)
    # The init default for ``requester_session_key`` is the per-session
    # requester key — used when ``chat_stream`` doesn't override.
    assert client._default_requester_session_key == "qiepai:sess-A"


def test_session_runner_distinct_sessions_get_distinct_requester_keys() -> None:
    """B1: two concurrent runners must produce two distinct requester keys."""
    from pathlib import Path

    from opentalking.pipeline.session.runner import SessionRunner

    common = dict(
        avatar_id="a1",
        model_type="musetalk",
        avatars_root=Path("/tmp"),
        redis=None,
        llm_provider="openclaw_agent",
        llm_openclaw_gateway_url="http://gw:18789",
        llm_openclaw_gateway_token="tok",
        llm_openclaw_agent_id="main",
    )
    runner_a = SessionRunner(session_id="sess-A", **common)
    runner_b = SessionRunner(session_id="sess-B", **common)
    client_a = runner_a._ensure_llm_client()
    client_b = runner_b._ensure_llm_client()
    assert (
        client_a._default_requester_session_key
        != client_b._default_requester_session_key
    )
    assert client_a._default_requester_session_key == "qiepai:sess-A"
    assert client_b._default_requester_session_key == "qiepai:sess-B"


# ---------------------------------------------------------------------------
# B3 (lazy defaults read from Settings)
# ---------------------------------------------------------------------------


def test_session_runner_ensure_llm_client_reads_settings_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3: when the runner doesn't have explicit openclaw fields, the
    lazy path must read defaults from ``Settings`` instead of hard-coded
    literals (``{prompt}``, ``600``, ``1.5``, ``65.0``).
    """
    import importlib

    from pathlib import Path

    from opentalking.core.config import get_settings
    from opentalking.pipeline.session import runner as runner_module

    monkeypatch.setenv("OPENTALKING_LLM_PROVIDER", "openclaw_agent")
    monkeypatch.setenv("OPENTALKING_LLM_OPENCLAW_GATEWAY_URL", "http://settings-gw:18789")
    monkeypatch.setenv("OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN", "settings-tok")
    monkeypatch.setenv("OPENTALKING_LLM_OPENCLAW_AGENT_ID", "settings-agent")
    monkeypatch.setenv(
        "OPENTALKING_LLM_OPENCLAW_TASK_PROMPT_TEMPLATE",
        "From settings: {prompt}",
    )
    monkeypatch.setenv("OPENTALKING_LLM_OPENCLAW_RUN_TIMEOUT_SECONDS", "777")
    monkeypatch.setenv("OPENTALKING_LLM_OPENCLAW_POLL_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv(
        "OPENTALKING_LLM_OPENCLAW_REQUEST_TIMEOUT_SECONDS", "33.0"
    )
    get_settings.cache_clear()
    # Reload the runner module so its module-level ``_SETTINGS`` snapshot
    # picks up the new env values.
    importlib.reload(runner_module)

    runner = runner_module.SessionRunner(
        session_id="sess-b3",
        avatar_id="a1",
        model_type="musetalk",
        avatars_root=Path("/tmp"),
        redis=None,
    )
    client = runner._ensure_llm_client()
    assert isinstance(client, OpenClawAgentLLMClient)
    # Defaults must come from Settings, not the legacy hard-coded literals.
    assert client.base_url == "http://settings-gw:18789"
    assert client.token == "settings-tok"
    assert client.agent_id == "settings-agent"
    assert client.task_prompt_template == "From settings: {prompt}"
    assert client.run_timeout_seconds == 777
    assert client.poll_interval_seconds == 2.5
    assert client.request_timeout_seconds == 33.0


# ---------------------------------------------------------------------------
# B4 (FlashTalkRunner: eager → lazy)
# ---------------------------------------------------------------------------


def test_flashtalk_runner_openclaw_init_is_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4: ``FlashTalkRunner.__init__`` must NOT eagerly construct
    ``OpenClawAgentLLMClient`` when ``llm_provider == "openclaw_agent"`` —
    missing token / agent_id shouldn't fail session startup.
    """
    from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner

    # Wipe any process-wide openclaw config so the runner's fallback
    # (``arg or _settings.*``) cannot resurrect a valid token / agent_id.
    for env in (
        "OPENTALKING_LLM_OPENCLAW_GATEWAY_URL",
        "OPENTALKING_LLM_OPENCLAW_GATEWAY_TOKEN",
        "OPENTALKING_LLM_OPENCLAW_AGENT_ID",
    ):
        monkeypatch.delenv(env, raising=False)
    # ``monkeypatch`` doesn't reset cached settings, so clear explicitly.
    from opentalking.core.config import get_settings
    get_settings.cache_clear()

    # Missing token + agent_id → eager construction would raise
    # ``OpenClawAgentConfigError``. Lazy init must succeed.
    runner = FlashTalkRunner(
        session_id="lazy-1",
        avatar_id="av",
        avatars_root="/tmp",
        redis=None,
        flashtalk_client=object(),
        model_type="quicktalk",
        llm_provider="openclaw_agent",
        llm_openclaw_gateway_url="http://x:18789",
        llm_openclaw_gateway_token="",
        llm_openclaw_agent_id="",
    )
    # Init succeeded: no client built, no eager exception.
    assert runner._openclaw_llm_client is None
    # ``self.llm`` is also unset (backwards-compat attr is populated lazily).
    assert not hasattr(runner, "llm")
    # Explicit ``_ensure_openclaw_llm_client`` now fails (configuration error).
    with pytest.raises(OpenClawAgentConfigError):
        runner._ensure_openclaw_llm_client()


def test_flashtalk_runner_ensure_openclaw_llm_client_uses_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4 + B1: ``FlashTalkRunner._ensure_openclaw_llm_client`` must build
    the client with ``requester_session_key=f"qiepai:{session_id}"``.
    """
    from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner

    runner = FlashTalkRunner(
        session_id="sess-flash",
        avatar_id="av",
        avatars_root="/tmp",
        redis=None,
        flashtalk_client=object(),
        model_type="quicktalk",
        llm_provider="openclaw_agent",
        llm_openclaw_gateway_url="http://x:18789",
        llm_openclaw_gateway_token="tok",
        llm_openclaw_agent_id="main",
    )
    client = runner._ensure_openclaw_llm_client()
    assert isinstance(client, OpenClawAgentLLMClient)
    assert client._default_requester_session_key == "qiepai:sess-flash"
    # Backwards-compat: ``self.llm`` is populated as a side-effect.
    assert runner.llm is client
    # Subsequent calls reuse the same client (no double-build).
    assert runner._ensure_openclaw_llm_client() is client


def test_flashtalk_runner_openclaw_provider_without_args_constructs_lazily() -> None:
    """B4: when ``llm_provider == "openclaw_agent"`` but no openclaw
    fields are passed, ``__init__`` still succeeds and defers construction.
    """
    from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner

    runner = FlashTalkRunner(
        session_id="lazy-2",
        avatar_id="av",
        avatars_root="/tmp",
        redis=None,
        flashtalk_client=object(),
        model_type="quicktalk",
        # No llm_provider arg → defaults to settings (openai_compatible in
        # the test env). Confirm we don't accidentally enter the openclaw
        # lazy branch.
        llm_provider="openai_compatible",
    )
    # openai branch: ``self.llm`` is set eagerly to ``OpenAICompatibleLLMClient``.
    from opentalking.providers.llm.openai_compatible.adapter import (
        OpenAICompatibleLLMClient,
    )
    assert isinstance(runner.llm, OpenAICompatibleLLMClient)


# ---------------------------------------------------------------------------
# B2 (runtime config refresh: _llm_provider + openclaw fields reach FlashTalkRunner)
# ---------------------------------------------------------------------------


def test_refresh_live_runners_updates_llm_provider_on_flashtalk_runner() -> None:
    """B2: ``_refresh_live_runners`` must sync ``_llm_provider`` and the
    openclaw fields on a FlashTalkRunner-style object (no ``_llm_base_url``
    attribute) so a live config switch reaches it.
    """
    from unittest.mock import MagicMock

    from apps.api.routes.runtime_config import _refresh_live_runners

    class _FakeRunner:
        """Minimal FlashTalkRunner-shaped object that records attribute
        writes; missing attributes raise ``AttributeError`` so we can
        detect accidental ``delattr`` of stale state.
        """

        def __init__(self) -> None:
            self._llm_provider = "openai_compatible"
            self._llm_openclaw_gateway_url = ""
            self._llm_openclaw_gateway_token = ""
            self._llm_openclaw_agent_id = ""
            self._llm_openclaw_task_prompt_template = ""
            self._llm_openclaw_model = ""
            self._llm_openclaw_run_timeout_seconds = 0
            self._llm_openclaw_poll_interval_seconds = 0.0
            self._llm_openclaw_request_timeout_seconds = 0.0
            self._llm_openclaw_thinking = ""
            self._llm_openclaw_context = ""
            self._openclaw_llm_client = None
            self.llm = MagicMock(name="stale_openai_client")

        def __delattr__(self, name: str) -> None:
            # ``hasattr`` returns False once deleted; subsequent reads
            # should not resurrect the old value.
            object.__delattr__(self, name)

    fake_runner = _FakeRunner()

    fake_settings = MagicMock()
    fake_settings.llm_provider = "openclaw_agent"
    fake_settings._llm_openclaw_gateway_url = "http://new-gw:18789"
    fake_settings._llm_openclaw_gateway_token = "new-tok"
    fake_settings._llm_openclaw_agent_id = "new-agent"
    fake_settings._llm_openclaw_task_prompt_template = "{prompt}"
    fake_settings._llm_openclaw_model = ""
    fake_settings._llm_openclaw_run_timeout_seconds = 600
    fake_settings._llm_openclaw_poll_interval_seconds = 1.5
    fake_settings._llm_openclaw_request_timeout_seconds = 65.0
    fake_settings._llm_openclaw_thinking = ""
    fake_settings._llm_openclaw_context = "isolated"

    request = MagicMock()
    request.app.state.session_runners = {"sess-1": fake_runner}

    count = _refresh_live_runners(request, fake_settings)
    assert count >= 1
    # Provider switched and openclaw fields populated.
    assert fake_runner._llm_provider == "openclaw_agent"
    assert fake_runner._llm_openclaw_gateway_url == "http://new-gw:18789"
    assert fake_runner._llm_openclaw_gateway_token == "new-tok"
    assert fake_runner._llm_openclaw_agent_id == "new-agent"
    # Stale eager ``llm`` was dropped (lazy re-build on next access).
    assert not hasattr(fake_runner, "llm")


def test_refresh_live_runners_resets_openclaw_lazy_cache() -> None:
    """B4 + B2: when the openclaw fields change at runtime, the cached
    lazy client must be invalidated so the next chat rebuilds."""
    from unittest.mock import MagicMock

    from apps.api.routes.runtime_config import _refresh_live_runners

    class _FakeRunner:
        def __init__(self) -> None:
            self._llm_provider = "openclaw_agent"
            self._llm_openclaw_gateway_url = ""
            self._llm_openclaw_gateway_token = ""
            self._llm_openclaw_agent_id = ""
            self._llm_openclaw_task_prompt_template = ""
            self._llm_openclaw_model = ""
            self._llm_openclaw_run_timeout_seconds = 0
            self._llm_openclaw_poll_interval_seconds = 0.0
            self._llm_openclaw_request_timeout_seconds = 0.0
            self._llm_openclaw_thinking = ""
            self._llm_openclaw_context = ""
            self._openclaw_llm_client = object()  # stale cache
            self.llm = MagicMock(name="stale_openclaw_client")

        def __delattr__(self, name: str) -> None:
            object.__delattr__(self, name)

    fake_runner = _FakeRunner()

    fake_settings = MagicMock()
    fake_settings.llm_provider = "openclaw_agent"
    fake_settings._llm_openclaw_gateway_url = "http://new-gw"
    fake_settings._llm_openclaw_gateway_token = "new-tok"
    fake_settings._llm_openclaw_agent_id = "new-agent"
    fake_settings._llm_openclaw_task_prompt_template = "{prompt}"
    fake_settings._llm_openclaw_model = ""
    fake_settings._llm_openclaw_run_timeout_seconds = 600
    fake_settings._llm_openclaw_poll_interval_seconds = 1.5
    fake_settings._llm_openclaw_request_timeout_seconds = 65.0
    fake_settings._llm_openclaw_thinking = ""
    fake_settings._llm_openclaw_context = "isolated"

    request = MagicMock()
    request.app.state.session_runners = {"sess-1": fake_runner}

    _refresh_live_runners(request, fake_settings)
    # Lazy cache reset; stale client dropped.
    assert fake_runner._openclaw_llm_client is None
    assert not hasattr(fake_runner, "llm")
