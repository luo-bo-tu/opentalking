"""qiepai · KPI snapshot loader (Phase ❷-3).

The loader is the **only** piece of code the cockpit route (❷-4) and the
seed step (this phase) call to materialise a metric's point-in-time
value. It deliberately hides the connector abstraction from callers so
business code can stay connector-agnostic.

Returned shape
==============

Every successful ``read`` returns a dict with exactly four keys:

* ``value``              — ``float | int | None``
* ``as_of``              — ISO 8601 string (preserved verbatim from the mock JSON)
* ``freshness_seconds``  — ``int`` (preserved verbatim; UI checks > 86400 for "stale")
* ``source``             — ``str`` (e.g. ``"mock://financial-kpi/v1"``)

Plus, when present in the underlying mock payload, ``items`` is forwarded
as-is (the loader does **not** validate the items schema — that is the
cockpit route's responsibility in ❷-4 once a chart shape is locked in).
Forwarding untyped JSON avoids re-parsing the same file twice.

Three-state contract (spec § 3.2)
=================================

The loader does not decide what to *render* — it only returns the data.
The three states are computed downstream by the UI from these signals:

* ``value is None``                           → "数据暂不可用"
* ``freshness_seconds > 86400``               → "过期"
* ``connector.probe()['state'] == 'error'``   → "数据源异常"

Loader behaviour per state:

* Connector missing → ``None`` (caller treats as unavailable; no exception
  raised so a single missing KPI does not 500 the whole cockpit page).
* Connector IO / JSON error → ``None`` (same reason; detail is logged).
* Connector OK, payload malformed (missing required keys) → ``None``
  + ``log.warning`` so the operator can spot a half-edited mock.
* Connector OK, payload well-formed → returns the four-key dict.

Returning ``None`` instead of raising is a deliberate choice for ❷-3.
The UI contract says "unavailable is a first-class state, not an error",
so the loader mirrors that semantics. Routes can always wrap the call
in ``try``/``except`` if they need an error path later.
"""
from __future__ import annotations

import logging
from typing import Any, Final

from apps.api.services.qiepai.connectors import (
    UnknownConnectorError,
    get_connector,
)

log = logging.getLogger(__name__)

#: Required keys on the mock JSON payload. Missing any of these means the
#: loader returns ``None`` and logs a warning rather than handing back a
#: half-formed dict that would crash the cockpit UI.
_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "source",
    "as_of",
    "freshness_seconds",
    "value",
)


async def load_kpi_snapshot(metric_id: str, scope: str = "default") -> dict[str, Any] | None:
    """Return a normalised KPI snapshot for ``metric_id``, or ``None`` if unavailable.

    Parameters
    ----------
    metric_id
        Key into ``MOCK_CONNECTORS`` (matches the JSON filename stem).
    scope
        Free-form scope label (``"default"`` for enterprise-wide values;
        a dept / team / person id for narrower scopes). Currently the
        loader only logs the scope — actual per-scope filtering happens
        in ❷-4 once the cockpit route decides which scope to display.
        Kept in the signature now so ❷-4 callers do not have to change
        the loader contract.

    Returns
    -------
    dict | None
        ``{value, as_of, freshness_seconds, source, [items]}`` on success,
        ``None`` if the connector is unknown, IO failed, JSON malformed,
        or any required key is missing.
    """
    try:
        connector = get_connector(metric_id)
    except UnknownConnectorError as exc:
        log.warning("load_kpi_snapshot(%s): %s", metric_id, exc)
        return None

    try:
        payload = await connector.read()
    except (OSError, ValueError) as exc:  # FileNotFoundError ⊂ OSError; JSONDecodeError ⊂ ValueError
        log.warning("load_kpi_snapshot(%s): connector read failed: %s", metric_id, exc)
        return None

    for key in _REQUIRED_KEYS:
        if key not in payload:
            log.warning(
                "load_kpi_snapshot(%s): payload missing required key %r; treating as unavailable",
                metric_id,
                key,
            )
            return None

    snapshot: dict[str, Any] = {
        "value": payload["value"],
        "as_of": payload["as_of"],
        "freshness_seconds": payload["freshness_seconds"],
        "source": payload["source"],
    }
    if "items" in payload:
        snapshot["items"] = payload["items"]
    # ``scope`` is intentionally not stored on the returned snapshot —
    # the snapshot is a property of the metric, not the caller. Routes
    # that need per-scope labelling can attach the scope label separately.
    log.debug("load_kpi_snapshot(%s, scope=%s): ok", metric_id, scope)
    return snapshot


__all__ = ["load_kpi_snapshot"]
