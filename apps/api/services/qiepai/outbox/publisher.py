"""qiepai · Feishu webhook publisher (Phase ❸-1).

Turns :class:`OutboxEventDraft` payloads into Feishu interactive-card
messages and POSTs them to the
``https://open.feishu.cn/open-apis/im/v1/messages`` endpoint. This
module owns **all** outbound HTTP — the worker only ever calls
:func:`publish_outbox_event`.

Credential handling
===================

* App id + app secret are loaded from typed config
  (:mod:`apps.api.services.qiepai.integrations.feishu_settings`)
  which reads ``QIEPAI_FEISHU_APP_ID`` + ``QIEPAI_FEISHU_APP_SECRET``.
  We never read OpenClaw gateway secrets — that's a sibling concern.
* The ``tenant_access_token`` is fetched on demand and cached in
  process memory. TTL = ``expire`` seconds returned by Feishu minus a
  60-second safety margin (so a slow HTTP call doesn't push us past
  the server-side expiry). A cache miss under a network error is
  surfaced as a :class:`PublishError` so the worker can back off.
* If credentials are missing the publisher enters **dry-run** mode:
  every message is logged + a fake ``feishu_dry_run`` dispatch record
  is appended to ``outbox_events.last_error`` so the operator can
  audit what *would* have been sent. This is the demo-mode contract
  for environments without a real 飞书 app (e.g. CI / local dev).

Card templates
==============

Each event_type has a tiny builder branch in :func:`_render_card` that
emits a Feishu interactive-card JSON. The card layout is a 1-section
template with header + up-to-6 plain-text fields; intentionally
minimal so we don't have to maintain a deep card schema. Adding a
new event type = add a new branch in :func:`_label_for_event` and
(optionally) a new field pair.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from ..integrations.feishu_settings import feishu_settings
from .events import EVENT_TYPES, build_event_payload

log = logging.getLogger(__name__)


#: Feishu API base + tenant_access_token endpoint.
FEISHU_BASE: Final[str] = "https://open.feishu.cn/open-apis"
FEISHU_TOKEN_URL: Final[str] = f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal"
FEISHU_MESSAGE_URL: Final[str] = (
    f"{FEISHU_BASE}/im/v1/messages?receive_id_type=chat_id"
)

#: Network IO budget for both endpoints (Feishu recommends < 5s for the
#: tenant_access_token endpoint + < 10s for the message endpoint; we
#: take the conservative union at 10s).
HTTP_TIMEOUT_S: Final[float] = 10.0


class PublishError(RuntimeError):
    """Raised when a delivery attempt failed and should be retried.

    Two error shapes exist:

    * **retryable** (``status_code is None or 429 or >= 500``) — the
      worker bumps ``attempts`` and reschedules with exponential backoff.
    * **permanent** (``status_code in 400..499 excluding 429``) — the
      worker marks the row ``state='failed'`` immediately.

    :func:`publish_outbox_event` does NOT distinguish; it always raises
    PublishError so the worker can implement its own retry policy via
    the ``status_code`` attribute. The default policy is "retry until
    attempts>=5".
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        # Auto-derive retryable from status_code when not explicitly given.
        if retryable is None:
            retryable = status_code is None or status_code == 429 or status_code >= 500
        self.retryable = bool(retryable)


# ---------------------------------------------------------------------------
# Tenant access token cache
# ---------------------------------------------------------------------------


@dataclass
class _TokenCache:
    """Process-local cache for the Feishu ``tenant_access_token``.

    A single shared cache is fine here: the publisher is invoked by the
    worker loop, which is single-task per process. Concurrent callers
    (a future REST endpoint that fires one-off messages) would contend
    briefly but the request count is tiny (single enterprise demo).
    """

    token: str = ""
    expires_at: float = 0.0  # epoch seconds
    last_refresh_at: float = 0.0

    def is_fresh(self, now: float) -> bool:
        """True iff the cached token is still good for at least 60s."""
        return bool(self.token) and now < (self.expires_at - 60.0)


_TOKEN: _TokenCache = _TokenCache()


def _reset_token_cache_for_tests() -> None:
    """Test helper — call before each test to discard the cached token."""
    global _TOKEN
    _TOKEN = _TokenCache()


