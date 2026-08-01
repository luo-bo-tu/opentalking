// qiepai · 场景模板 Marketplace mock 数据 (Phase ❹ 前端先行)
//
// 后端 /api/qiepai/marketplace/* 还在 stub, 前端先用这份 mock 渲染真实 UI 结构.
// 数据语义合理 (5 个 category 各 1 条 / rating 1-5 真实分布 / use_count 不重复),
// 后端就绪后所有 fetch 自动切真, 这份文件作废.
//
// 数据来源全部标 data_source=mock://..., UI 顶部显式标 "mock 模式".
// payload 是合理 JSON 配置快照, 跟 ❷-6 employee_revision.config_snapshot 同构.

import type {
  MarketplaceTemplate,
  TemplateRating,
} from "./types";

/** Mock 场景模板列表 (5 条, 覆盖 5 个 category) */
export const MOCK_TEMPLATES: MarketplaceTemplate[] = [
  {
    id: "tpl-cs-001",
    name: "智能客服坐席",
    description:
      "面向 C 端用户的 7×24 智能客服, 自动识别工单类型并引导用户自助解决, 复杂问题转人工坐席并附带完整上下文。",
    category: "customer_service",
    industry: "电商零售",
    tags: ["客服", "工单", "自助", "转人工"],
    source: "builtin",
    use_count: 142,
    rating_avg: 4.8,
    rating_count: 38,
    payload: {
      avatar_id: "anime-customer-service-girl",
      voice_id: "zhitian_emo",
      tts_provider: "cosyvoice",
      tts_model: "cosyvoice-300m",
      tts_voice: "longxiaochuan_v2",
      stt_provider: "dashscope",
      llm_provider: "dashscope",
      llm_model: "qwen-plus",
      system_prompt:
        "你是 qiepai 智能客服助手, 负责处理用户咨询。请先识别用户问题类型, 优先提供自助解决方案, 必要时转人工坐席。",
      knowledge_base_ids: ["kb-faq-001", "kb-product-spec-002"],
    },
    created_by: "system",
    created_at: "2026-04-12T09:00:00+08:00",
    updated_at: "2026-07-20T15:30:00+08:00",
    data_source: "mock://marketplace/templates/v1",
    as_of: "2026-07-31T09:00:00+08:00",
  },
  {
    id: "tpl-sales-002",
    name: "销售线索跟进",
    description:
      "面向 B 端销售团队的线索智能跟进, 自动从 CRM 同步线索状态, 生成跟进建议并提醒销售及时触达。",
    category: "sales",
    industry: "企业服务",
    tags: ["销售", "CRM", "线索", "跟进提醒"],
    source: "user",
    use_count: 98,
    rating_avg: 4.5,
    rating_count: 26,
    payload: {
      avatar_id: "business-male-01",
      voice_id: "zhiyan_emo",
      tts_provider: "dashscope",
      tts_model: "qwen-tts",
      tts_voice: "male-qn-jingying",
      stt_provider: "dashscope",
      llm_provider: "dashscope",
      llm_model: "qwen-max",
      system_prompt:
        "你是销售助理, 帮助销售梳理线索进展、生成跟进话术、提醒关键时间节点。回答请简洁专业。",
      knowledge_base_ids: ["kb-sales-playbook-001"],
    },
    created_by: "user_lin",
    created_at: "2026-05-03T14:20:00+08:00",
    updated_at: "2026-07-28T11:45:00+08:00",
    data_source: "mock://marketplace/templates/v1",
    as_of: "2026-07-31T09:00:00+08:00",
  },
  {
    id: "tpl-fin-003",
    name: "财务报表解读",
    description:
      "面向 CFO / 财务总监的财报智能解读, 自动拉取营收 / 成本 / 应收数据, 生成趋势分析与异常告警。",
    category: "finance",
    industry: "通用",
    tags: ["财务", "报表", "趋势", "告警"],
    source: "builtin",
    use_count: 67,
    rating_avg: 4.6,
    rating_count: 19,
    payload: {
      avatar_id: "finance-male-expert",
      voice_id: "zhimiao_emo",
      tts_provider: "cosyvoice",
      tts_model: "cosyvoice-300m-sft",
      tts_voice: "longwan_v2",
      stt_provider: "dashscope",
      llm_provider: "dashscope",
      llm_model: "qwen-max",
      system_prompt:
        "你是 qiepai 财务分析助手, 负责解读财务数据并生成洞察。请引用具体数字, 给出明确结论与建议。",
      knowledge_base_ids: ["kb-finance-glossary-001"],
    },
    created_by: "system",
    created_at: "2026-03-18T10:30:00+08:00",
    updated_at: "2026-07-15T16:00:00+08:00",
    data_source: "mock://marketplace/templates/v1",
    as_of: "2026-07-31T09:00:00+08:00",
  },
  {
    id: "tpl-hr-004",
    name: "员工入职引导",
    description:
      "面向 HR 的新员工入职智能引导, 自动讲解公司制度 / 流程 / 常用工具, 跟踪入职 checklist 完成度。",
    category: "hr",
    industry: "通用",
    tags: ["人事", "入职", "新人", "checklist"],
    source: "user",
    use_count: 35,
    rating_avg: 4.2,
    rating_count: 12,
    payload: {
      avatar_id: "friendly-female-hr",
      voice_id: "zhiyan_emo",
      tts_provider: "dashscope",
      tts_model: "qwen-tts",
      tts_voice: "female-shaonv",
      stt_provider: "dashscope",
      llm_provider: "dashscope",
      llm_model: "qwen-plus",
      system_prompt:
        "你是 qiepai HR 助手, 负责新员工入职引导。请保持友好耐心, 用通俗语言讲解制度和流程。",
      knowledge_base_ids: ["kb-hr-handbook-001"],
    },
    created_by: "user_zhang",
    created_at: "2026-06-08T11:15:00+08:00",
    updated_at: "2026-07-10T09:30:00+08:00",
    data_source: "mock://marketplace/templates/v1",
    as_of: "2026-07-31T09:00:00+08:00",
  },
  {
    id: "tpl-ops-005",
    name: "运维值班响应",
    description:
      "面向运维团队的 7×24 值班响应助手, 接收告警信息并自动触发应急流程, 沉淀值班手册与历史事件。",
    category: "ops",
    industry: "互联网",
    tags: ["运维", "告警", "值班", "应急"],
    source: "imported",
    use_count: 51,
    rating_avg: 4.4,
    rating_count: 15,
    payload: {
      avatar_id: "tech-male-engineer",
      voice_id: "zhitian_emo",
      tts_provider: "cosyvoice",
      tts_model: "cosyvoice-300m",
      tts_voice: "longxiaochuan_v2",
      stt_provider: "dashscope",
      llm_provider: "dashscope",
      llm_model: "qwen-max",
      system_prompt:
        "你是 qiepai 运维值班助手, 负责接收告警、诊断问题、推送应急响应步骤。请保持冷静专业。",
      knowledge_base_ids: ["kb-ops-runbook-001", "kb-incident-history-002"],
    },
    created_by: "user_wang",
    created_at: "2026-04-25T16:00:00+08:00",
    updated_at: "2026-07-22T13:20:00+08:00",
    data_source: "mock://marketplace/templates/v1",
    as_of: "2026-07-31T09:00:00+08:00",
  },
];

