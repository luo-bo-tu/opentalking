"""qiepai · employees publish state machine (Phase ❷-6, pure module).

This module is the **single source of truth** for the digital-employee
lifecycle. It owns no DB connection, no logging side effects, and no
HTTP awareness — only transition tables + the readiness gate. That
shape mirrors ``decisions/service._STATUS_TRANSITIONS`` but extracted
into its own module because:

1. The transition graph is bigger (six states, including the "skipping"
   the spec calls out as illegal) and the readiness gate is non-trivial;
   merging it into ``service.py`` would inflate that file to >700 lines.
2. The state machine is independently testable: every public function
   here is a pure function of its inputs, so a downstream test can pin
   the rules without spinning up a SQLite DB.

State graph (架构 v1.1 § 21.5 + spec section 6.2)
=================================================

::

    draft → configuring → ready → published → suspended
                                              ↑        ↓
                                              └── retired
                  retired → published (recovery from mis-publish)

Encoded as ``_STATUS_TRANSITIONS``: a ``from → frozenset(to)`` map. Any
(from, to) not in the map (and not "no-op" same-state) raises
:class:`EmployeeStateError` — the route layer maps that to HTTP 409.

Readiness gate (架构 § 21.5 + spec section 6.2)
===============================================

Two preconditions gate the move to ``ready`` *and* ``published``:

* The active revision's ``readiness_p0`` AND ``readiness_p1`` must both
  be ``True``.
* The active revision's ``sync_state`` must NOT be ``"error"`` or
  ``"drifted"`` (``"pending"`` and ``"in_sync"`` are acceptable — the
  spec is "publish requires the workspace to be in a known-good state").

Encoded as :func:`check_readiness_for_publish` so the router / service
share a single enforcement point.
"""
from __future__ import annotations

from typing import Any, Final


#: Allowed ``from -> {to, ...}`` transitions for ``employees.status``.
#: Terminal-ish states (``retired``) only allow the explicit recovery path
#: ``retired → published`` per spec section 6.2 "反向也可 retired→published
#: if 误操作". ``published`` allows ``published → suspended`` and
#: ``published → retired``; ``suspended`` allows ``suspended → retired``
#: and ``suspended → published`` (re-publish after a temporary halt).
_STATUS_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"configuring", "retired"}),
    "configuring": frozenset({"ready", "draft", "retired"}),
    "ready": frozenset({"published", "configuring", "retired"}),
    "published": frozenset({"suspended", "retired"}),
    "suspended": frozenset({"published", "retired"}),
    "retired": frozenset({"published"}),
}

#: Valid ``status`` values for new employees + filter parameter.
_VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {"draft", "configuring", "ready", "published", "suspended", "retired"}
)

#: States from which an employee cannot be PATCHED to a different status
#: *at all* (still allows same-status no-op). Reserved for future use —
#: currently every state has at least one outbound transition.
_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset()

#: ``sync_state`` values that block the ``ready`` and ``published`` moves.
#: ``pending`` is allowed (a fresh revision hasn't been synced yet — the
#: initial ``draft`` → ``configuring`` flow doesn't need a sync); once
#: the operator signals it's good, they call the (future) sync endpoint
#: which transitions ``sync_state`` to ``in_sync``.
_BLOCKING_SYNC_STATES: Final[frozenset[str]] = frozenset({"error", "drifted"})


class EmployeeStateError(RuntimeError):
    """Raised when a status transition violates the state machine (HTTP 409)."""


class EmployeeValidationError(ValueError):
    """Raised when the readiness gate fails (HTTP 422)."""


def is_valid_status(status: str) -> bool:
    """Return True iff ``status`` is one of the six known employee states."""
    return status in _VALID_STATUSES


def can_transition(current: str, target: str) -> bool:
    """Return True iff ``current -> target`` is a legal transition.

    Same-state transitions (``current == target``) are always allowed —
    PATCH bodies frequently re-affirm the current status, and rejecting
    those would force every UI to no-op them server-side.
    """
    if current == target:
        return True
    return target in _STATUS_TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    """Raise :class:`EmployeeStateError` iff ``current -> target`` is illegal.

    On illegal transitions the error message lists the allowed targets so
    the UI / operator gets a self-explaining 409.
    """
    if can_transition(current, target):
        return
    allowed = sorted(_STATUS_TRANSITIONS.get(current, frozenset()))
    raise EmployeeStateError(
        f"illegal status transition {current!r} -> {target!r}; "
        f"allowed: {allowed or 'none (terminal)'}"
    )


def check_readiness_for_publish(revision: dict[str, Any], target: str) -> None:
    """Validate the readiness gate before allowing a move to ``target``.

    The gate fires only when ``target`` is ``"ready"`` or ``"published"``;
    other transitions (e.g. ``draft → configuring``,
    ``configuring → draft``) are unconstrained by readiness — they reflect
    operator intent, not a deploy.

    Two checks (spec section 6.2):

    1. ``readiness_p0`` AND ``readiness_p1`` must both be truthy.
    2. ``sync_state`` must NOT be ``"error"`` or ``"drifted"``.

    Raises :class:`EmployeeValidationError` (HTTP 422) on either failure.
    The message is human-readable so the route can pass it through to
    the operator verbatim.
    """
    if target not in {"ready", "published"}:
        return

    # SQLite stores booleans as ints (0/1). Normalize so callers passing
    # either form get the same answer.
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return bool(value)

    if not _truthy(revision.get("readiness_p0")) or not _truthy(revision.get("readiness_p1")):
        raise EmployeeValidationError(
            f"readiness_p0/p1 required for status={target!r}; "
            f"got readiness_p0={revision.get('readiness_p0')!r}, "
            f"readiness_p1={revision.get('readiness_p1')!r}"
        )
    sync_state = revision.get("sync_state")
    if sync_state in _BLOCKING_SYNC_STATES:
        raise EmployeeValidationError(
            f"sync_state {sync_state!r} blocks status={target!r}; "
            f"resolve the sync error before retrying"
        )


__all__ = [
    "EmployeeStateError",
    "EmployeeValidationError",
    "is_valid_status",
    "can_transition",
    "assert_transition",
    "check_readiness_for_publish",
]