async def _fetch_tenant_token(
    client: httpx.AsyncClient,
    *,
    app_id: str,
    app_secret: str,
) -> tuple[str, int]:
    """Hit the token endpoint with the supplied credentials.

    Returns ``(token, expire_seconds)``. Raises :class:`PublishError`
    (retryable) on any IO / non-200 response. A 200-with-bad-body
    raises a permanent PublishError so the operator notices the
    misconfiguration immediately (no point retrying — same response
    will come back).
    """
    try:
        resp = await client.post(
            FEISHU_TOKEN_URL,
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=HTTP_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise PublishError(f"token endpoint transport error: {exc}") from exc
    if resp.status_code != 200:
        raise PublishError(
            f"token endpoint http {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )
    try:
        body = resp.json()
    except ValueError as exc:
        raise PublishError(
            f"token endpoint returned non-JSON: {exc}", retryable=False
        ) from exc
    code = body.get("code")
    if code not in (0, None):
        raise PublishError(
            f"token endpoint Feishu code {code}: {body.get('msg')!r}",
            retryable=False,
        )
    token = body.get("tenant_access_token") or ""
    expire = int(body.get("expire") or 0)
    if not token or expire <= 0:
        raise PublishError(
            "token endpoint missing tenant_access_token/expire",
            retryable=False,
        )
    return token, expire


async def _get_token(client: httpx.AsyncClient, *, force: bool = False) -> str:
    """Return a usable tenant_access_token, refreshing as needed.

    If credentials are not configured the call returns an empty string
    + logs once; the caller (publisher) then takes the dry-run branch.
    """
    creds = feishu_settings()
    if not creds.app_id or not creds.app_secret:
        return ""
    now = time.monotonic()
    if not force and _TOKEN.is_fresh(now):
        return _TOKEN.token
    token, expire = await _fetch_tenant_token(
        client,
        app_id=creds.app_id,
        app_secret=creds.app_secret,
    )
    _TOKEN.token = token
    _TOKEN.expires_at = now + expire
    _TOKEN.last_refresh_at = now
    log.debug(
        "outbox.publisher: refreshed tenant_access_token ttl=%ds", expire
    )
    return token


# ---------------------------------------------------------------------------
# Card renderer
# ---------------------------------------------------------------------------


_CARD_TONE: Final[dict[str, str]] = {
    # aggregate_type → header template colour (Feishu limited palette)
    "employee": "blue",
    "decision": "purple",
    "task": "orange",
    "kpi": "red",
    "system": "grey",
}


def _label_for_event(event_type: str) -> str:
    """Human-readable Chinese label for the Feishu card header."""
    return {
        "employee.published": "数字员工已发布",
        "employee.failed_publish": "数字员工发布失败",
        "decision.created": "新决策项",
        "decision.decided": "决策已闭环",
        "decision.cancelled": "决策已取消",
        "task.assigned": "新业务任务",
        "task.completed": "业务任务已完成",
        "task.cancelled": "业务任务已取消",
        "kpi.anomaly": "KPI 异常告警",
        "kpi.freshness_warning": "KPI 数据过期",
        "system.demo_notify": "系统演示通知",
        "system.heartbeat": "飞书通道心跳",
    }.get(event_type, event_type)


def _safe_str(payload: dict[str, Any], key: str) -> str:
    """Helper: safely format a payload field, falling back to ``"-"``."""
    val = payload.get(key)
    if val is None or val == "":
        return "-"
    if isinstance(val, bool):
        return "是" if val else "否"
    return str(val)


def _render_card(body: dict[str, Any]) -> dict[str, Any]:
    """Translate a payload dict into a Feishu interactive-card body.

    Structure: ``header`` (title + colour) + ``elements`` array with up
    to 6 fields. Unknown fields are silently ignored so an old worker
    receiving a future-shaped payload still renders.

    Why interactive cards (not plain text)?
    ---------------------------------------

    Plain text messages carry less signal in the chat preview and lose
    Feishu's "title / colour" affordances; cards keep the message
    compact and the team can mute individual titles later if the noise
    gets too loud.
    """
    event_type = str(body.get("_event_type", ""))
    aggregate_type = str(body.get("_aggregate_type", "system"))
    title = _label_for_event(event_type)
    tone = _CARD_TONE.get(aggregate_type, "blue")

    fields: list[dict[str, Any]] = []

    def _maybe(key: str, label: str) -> None:
        if key in body and body[key] not in (None, ""):
            fields.append(
                {
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{label}:** {_safe_str(body, key)}",
                    },
                }
            )

    _maybe("display_name", "员工")
    _maybe("role", "角色")
    if "decision_title" in body:
        _maybe("decision_title", "标题")
    elif "title" in body:
        _maybe("title", "标题")
    _maybe("decision_text", "决策文本")
    _maybe("task_title", "任务")
    _maybe("assignee_id", "指派")
    _maybe("metric_name", "指标")
    if "metric_value" in body:
        unit = body.get("unit") or ""
        # Combine into a single short field so the card stays compact.
        val = _safe_str(body, "metric_value")
        fields.append(
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**当前值:** {val}{(' ' + unit) if unit else ''}",
                },
            }
        )
    _maybe("threshold", "阈值")
    _maybe("message", "消息")

    # Always render the aggregate_id so the operator can deep-link.
    fields.append(
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**id:** `{body.get('_aggregate_id', '-')}`",
            },
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": tone,
        },
        "elements": [
            {"tag": "div", "fields": fields[:6]},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"qiepai · {event_type or 'unknown'}",
                    }
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public publisher entry point
# ---------------------------------------------------------------------------