/** Mock 评分 (按 template_id 索引, 每个模板 2-3 条真实分布) */
export const MOCK_RATINGS: Record<string, TemplateRating[]> = {
  "tpl-cs-001": [
    {
      id: "rt-cs-001-1",
      template_id: "tpl-cs-001",
      user_id: "user_lin",
      rating: 5,
      comment: "自助率提升明显, 转人工上下文完整, 客服团队反馈很好。",
      created_at: "2026-07-20T10:30:00+08:00",
    },
    {
      id: "rt-cs-001-2",
      template_id: "tpl-cs-001",
      user_id: "user_zhao",
      rating: 5,
      comment: "智能识别工单类型非常准, 客户满意度 +12%。",
      created_at: "2026-07-15T14:20:00+08:00",
    },
    {
      id: "rt-cs-001-3",
      template_id: "tpl-cs-001",
      user_id: "user_chen",
      rating: 4,
      comment: "整体不错, 个别长尾问题处理需要再优化。",
      created_at: "2026-07-08T09:45:00+08:00",
    },
  ],
  "tpl-sales-002": [
    {
      id: "rt-sales-002-1",
      template_id: "tpl-sales-002",
      user_id: "user_zhang",
      rating: 5,
      comment: "跟进提醒很及时, 销售复盘效率提升 30%。",
      created_at: "2026-07-22T11:00:00+08:00",
    },
    {
      id: "rt-sales-002-2",
      template_id: "tpl-sales-002",
      user_id: "user_li",
      rating: 4,
      comment: "话术生成专业, 但偶尔过于正式。",
      created_at: "2026-07-18T16:30:00+08:00",
    },
  ],
  "tpl-fin-003": [
    {
      id: "rt-fin-003-1",
      template_id: "tpl-fin-003",
      user_id: "user_chen",
      rating: 5,
      comment: "异常告警很敏锐, 救了一次逾期客户。",
      created_at: "2026-07-25T09:15:00+08:00",
    },
    {
      id: "rt-fin-003-2",
      template_id: "tpl-fin-003",
      user_id: "user_lin",
      rating: 4,
      comment: "趋势分析到位, 个别指标解读口径建议校准。",
      created_at: "2026-07-12T13:40:00+08:00",
    },
  ],
  "tpl-hr-004": [
    {
      id: "rt-hr-004-1",
      template_id: "tpl-hr-004",
      user_id: "user_zhao",
      rating: 4,
      comment: "入职流程清晰, 新员工上手时间缩短约 30%。",
      created_at: "2026-07-19T10:00:00+08:00",
    },
    {
      id: "rt-hr-004-2",
      template_id: "tpl-hr-004",
      user_id: "user_wang",
      rating: 4,
      comment: "讲解友好, 但 checklist 跟踪不够直观。",
      created_at: "2026-07-05T15:20:00+08:00",
    },
  ],
  "tpl-ops-005": [
    {
      id: "rt-ops-005-1",
      template_id: "tpl-ops-005",
      user_id: "user_li",
      rating: 5,
      comment: "应急响应步骤精准, 7 月处理 3 次 P2 告警都很快。",
      created_at: "2026-07-28T22:15:00+08:00",
    },
    {
      id: "rt-ops-005-2",
      template_id: "tpl-ops-005",
      user_id: "user_chen",
      rating: 4,
      comment: "值班手册检索好用, 偶有重复步骤。",
      created_at: "2026-07-14T18:50:00+08:00",
    },
  ],
};