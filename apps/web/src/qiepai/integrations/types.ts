// qiepai · 飞书机器人集成 类型契约 (Phase ❸-1)
//
// 数据契约对齐 backend `/api/qiepai/integrations/feishu/*`:
//   GET    /groups                        -> {items: FeishuGroup[], total: number}
//   POST   /groups                        -> {item: FeishuGroup}
//   DELETE /groups/{id}                   -> {deleted: true, id: string}
//   POST   /test                          -> {delivered: number, status: "ok"|"partial"|"failed", results: FeishuDeliveryResult[]}
//   GET    /deliveries                    -> {items: FeishuDeliveryRecord[]}
//
// 前端契约要点:
//   - bot_token / webhook_url **仅保留截断预览** (后端不返回完整凭证)
//   - 三态渲染契约 (架构 v1.1 §21.1): number 显数字 / null unavailable / 过时标过期
//   - mock 模式 source 显式标 "mock://..."

export type FeishuGroupStatus = "active" | "inactive" | "error";

export type FeishuCredentialKind = "webhook" | "bot_token";

/** 群对象 (列表 / 添加 通用) */
export interface FeishuGroup {
  id: string;
  chat_id: string;
  chat_name: string;
  /** webhook URL 截断预览 (前 32 + **** + 后 8), 不暴露完整 token */
  webhook_url: string;
  /** bot_token 截断预览 (fe****...****XXXX), null 表示未使用 bot_token */
  bot_token_masked: string | null;
  credential_kind: FeishuCredentialKind;
  status: FeishuGroupStatus;
  /** 上次成功投递时间 (ISO), null 表示从未投递 */
  last_delivered_at: string | null;
  /** 上次投递状态文字 (e.g. "ok" / "rate_limited"), null 同上 */
  last_delivery_status: string | null;
  /** 数据来源, mock 时为 "mock://..." */
  source: string;
  /** 数据快照时间 (ISO) */
  as_of: string;
  /** mock 历史投递 (只 mock 数据用, 真后端可省略) */
  recent_deliveries?: FeishuDeliveryRecord[];
}

/** 历史投递记录 */
export interface FeishuDeliveryRecord {
  id: string;
  chat_id: string;
  chat_name: string;
  message_preview: string;
  status: "ok" | "failed" | "rate_limited";
  created_at: string;
}

/** GET /groups 响应 */
export interface FeishuGroupsResponse {
  items: FeishuGroup[];
  total: number;
}

/** POST /groups 请求 */
export interface FeishuGroupCreatePayload {
  chat_id: string;
  chat_name?: string;
  credential_kind: FeishuCredentialKind;
  webhook_url?: string;
  bot_token?: string;
}

/** POST /groups 响应 */
export interface FeishuGroupCreateResponse {
  item: FeishuGroup;
}

/** POST /test 请求 */
export interface FeishuTestPayload {
  chat_ids: string[];
  message: string;
}

/** POST /test 单条投递结果 */
export interface FeishuDeliveryResult {
  chat_id: string;
  chat_name: string;
  status: "ok" | "failed";
  error?: string | null;
}

/** POST /test 响应 */
export interface FeishuTestResponse {
  delivered: number;
  total: number;
  status: "ok" | "partial" | "failed";
  results: FeishuDeliveryResult[];
}

/** GET /deliveries 响应 */
export interface FeishuDeliveriesResponse {
  items: FeishuDeliveryRecord[];
  total: number;
}