async def publish_outbox_event(
    client: httpx.AsyncClient | None,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload_text: str,
    chat_id: str,
) -> dict[str, Any]:
    """Deliver a single outbox row to Feishu.

    Returns a result dict ``{"ok": bool, "mode": "live"|"dry_run"|"skipped",
    "info": ...}``. **Always** raises :class:`PublishError` on a failed
    live delivery so the worker can record ``last_error`` and back off.

    Parameters
    ----------
    client
        An optional shared ``httpx.AsyncClient``. ``None`` triggers the
        publisher to create + tear down its own client per call (used by
        tests). Production callers pass a long-lived client from the
        worker.
    chat_id
        The Feishu ``chat_id`` of the target group. Pulled from the
        ``feishu_groups`` registry by the worker when it pops an event;
        a missing chat_id falls through to dry-run + a log line so the
        worker doesn't pile up failed rows in tests.
    event_type
    aggregate_type
    aggregate_id
    payload_text
        Mirrors the ``outbox_events`` table columns verbatim; the
        publisher never re-reads the DB.
    """
    body = build_event_payload(event_type, aggregate_type, aggregate_id, payload_text)

    if client is not None:
        return await _dispatch(client, body, chat_id, event_type)
    async with httpx.AsyncClient() as owned_client:
        return await _dispatch(owned_client, body, chat_id, event_type)


async def _dispatch(
    actual_client: httpx.AsyncClient,
    body: dict[str, Any],
    chat_id: str,
    event_type: str,
) -> dict[str, Any]:
    creds = feishu_settings()

    # 1. Dry-run when credentials or chat_id are missing.
    if not creds.app_id or not creds.app_secret or not chat_id:
        mode = "dry_run"
        if event_type not in EVENT_TYPES:
            mode = "skipped"
        log.info(
            "outbox.publisher: %s event_type=%s chat_id=%s payload=%s",
            mode,
            event_type,
            chat_id or "(none)",
            json.dumps(body, ensure_ascii=False)[:200],
        )
        return {"ok": True, "mode": mode, "info": "no credentials or chat_id"}

    token = await _get_token(actual_client)
    card = _render_card(body)
    content_text = json.dumps(card, ensure_ascii=False)
    feishu_body: dict[str, Any] = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": content_text,
    }

    try:
        resp = await actual_client.post(
            FEISHU_MESSAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=feishu_body,
            timeout=HTTP_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise PublishError(f"message endpoint transport error: {exc}") from exc

    if resp.status_code >= 400:
        raise PublishError(
            f"message endpoint http {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
            response_body=resp.text[:500],
        )
    try:
        parsed = resp.json()
    except ValueError:
        # Non-JSON success body — could be a proxy stripping the
        # Content-Type. Treat as 200 + log a warning so we don't
        # retry something that already worked.
        log.warning(
            "outbox.publisher: message endpoint 2xx but non-JSON body: %s",
            resp.text[:200],
        )
        return {"ok": True, "mode": "live", "info": "non-json body"}

    code = parsed.get("code")
    if code not in (0, None):
        # Feishu returns 200 + business code on most 4xx-style failures.
        # Treat code != 0 as a publish error.
        raise PublishError(
            f"message endpoint Feishu code {code}: {parsed.get('msg')!r}",
            status_code=resp.status_code,
            response_body=resp.text[:500],
            retryable=False,
        )
    return {"ok": True, "mode": "live", "info": parsed.get("msg") or "ok"}


def reset_for_tests() -> None:
    """Drop the in-process token cache (test helper)."""
    _reset_token_cache_for_tests()


__all__ = [
    "FEISHU_BASE",
    "FEISHU_TOKEN_URL",
    "FEISHU_MESSAGE_URL",
    "HTTP_TIMEOUT_S",
    "PublishError",
    "publish_outbox_event",
    "reset_for_tests",
]
