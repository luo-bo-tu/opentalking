// qiepai · 飞书机器人 mock 数据 (Phase ❸-1 前端先行)
//
// 后端 /api/qiepai/integrations/feishu/* 还在 stub, 前端先用这份 mock 渲染真实 UI 结构.
// 数据语义合理 (4 个不同状态群 + 历史投递记录), 后端就绪后所有 fetch 自动切真, 这份文件作废.
//
// 数据来源全部标 source=mock://..., UI 顶部显式标 "mock 模式".
// 凭证仅显示截断预览, 完整 token 不在 mock 数据中.

import type {
  FeishuDeliveryRecord,
  FeishuGroup,
} from "./types";

/** Mock 飞书群列表 (5 个, 覆盖 active / inactive / error 三态) */
export const MOCK_GROUPS: FeishuGroup[] = [
  {
    id: "fs-grp-cfo-001",
    chat_id: "oc_cfo_audit_room",
    chat_name: "财务审计日报群",
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/c8e2****f1a4",
    bot_token_masked: null,
    credential_kind: "webhook",
    status: "active",
    last_delivered_at: "2026-07-31T08:30:00+08:00",
    last_delivery_status: "ok",
    source: "mock://feishu/groups/v1",
    as_of: "2026-07-31T09:00:00+08:00",
    recent_deliveries: [
      {
        id: "del-cfo-001-3",
        chat_id: "oc_cfo_audit_room",
        chat_name: "财务审计日报群",
        message_preview: "[日报] 2026-07-31 营收 ¥482.3万, 环比 -3.0%",
        status: "ok",
        created_at: "2026-07-31T08:30:00+08:00",
      },
      {
        id: "del-cfo-001-2",
        chat_id: "oc_cfo_audit_room",
        chat_name: "财务审计日报群",
        message_preview: "[日报] 2026-07-30 营收 ¥497.3万, 环比 +1.2%",
        status: "ok",
        created_at: "2026-07-30T08:30:00+08:00",
      },
      {
        id: "del-cfo-001-1",
        chat_id: "oc_cfo_audit_room",
        chat_name: "财务审计日报群",
        message_preview: "[日报] 2026-07-29 营收 ¥491.4万, 环比 -0.8%",
        status: "ok",
        created_at: "2026-07-29T08:30:00+08:00",
      },
    ],
  },
  {
    id: "fs-grp-sales-002",
    chat_id: "oc_sales_alert",
    chat_name: "销售战报告警群",
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/a17b****92cd",
    bot_token_masked: null,
    credential_kind: "webhook",
    status: "active",
    last_delivered_at: "2026-07-31T07:15:00+08:00",
    last_delivery_status: "ok",
    source: "mock://feishu/groups/v1",
    as_of: "2026-07-31T09:00:00+08:00",
    recent_deliveries: [
      {
        id: "del-sales-002-2",
        chat_id: "oc_sales_alert",
        chat_name: "销售战报告警群",
        message_preview: "[战报] 本周新签合同 8 单, 同比 +12%",
        status: "ok",
        created_at: "2026-07-31T07:15:00+08:00",
      },
      {
        id: "del-sales-002-1",
        chat_id: "oc_sales_alert",
        chat_name: "销售战报告警群",
        message_preview: "[战报] Top 1 客户贡献 38%, 集中度告警",
        status: "rate_limited",
        created_at: "2026-07-30T15:42:00+08:00",
      },
    ],
  },
  {
    id: "fs-grp-ops-003",
    chat_id: "oc_ops_runtime",
    chat_name: "运维值班群",
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/d04e****bb81",
    bot_token_masked: "t-7****3f9a",
    credential_kind: "bot_token",
    status: "inactive",
    last_delivered_at: "2026-07-20T22:00:00+08:00",
    last_delivery_status: "ok",
    source: "mock://feishu/groups/v1",
    as_of: "2026-07-31T09:00:00+08:00",
    recent_deliveries: [
      {
        id: "del-ops-003-1",
        chat_id: "oc_ops_runtime",
        chat_name: "运维值班群",
        message_preview: "[告警] API 队列堆积 124 条, 已自动扩容",
        status: "ok",
        created_at: "2026-07-20T22:00:00+08:00",
      },
    ],
  },
  {
    id: "fs-grp-legal-004",
    chat_id: "oc_legal_review",
    chat_name: "法务审批群",
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/88f1****77e0",
    bot_token_masked: null,
    credential_kind: "webhook",
    status: "error",
    last_delivered_at: "2026-07-29T11:08:00+08:00",
    last_delivery_status: "failed",
    source: "mock://feishu/groups/v1",
    as_of: "2026-07-31T09:00:00+08:00",
    recent_deliveries: [
      {
        id: "del-legal-004-2",
        chat_id: "oc_legal_review",
        chat_name: "法务审批群",
        message_preview: "[审批] 合同草案 v3 待审",
        status: "failed",
        created_at: "2026-07-29T11:08:00+08:00",
      },
      {
        id: "del-legal-004-1",
        chat_id: "oc_legal_review",
        chat_name: "法务审批群",
        message_preview: "[审批] 合同草案 v2 待审",
        status: "ok",
        created_at: "2026-07-28T16:30:00+08:00",
      },
    ],
  },
  {
    id: "fs-grp-cs-005",
    chat_id: "oc_cs_feedback",
    chat_name: "客户反馈群",
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/2c9a****88b5",
    bot_token_masked: null,
    credential_kind: "webhook",
    status: "active",
    last_delivered_at: null,
    last_delivery_status: null,
    source: "mock://feishu/groups/v1",
    as_of: "2026-07-31T09:00:00+08:00",
    recent_deliveries: [],
  },
];

/** Mock 历史投递 (供测试 modal 跨群查询) */
export const MOCK_DELIVERY_HISTORY: FeishuDeliveryRecord[] = MOCK_GROUPS
  .flatMap((g) => g.recent_deliveries ?? [])
  .filter((d): d is FeishuDeliveryRecord => d !== undefined);