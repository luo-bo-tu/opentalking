"""qiepai · marketplace builtin template seed (Phase ❹).

Lives alongside :mod:`apps.api.services.qiepai.marketplace.service` (not
inside the migrations package) on purpose: per spec ❹ section 0 the
builtin template roster will iterate as we discover what works for the
demo customer, and piggy-backing those changes on migrations would
inflate ``_migration_history`` with rows that have no schema impact.
Instead this seed step is called from the FastAPI ``lifespan`` after
migrations finish, is fully idempotent (``INSERT OR IGNORE`` keyed by
deterministic primary ids), and only touches the qiepai enterprise
database.

What gets seeded
================

Four ``scene_templates`` rows, one per canonical category
(``customer_service`` / ``sales`` / ``finance`` / ``hr``). Each row
carries:

* ``id`` — deterministic (``stpl_builtin_<slug>``) so the seed is
  idempotent and so the demo frontend can pin references to known
  builtin ids.
* ``source`` — hard-coded ``"builtin"`` (the service's
  :func:`create_template` rejects admin POSTs that try to claim
  ``source="builtin"`` to keep the demo truthful).
* ``payload`` — a JSON object modelling the scene_assets config
  (``avatar_id`` / ``voice_id`` / ``tts_provider`` / ``stt_provider`` /
  ``llm_provider`` / ``system_prompt``) that the copy endpoint will
  write into a new ``employee_revisions.config_snapshot``.

Idempotency contract
====================

Re-running :func:`seed_builtin_templates` (or its sync core called
from the service) returns ``0` (rows inserted) on every call after
the first. The mock JSON content is *not* re-read on every restart:
builtin rows are written with the values present at first seed time.
If the seed list changes between restarts, the seed will *not*
update the existing DB row — this matches the ``seed_initial_metrics``
contract (❷-3); operators who want a fresh payload should DELETE
the builtin + re-seed manually.

Why ``INSERT OR IGNORE`` and not ``SELECT … INSERT``
====================================================

* O(1) per row regardless of table size.
* Atomic at the statement level (no transaction window where two
  workers could double-insert).
* Plays nicely with SQLite's WAL mode — no read-then-write race.
"""
from __future__ import annotations

from typing import Any, Final

#: The four fixed builtin template rows. ``id`` is deterministic so the
#: seed is idempotent; ``payload`` is the scene_assets config the copy
#: endpoint will materialise into a new employee + revision.
#:
#: NOTE: keep this list small (3-5) per spec ❹ section 0 — these are the
#: "tried-and-true" presets we want to highlight in the marketplace UI,
#: not an exhaustive catalogue.
SEED_TEMPLATES: Final[tuple[dict[str, Any], ...]] = (
    {
        "id": "stpl_builtin_customer_service",
        "name": "客服数字员工 - 标准版",
        "description": (
            "面向售后 / 售前咨询场景,基于 edge-tts + FunASR + Qwen,响应时长"
            "1.5s,内置退款 / 物流 / 投诉 FAQ。"
        ),
        "category": "customer_service",
        "industry": "通用零售",
        "tags": ["客服", "售后", "FAQ", "高并发"],
        "payload": {
            "avatar_id": "avatar-cs-female-01",
            "voice_id": "edge-xiaoxiao",
            "tts_provider": "edge-tts",
            "stt_provider": "funasr",
            "llm_provider": "qwen",
            "llm_model": "qwen-plus",
            "system_prompt": (
                "你是「客服小助手」,负责接待用户的售前售后咨询。"
                "回答必须基于知识库;遇到无法回答的问题时礼貌转人工。"
            ),
            "knowledge_base_ids": ["kb-cs-faq"],
            "fallback_to_human": True,
            "max_response_seconds": 1.5,
        },
    },
    {
        "id": "stpl_builtin_sales",
        "name": "销售数字员工 - 商机跟进",
        "description": (
            "面向 B2B 销售外呼场景,基于 dashscope TTS + OpenAI Whisper + GPT-4,"
            "内置 SPIN 提问模板与商机阶段判断。"
        ),
        "category": "sales",
        "industry": "B2B",
        "tags": ["销售", "外呼", "SPIN", "商机"],
        "payload": {
            "avatar_id": "avatar-sales-male-02",
            "voice_id": "cosyvoice-longxiaocheng",
            "tts_provider": "dashscope",
            "stt_provider": "openai-whisper",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "system_prompt": (
                "你是「销售助理」,负责对潜客进行外呼跟进。"
                "使用 SPIN 提问法 (Situation / Problem / Implication / Need-payoff),"
                "在合适节点判断商机阶段 (新建 / 跟进 / 谈判 / 成单)。"
            ),
            "spin_template": "default",
            "auto_qualify": True,
            "warm_transfer_keywords": ["价格", "合同", "对接"],
        },
    },
    {
        "id": "stpl_builtin_finance",
        "name": "财务数字员工 - 月结汇报",
        "description": (
            "面向财务月结汇报场景,基于 edge-tts + 本地 SenseVoice + Qwen-Plus,"
            "自动汇总 5 个 KPI (营收 / 回款 / 应收 / 客户集中度 / 目标达成) 并生成"
            "5 分钟语音简报。"
        ),
        "category": "finance",
        "industry": "集团总部",
        "tags": ["财务", "月结", "KPI", "语音简报"],
        "payload": {
            "avatar_id": "avatar-fin-female-01",
            "voice_id": "edge-yunxi",
            "tts_provider": "edge-tts",
            "stt_provider": "sensevoice",
            "llm_provider": "qwen",
            "llm_model": "qwen-plus",
            "system_prompt": (
                "你是「财务月结助手」,负责基于 metric_snapshots 的 5 个 KPI"
                "(financial-kpi / sales-trend / customer-concentration / "
                "orders-ar / target-attainment) 生成 5 分钟语音简报。"
            ),
            "metric_ids": [
                "financial-kpi",
                "sales-trend",
                "customer-concentration",
                "orders-ar",
                "target-attainment",
            ],
            "report_duration_minutes": 5,
            "require_disclaimer": True,
        },
    },
    {
        "id": "stpl_builtin_hr",
        "name": "HR 数字员工 - 入职引导",
        "description": (
            "面向新员工入职 Day-1 场景,基于 edge-tts + FunASR + Qwen-Turbo,"
            "内置入职流程 + 福利政策 FAQ + 工位 / 设备指引。"
        ),
        "category": "hr",
        "industry": "通用",
        "tags": ["HR", "入职", "FAQ", "新员工"],
        "payload": {
            "avatar_id": "avatar-hr-female-02",
            "voice_id": "edge-yunjian",
            "tts_provider": "edge-tts",
            "stt_provider": "funasr",
            "llm_provider": "qwen",
            "llm_model": "qwen-turbo",
            "system_prompt": (
                "你是「HR 入职助手」,负责接待新员工 Day-1 的提问。"
                "回答必须围绕入职流程 / 福利政策 / 工位 / 设备 / IT 账号,"
                "遇到超出范围的问题时礼貌告知 \"请联系 HRBP\"。"
            ),
            "knowledge_base_ids": ["kb-hr-onboarding"],
            "escalation_keywords": ["薪资", "社保", "公积金", "投诉"],
            "multilingual": ["zh-CN", "en-US"],
        },
    },
)


__all__ = ["SEED_TEMPLATES"]