"""qiepai · marketplace service (Phase ❹).

Single business-layer module backing
``apps/api/routes/qiepai/marketplace.py``. Owns:

* ``scene_templates`` table CRUD (list / get / create / patch / soft-delete).
* ``scene_template_ratings`` writes (insert / upsert-by-(template,user)) +
  denormalised ``rating_avg`` / ``rating_count`` recompute on the parent.
* ``scene_template_copies`` writes + the **copy flow** that materialises
  a template's ``payload`` into a new ``employees`` + ``employee_revisions``
  pair via the existing ❷-6 ``employees.service`` API.

Why one file
============

The marketplace service is structurally smaller than decisions/employees:
a flat CRUD on three tables with no state machine. Splitting it across
``crud.py`` + ``ratings.py`` + ``copies.py`` would inflate the import
graph without unlocking any independence. We can split if it ever
crosses ~500 lines.

Cross-revision atomicity
========================

The rating-insert path performs three writes in one transaction:

1. ``INSERT OR REPLACE`` into ``scene_template_ratings`` (the
   ``UNIQUE(template_id, user_id)`` constraint enforces "one rating
   per user" — re-rating replaces the previous row).
2. ``SELECT AVG(rating), COUNT(*) FROM scene_template_ratings WHERE template_id = ?``
   so the denormalised ``rating_avg`` / ``rating_count`` columns on
   the parent ``scene_templates`` row match the truth.

A crash mid-rating cannot leave ``rating_avg`` out of sync with the
underlying rows because the parent UPDATE happens inside the same
transaction.

Copy flow (spec ❹ section 6)
=============================

The copy endpoint materialises a template into a real digital employee
by *delegating* to the existing ❷-6 ``employees.service`` API rather
than re-implementing the employee + revision creation:

* Step 1 — Read ``template.payload`` (a dict).
* Step 2 — Call ``employees.service.create_employee`` with a derived
  ``display_name`` (``"{template.name} (副本)"``) and ``role``
  (``"数字员工"``); fall through if the operator pre-supplied a
  ``target_employee_id`` so we don't create a second employee.
* Step 3 — Call ``employees.service.create_revision`` with
  ``workspace_file_hash = "sha256:marketplace-copy-<template_id>"``
  and ``config_snapshot = template.payload``. ``employees.service``
  auto-assigns ``revision_number`` and stamps ``created_at``.
* Step 4 — Insert ``scene_template_copies`` row + bump
  ``scene_templates.use_count``.

The whole sequence runs inside ``asyncio.to_thread`` wrappers on the
business functions; the *intermediate* ``INSERT``s inside
``employees.service`` are each their own transaction (matches the ❷-6
contract), so a crash between step 2 and step 3 leaves the partial
employee visible (the operator can drop it manually) but never leaves
a dangling ``scene_template_copies`` row referencing a non-existent
template — the FK does the bookkeeping.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import Any, Final
from uuid import uuid4

from .. import db
from .seed import SEED_TEMPLATES

log = logging.getLogger(__name__)


#: Default ``enterprise_id`` for the single-tenant demo (拿不准点 #1, 架构
#: v1.1 § P0-D 条目 1). Mirrors :data:`apps.api.services.qiepai.employees.service.DEFAULT_ENTERPRISE_ID`
#: and :data:`apps.api.services.qiepai.decisions.service.DEFAULT_ENTERPRISE_ID`.
DEFAULT_ENTERPRISE_ID: Final[str] = "huilton_seed"

#: Allowed categories per spec ❹ section 1 (whitelist + forward-compat).
#: Unknown categories are accepted but logged so operators can spot typos;
#: the spec lists 5 canonical buckets but the demo may introduce new ones
#: later (e.g. "marketing" / "legal") without a code change.
_KNOWN_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"customer_service", "sales", "finance", "hr", "ops"}
)

#: Sort modes for the list endpoint. ``popular`` orders by the
#: denormalised aggregates (descending); ``recent`` orders by
#: ``created_at`` (descending).
_VALID_SORTS: Final[frozenset[str]] = frozenset({"popular", "recent"})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TemplateNotFoundError(LookupError):
    """Raised when a scene_template id query yields no row (HTTP 404)."""


class TemplateValidationError(ValueError):
    """Raised when an incoming body is structurally invalid (HTTP 422)."""


class TemplateConflictError(RuntimeError):
    """Raised when a rating insert collides on ``UNIQUE(template_id, user_id)``
    without an explicit upsert path (HTTP 409).

    In ❹ v1 we surface this as a 409 so the UI can prompt "你已评分, 是否覆盖"
    rather than silently overwriting — the demo operator can then PATCH
    the existing rating via a follow-up endpoint if we add one in ❹+.
    """


class TargetEmployeeNotFoundError(LookupError):
    """Raised when the operator-supplied ``target_employee_id`` does not
    exist (HTTP 404)."""


# ---------------------------------------------------------------------------
# DB read / write helpers (sync — called inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a ``scene_templates`` sqlite3.Row into a JSON-safe dict.

    Decodes ``payload`` + ``tags`` (both TEXT JSON columns) so the API
    returns real dicts / lists rather than stringified blobs. A corrupt
    JSON blob passes through as the original string + a warning (matches
    the decisions / employees contract).
    """
    out = dict(row)
    for key in ("payload", "tags"):
        raw = out.get(key)
        if isinstance(raw, str) and raw:
            try:
                out[key] = json.loads(raw)
            except ValueError:
                log.warning(
                    "marketplace: %s JSON parse failed for row %r",
                    key,
                    out.get("id"),
                )
    if out.get("industry") is None:
        out["industry"] = None  # B1: explicit industry: str | None contract
    return out


def _rating_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Pass-through for ``scene_template_ratings`` rows (no JSON columns)."""
    return dict(row)


def _copy_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Pass-through for ``scene_template_copies`` rows (no JSON columns)."""
    return dict(row)


def _list_sync(
    *,
    enterprise_id: str,
    category: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Read the marketplace templates list (sync).

    Excludes ``enabled = 0`` (soft-deleted) by default. Sort defaults to
    ``popular`` (``rating_avg DESC, use_count DESC, created_at DESC``);
    ``recent`` flips to ``created_at DESC``. Pagination is
    ``limit / offset`` with a hard cap on ``limit`` enforced by the
    caller so this function trusts its inputs.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        sql = (
            "SELECT id, enterprise_id, name, description, category, industry, "
            "tags, source, enabled, created_by, created_at, updated_at, "
            "use_count, rating_avg, rating_count "
            "FROM scene_templates WHERE enabled = 1 AND enterprise_id = ?"
        )
        params: list[Any] = [enterprise_id]
        if category is not None:
            sql += " AND category = ?"
            params.append(category)
        if sort == "recent":
            sql += " ORDER BY created_at DESC, id DESC"
        else:
            sql += " ORDER BY rating_avg DESC, use_count DESC, created_at DESC, id DESC"
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def _get_sync(template_id: str) -> dict[str, Any]:
    """Read a single template by id (including ``payload``)."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, enterprise_id, name, description, category, industry, "
            "payload, tags, source, enabled, created_by, created_at, updated_at, "
            "use_count, rating_avg, rating_count "
            "FROM scene_templates WHERE id = ?",
            (template_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise TemplateNotFoundError(template_id)
    return _row_to_dict(row)


def _insert_sync(
    *,
    enterprise_id: str,
    name: str,
    description: str | None,
    category: str,
    industry: str | None,
    payload: dict[str, Any],
    tags: list[str] | None,
    source: str,
    enabled: int,
    created_by: str | None,
) -> dict[str, Any]:
    """Insert a new template row (sync)."""
    conn = db.connect()
    try:
        # Forward-reference dance: ``enterprise_spaces`` is empty in the
        # single-tenant demo so the FK check would block us. Mirror the
        # decisions/employees services' pattern.
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        new_id = f"stpl_{uuid4().hex[:12]}"
        try:
            cur.execute(
                "INSERT INTO scene_templates ("
                "  id, enterprise_id, name, description, category, industry,"
                "  payload, tags, source, enabled, created_by"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id,
                    enterprise_id,
                    name,
                    description,
                    category,
                    industry,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False) if tags is not None else None,
                    source,
                    enabled,
                    created_by,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise TemplateValidationError(f"invalid template row: {exc}") from exc
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()
    return _get_sync(new_id)


def _patch_sync(
    template_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    industry: str | None = None,
    payload: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    enabled: int | None = None,
) -> dict[str, Any]:
    """Apply a partial update (sync). ``created_by`` / ``source`` /
    ``enterprise_id`` are immutable post-create — the route layer
    silently drops them from the body so demo callers don't get
    surprising schema-bending behaviour.
    """
    conn = db.connect()
    try:
        cur = conn.cursor()
        # Verify the row exists first so PATCH on an unknown id returns
        # 404 (not "0 rows affected").
        cur.execute("SELECT id FROM scene_templates WHERE id = ?", (template_id,))
        if cur.fetchone() is None:
            raise TemplateNotFoundError(template_id)

        updates: list[str] = []
        params: list[Any] = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if industry is not None:
            updates.append("industry = ?")
            params.append(industry)
        if payload is not None:
            updates.append("payload = ?")
            params.append(json.dumps(payload, ensure_ascii=False))
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)

        if not updates:
            raise TemplateValidationError(
                "PATCH body must include at least one of: "
                "name, description, category, industry, payload, tags, enabled"
            )

        # Always bump ``updated_at`` so the list endpoint's "recent" sort
        # reflects the last admin edit.
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(template_id)
        cur.execute(
            f"UPDATE scene_templates SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()
    return _get_sync(template_id)


def _soft_delete_sync(template_id: str) -> dict[str, Any]:
    """Set ``enabled = 0`` (soft delete) so the row stays for audit
    but disappears from the public list.
    """
    return _patch_sync(template_id, enabled=0)


def _insert_rating_sync(
    template_id: str,
    *,
    user_id: str | None,
    rating: int,
    comment: str | None,
) -> dict[str, Any]:
    """Insert (or replace, on UNIQUE collision) a rating row + recompute
    the denormalised aggregates on the parent template.

    The unique-collision path is treated as an *update* rather than a
    409: re-rating is a normal flow for the demo operator (they fix
    typos or change their mind). The ❹ spec is silent on this; we pick
    upsert over 409 because (a) it's friendlier to the UI, and (b) the
    UNIQUE constraint guarantees we never accumulate ghost rows.
    """
    if not (1 <= rating <= 5):
        raise TemplateValidationError(
            f"rating must be an integer between 1 and 5; got {rating!r}"
        )

    new_id = f"rt_{uuid4().hex[:12]}"
    conn = db.connect()
    try:
        # FK check on ``template_id`` should fire here — the parent row
        # must exist before we accept a rating. We keep FK ON for this
        # transaction (no forward-reference dance needed) so a bad
        # template_id surfaces as a real 404 before we touch ratings.
        cur = conn.cursor()
        cur.execute("SELECT id FROM scene_templates WHERE id = ?", (template_id,))
        if cur.fetchone() is None:
            raise TemplateNotFoundError(template_id)

        # ``INSERT OR REPLACE`` so re-rating replaces the previous row.
        # The UNIQUE(template_id, user_id) index picks the conflict.
        cur.execute(
            "INSERT OR REPLACE INTO scene_template_ratings ("
            "  id, template_id, user_id, rating, comment, created_at"
            ") VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (new_id, template_id, user_id, rating, comment),
        )
        # Recompute aggregates. Note: ``INSERT OR REPLACE`` keeps the
        # primary key (``id``) the same when there's no conflict, so
        # for a *first* rating we just inserted the row with
        # ``id = new_id``; for a *re-rating* we inserted a fresh row
        # under ``new_id`` AND deleted the old row by the same
        # ``(template_id, user_id)`` pair — so the COUNT below always
        # reflects the current distinct-user count.
        cur.execute(
            "SELECT COALESCE(AVG(rating), 0) AS avg_r, COUNT(*) AS cnt "
            "FROM scene_template_ratings WHERE template_id = ?",
            (template_id,),
        )
        agg = cur.fetchone()
        avg_r = float(agg["avg_r"] or 0)
        cnt = int(agg["cnt"] or 0)
        cur.execute(
            "UPDATE scene_templates SET rating_avg = ?, rating_count = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (round(avg_r, 4), cnt, template_id),
        )
        conn.commit()

        # Read back the rating row we just wrote.
        cur.execute(
            "SELECT id, template_id, user_id, rating, comment, created_at "
            "FROM scene_template_ratings WHERE id = ?",
            (new_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        # Defensive: should never happen — the INSERT just succeeded.
        raise TemplateNotFoundError(template_id)
    return _rating_row_to_dict(row)


def _list_copies_sync(template_id: str) -> list[dict[str, Any]]:
    """List copy records for a template (newest first)."""
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, template_id, copied_by, target_employee_id, created_at "
            "FROM scene_template_copies WHERE template_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (template_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [_copy_row_to_dict(r) for r in rows]


def _record_copy_sync(
    template_id: str,
    *,
    copied_by: str | None,
    target_employee_id: str,
) -> dict[str, Any]:
    """Insert a copy audit row + bump ``use_count`` on the parent.

    Returns the inserted copy row. Atomic per-row (single transaction):
    the copy row + the parent's ``use_count`` UPDATE both commit or
    neither does — a partial crash cannot leave ``use_count`` ahead of
    the actual audit trail.
    """
    new_id = f"cp_{uuid4().hex[:12]}"
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM scene_templates WHERE id = ?", (template_id,))
        if cur.fetchone() is None:
            raise TemplateNotFoundError(template_id)
        try:
            cur.execute(
                "INSERT INTO scene_template_copies ("
                "  id, template_id, copied_by, target_employee_id"
                ") VALUES (?, ?, ?, ?)",
                (new_id, template_id, copied_by, target_employee_id),
            )
        except sqlite3.IntegrityError as exc:
            raise TemplateValidationError(f"invalid copy row: {exc}") from exc
        cur.execute(
            "UPDATE scene_templates SET use_count = use_count + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (template_id,),
        )
        conn.commit()
        cur.execute(
            "SELECT id, template_id, copied_by, target_employee_id, created_at "
            "FROM scene_template_copies WHERE id = ?",
            (new_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise TemplateNotFoundError(template_id)
    return _copy_row_to_dict(row)


def _seed_builtin_sync(payloads: list[dict[str, Any]]) -> int:
    """Insert (or skip) the builtin template rows.

    Uses ``INSERT OR IGNORE`` keyed by the deterministic ``id`` set in
    :mod:`.seed` so a re-run is a no-op. Returns the number of rows
    newly inserted (0 on every call after the first).

    Forward-reference dance: ``enterprise_id`` is the single-tenant
    placeholder ``"huilton_seed"`` so the FK check would block; we
    temporarily disable FK only inside this connection.
    """
    conn = db.connect()
    inserted = 0
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        cur = conn.cursor()
        for entry in payloads:
            cur.execute(
                "INSERT OR IGNORE INTO scene_templates ("
                "  id, enterprise_id, name, description, category, industry,"
                "  payload, tags, source, enabled, created_by"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    entry["id"],
                    DEFAULT_ENTERPRISE_ID,
                    entry["name"],
                    entry["description"],
                    entry["category"],
                    entry.get("industry"),
                    json.dumps(entry["payload"], ensure_ascii=False),
                    json.dumps(entry.get("tags") or [], ensure_ascii=False),
                    "builtin",
                    "system",
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
                log.info("marketplace seed: inserted builtin template %r", entry["id"])
        conn.commit()
    finally:
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:  # noqa: BLE001
            pass
        conn.close()
    return inserted


# ---------------------------------------------------------------------------
# Public coroutines (routes call these)
# ---------------------------------------------------------------------------


async def list_templates(
    enterprise_id: str | None = None,
    *,
    category: str | None = None,
    sort: str = "popular",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List marketplace templates (paginated).

    Query parameters:

    * ``category`` (str) — exact match on ``scene_templates.category``;
      ``None`` means "all categories".
    * ``sort`` (str) — ``"popular"`` (default, ``rating_avg`` / ``use_count``
      descending) or ``"recent"`` (``created_at`` descending).
    * ``limit`` / ``offset`` — pagination; ``limit`` is hard-capped at
      200 in the route layer.

    Returns ``{"items": [...], "total": int, "limit": int, "offset": int}``.
    ``total`` reflects the *filtered* count (so the UI can render
    "Showing 1-50 of N").
    """
    if sort not in _VALID_SORTS:
        raise TemplateValidationError(
            f"invalid sort: {sort!r}; expected one of {sorted(_VALID_SORTS)}"
        )
    if category is not None and category not in _KNOWN_CATEGORIES:
        # Soft check: unknown categories are accepted but logged so the
        # operator can spot typos. The ❹ spec lists 5 canonical buckets
        # but the demo may extend them; we don't want a forward-compat
        # one-line typo to 422 every call.
        log.warning("marketplace list_templates: unknown category %r", category)
    eid = enterprise_id or DEFAULT_ENTERPRISE_ID

    def _count_filtered() -> int:
        conn = db.connect()
        try:
            cur = conn.cursor()
            sql = (
                "SELECT COUNT(*) AS n FROM scene_templates "
                "WHERE enabled = 1 AND enterprise_id = ?"
            )
            params: list[Any] = [eid]
            if category is not None:
                sql += " AND category = ?"
                params.append(category)
            cur.execute(sql, params)
            return int(cur.fetchone()["n"])
        finally:
            conn.close()

    total, items = await asyncio.gather(
        asyncio.to_thread(_count_filtered),
        asyncio.to_thread(
            _list_sync,
            enterprise_id=eid,
            category=category,
            sort=sort,
            limit=limit,
            offset=offset,
        ),
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def get_template(template_id: str) -> dict[str, Any]:
    """Fetch a single template by id (payload included).

    Raises :class:`TemplateNotFoundError` (HTTP 404).
    """
    return await asyncio.to_thread(_get_sync, template_id)


async def create_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a new template row.

    ``payload`` keys:

    * ``name`` (str) — **required**, non-empty.
    * ``category`` (str) — **required**, one of the known categories.
    * ``description`` (str) — optional.
    * ``industry`` (str) — optional secondary tag.
    * ``payload`` (dict) — **required**, JSON object describing the
      scene assets (avatar_id / voice_id / tts_provider / stt_provider /
      llm_provider / preset prompts).
    * ``tags`` (list[str]) — optional, JSON array.
    * ``source`` (str) — optional, defaults to ``"user"``. Allowed values:
      ``"user"`` / ``"imported"`` (``"builtin"`` is reserved for seed-time
      rows — admin POSTs that try to claim ``source="builtin"`` are
      silently downgraded to ``"user"`` to keep the demo truthful).
    * ``enabled`` (int 0/1) — optional, defaults to ``1``.
    * ``created_by`` (str) — optional, free-form user reference.
    * ``enterprise_id`` (str) — optional, defaults to the single-tenant
      placeholder.

    Raises :class:`TemplateValidationError` on bad input (HTTP 422).
    """
    if not isinstance(payload, dict):
        raise TemplateValidationError("request body must be a JSON object")

    name_raw = payload.get("name")
    if not isinstance(name_raw, str) or not name_raw.strip():
        raise TemplateValidationError(
            "name is required and must be a non-empty string"
        )
    name = name_raw.strip()

    category_raw = payload.get("category")
    if not isinstance(category_raw, str) or not category_raw.strip():
        raise TemplateValidationError(
            "category is required and must be a non-empty string"
        )
    category = category_raw.strip()
    if category not in _KNOWN_CATEGORIES:
        log.warning("marketplace create_template: unknown category %r", category)

    payload_raw = payload.get("payload")
    if not isinstance(payload_raw, dict):
        raise TemplateValidationError("payload must be a dict")

    description_raw = payload.get("description")
    description = (
        description_raw.strip()
        if isinstance(description_raw, str) and description_raw.strip()
        else None
    )

    industry_raw = payload.get("industry")
    industry = (
        industry_raw.strip()
        if isinstance(industry_raw, str) and industry_raw.strip()
        else None
    )

    tags_raw = payload.get("tags")
    tags: list[str] | None
    if tags_raw is None:
        tags = None
    elif isinstance(tags_raw, list) and all(isinstance(t, str) for t in tags_raw):
        tags = [t for t in tags_raw if t.strip()]
    else:
        raise TemplateValidationError("tags, when provided, must be a list of strings")

    source_raw = payload.get("source")
    if source_raw is None:
        source = "user"
    elif source_raw in {"user", "imported"}:
        source = source_raw
    elif source_raw == "builtin":
        # Admin can't claim builtin ownership; downgrade to user.
        log.warning("marketplace create_template: source=builtin downgraded to user")
        source = "user"
    else:
        raise TemplateValidationError(
            f"source, when provided, must be one of 'user' / 'imported' / 'builtin'; got {source_raw!r}"
        )

    enabled_raw = payload.get("enabled")
    if enabled_raw is None:
        enabled = 1
    elif enabled_raw in (0, 1, True, False):
        enabled = 1 if enabled_raw else 0
    else:
        raise TemplateValidationError(
            "enabled, when provided, must be 0 or 1"
        )

    created_by_raw = payload.get("created_by")
    created_by = (
        created_by_raw.strip()
        if isinstance(created_by_raw, str) and created_by_raw.strip()
        else None
    )

    eid_raw = payload.get("enterprise_id")
    eid = str(eid_raw or "").strip() or DEFAULT_ENTERPRISE_ID

    return await asyncio.to_thread(
        _insert_sync,
        enterprise_id=eid,
        name=name,
        description=description,
        category=category,
        industry=industry,
        payload=payload_raw,
        tags=tags,
        source=source,
        enabled=enabled,
        created_by=created_by,
    )


async def patch_template(
    template_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Apply a partial update (sync).

    Body keys mirror :func:`create_template` minus ``source`` / ``created_by`` /
    ``enterprise_id`` (immutable post-create).

    Raises :class:`TemplateNotFoundError` (404) or
    :class:`TemplateValidationError` (422) on bad input.
    """
    if not isinstance(payload, dict):
        raise TemplateValidationError("request body must be a JSON object")

    # ``None`` means "field not supplied"; the patch only writes fields
    # that are explicitly present.
    name: str | None = None
    name_raw = payload.get("name")
    if name_raw is not None:
        if not isinstance(name_raw, str) or not name_raw.strip():
            raise TemplateValidationError("name, when provided, must be a non-empty string")
        name = name_raw.strip()

    description: str | None = None
    description_raw = payload.get("description")
    if description_raw is not None:
        if not isinstance(description_raw, str):
            raise TemplateValidationError("description, when provided, must be a string")
        description = description_raw

    category: str | None = None
    category_raw = payload.get("category")
    if category_raw is not None:
        if not isinstance(category_raw, str) or not category_raw.strip():
            raise TemplateValidationError(
                "category, when provided, must be a non-empty string"
            )
        category = category_raw.strip()
        if category not in _KNOWN_CATEGORIES:
            log.warning("marketplace patch_template: unknown category %r", category)

    industry: str | None = None
    industry_raw = payload.get("industry")
    if industry_raw is not None:
        if not isinstance(industry_raw, str):
            raise TemplateValidationError("industry, when provided, must be a string")
        industry = industry_raw

    payload_field: dict[str, Any] | None = None
    payload_raw = payload.get("payload")
    if payload_raw is not None:
        if not isinstance(payload_raw, dict):
            raise TemplateValidationError("payload, when provided, must be a dict")
        payload_field = payload_raw

    tags_field: list[str] | None = None
    tags_raw = payload.get("tags")
    if tags_raw is not None:
        if isinstance(tags_raw, list) and all(isinstance(t, str) for t in tags_raw):
            tags_field = [t for t in tags_raw if t.strip()]
        else:
            raise TemplateValidationError(
                "tags, when provided, must be a list of strings"
            )

    enabled_field: int | None = None
    enabled_raw = payload.get("enabled")
    if enabled_raw is not None:
        if enabled_raw in (0, 1, True, False):
            enabled_field = 1 if enabled_raw else 0
        else:
            raise TemplateValidationError(
                "enabled, when provided, must be 0 or 1"
            )

    return await asyncio.to_thread(
        _patch_sync,
        template_id,
        name=name,
        description=description,
        category=category,
        industry=industry,
        payload=payload_field,
        tags=tags_field,
        enabled=enabled_field,
    )


async def delete_template(template_id: str) -> dict[str, Any]:
    """Soft-delete (set ``enabled = 0``) the template row.

    Returns the updated (now hidden) row so the UI can show "Deleted
    template X" without a follow-up GET.

    Raises :class:`TemplateNotFoundError` (404).
    """
    return await asyncio.to_thread(_soft_delete_sync, template_id)


async def rate_template(
    template_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Insert (or replace) a rating row + recompute denormalised aggregates.

    ``payload`` keys:

    * ``rating`` (int) — **required**, ``1 <= rating <= 5``.
    * ``user_id`` (str) — optional; defaults to ``None`` (anonymous
      rating). When provided, the UNIQUE(template_id, user_id) constraint
      treats re-rating as an *update* (the prior row is replaced).
    * ``comment`` (str) — optional free-form annotation.

    Returns the inserted rating row.

    Raises:
      * :class:`TemplateNotFoundError` (404) if the template id is unknown.
      * :class:`TemplateValidationError` (422) if the rating is out of range.
    """
    if not isinstance(payload, dict):
        raise TemplateValidationError("request body must be a JSON object")

    rating_raw = payload.get("rating")
    if isinstance(rating_raw, bool) or not isinstance(rating_raw, int):
        raise TemplateValidationError(
            "rating is required and must be an integer between 1 and 5"
        )

    user_id_raw = payload.get("user_id")
    user_id: str | None
    if user_id_raw is None:
        user_id = None
    elif isinstance(user_id_raw, str) and user_id_raw.strip():
        user_id = user_id_raw.strip()
    else:
        raise TemplateValidationError(
            "user_id, when provided, must be a non-empty string"
        )

    comment_raw = payload.get("comment")
    comment: str | None
    if comment_raw is None:
        comment = None
    elif isinstance(comment_raw, str):
        comment = comment_raw
    else:
        raise TemplateValidationError("comment, when provided, must be a string")

    return await asyncio.to_thread(
        _insert_rating_sync,
        template_id,
        user_id=user_id,
        rating=rating_raw,
        comment=comment,
    )


async def list_copies(template_id: str) -> dict[str, Any]:
    """List copy records for a template (newest first).

    Returns ``{"items": [...], "total": int}``.

    Raises :class:`TemplateNotFoundError` (404) — the parent template
    must exist, mirroring the ``list_revisions`` / ``list_ratings``
    semantics on the other qiepai endpoints.
    """
    # Confirm template exists first so callers get 404 on bad ids.
    await asyncio.to_thread(_get_sync, template_id)
    items = await asyncio.to_thread(_list_copies_sync, template_id)
    return {"items": items, "total": len(items)}


async def copy_template(
    template_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Copy a template into a real digital employee (spec ❹ section 6).

    Flow (delegates to ``employees.service`` for employee + revision
    creation — we don't re-implement ❷-6 logic):

    1. Read ``template.payload`` (a dict).
    2. If ``target_employee_id`` is in the body, skip employee creation
       and verify the employee exists (else 404). Otherwise auto-create
       one with ``display_name="{template.name} (副本)"`` and
       ``role="数字员工"``.
    3. Append a new ``employee_revisions`` row with
       ``config_snapshot = template.payload`` (delegated to
       ``employees.service.create_revision``).
    4. Insert a ``scene_template_copies`` audit row + bump
       ``scene_templates.use_count``.

    Returns ``{"template_id", "target_employee_id", "revision_id",
    "employee": <full employee row>}`` so the frontend can pivot to
    the new employee without a follow-up GET.

    Body keys:
      * ``target_employee_id`` (str) — optional. When omitted, a new
        employee is created with ``display_name`` / ``role`` derived
        from the template.
      * ``copied_by`` (str) — optional user reference for the audit row.
      * ``display_name`` (str) — optional override of the auto-derived
        ``display_name`` when creating a new employee (useful for "Copy
        as "客服-华东"" UX). Ignored when ``target_employee_id`` is set.
      * ``role`` (str) — optional override of the auto-derived ``role``.
        Ignored when ``target_employee_id`` is set.
    """
    # Lazy import to avoid a circular import: employees.service imports
    # from ..outbox.events, which is fine, but we keep the dependency
    # edge tight so the marketplace module stays usable on its own.
    from ..employees import service as employees_service

    if not isinstance(payload, dict):
        raise TemplateValidationError("request body must be a JSON object")

    template = await asyncio.to_thread(_get_sync, template_id)
    template_payload = template.get("payload")
    if not isinstance(template_payload, dict):
        # Defensive: every template we ship has a dict payload, but a
        # hand-crafted INSERT could leave a string behind. Refuse rather
        # than propagate garbage into a real employee.
        raise TemplateValidationError(
            "template payload is not a JSON object; cannot copy"
        )

    target_employee_id_raw = payload.get("target_employee_id")
    copied_by_raw = payload.get("copied_by")
    copied_by = (
        copied_by_raw.strip()
        if isinstance(copied_by_raw, str) and copied_by_raw.strip()
        else None
    )

    if target_employee_id_raw is not None:
        if not isinstance(target_employee_id_raw, str) or not target_employee_id_raw.strip():
            raise TemplateValidationError(
                "target_employee_id, when provided, must be a non-empty string"
            )
        target_employee_id = target_employee_id_raw.strip()
        # Confirm the employee exists. ``employees.service.get_employee``
        # raises EmployeeNotFoundError on a bad id; we surface that as a
        # TargetEmployeeNotFoundError so the route maps to 404 with a
        # marketplace-flavored message.
        try:
            employee = await employees_service.get_employee(target_employee_id)
        except employees_service.EmployeeNotFoundError as exc:
            raise TargetEmployeeNotFoundError(
                f"target_employee_id not found: {target_employee_id}"
            ) from exc
    else:
        # Auto-create the employee. Display name + role fall back to
        # template-derived defaults; the body can override either via
        # ``display_name`` / ``role`` keys for "Copy as ..." UX.
        display_name_raw = payload.get("display_name")
        if isinstance(display_name_raw, str) and display_name_raw.strip():
            display_name = display_name_raw.strip()
        else:
            display_name = f"{template.get('name') or '未命名'} (副本)"

        role_raw = payload.get("role")
        if isinstance(role_raw, str) and role_raw.strip():
            role = role_raw.strip()
        else:
            role = "数字员工"

        employee = await employees_service.create_employee(
            {
                "display_name": display_name,
                "role": role,
            }
        )
        target_employee_id = str(employee["id"])

    # Append a revision carrying the template's payload. The
    # ``workspace_file_hash`` is a stable synthetic identifier so
    # downstream publish-state-machine calls don't reject it (the
    # field is required by employees.service.create_revision; the
    # value's contents don't gate any business rule, only its
    # non-emptiness).
    revision = await employees_service.create_revision(
        target_employee_id,
        {
            "workspace_file_hash": f"sha256:marketplace-copy-{template_id}",
            "config_snapshot": template_payload,
        },
    )

    # Audit + use_count bump.
    copy_row = await asyncio.to_thread(
        _record_copy_sync,
        template_id,
        copied_by=copied_by,
        target_employee_id=target_employee_id,
    )

    return {
        "template_id": template_id,
        "target_employee_id": target_employee_id,
        "revision_id": revision["id"],
        "copy_id": copy_row["id"],
        "employee": employee,
        "revision": revision,
    }


async def seed_builtin_templates() -> int:
    """Lifespan-time bootstrap of the 4 fixed ``source='builtin'`` rows.

    Idempotent (INSERT OR IGNORE keyed by deterministic ``id``). Returns
    the number of rows newly inserted (0 on every call after the first).

    Safe to call from the FastAPI ``lifespan`` after
    ``run_pending_migrations()`` and ``seed_initial_metrics()``.
    """
    return await asyncio.to_thread(_seed_builtin_sync, list(SEED_TEMPLATES))


__all__ = [
    "DEFAULT_ENTERPRISE_ID",
    "TemplateNotFoundError",
    "TemplateValidationError",
    "TemplateConflictError",
    "TargetEmployeeNotFoundError",
    "list_templates",
    "get_template",
    "create_template",
    "patch_template",
    "delete_template",
    "rate_template",
    "list_copies",
    "copy_template",
    "seed_builtin_templates",
]