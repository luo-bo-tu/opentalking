// qiepai · 决策中心类型定义 (Phase ❷-5)
//
// 设计原则 (架构 v1.1 § 0.1 + § 21.2):
//   - fact / inference / suggestion / unknown 四层, UI 必须显式分层
//   - fact 来源必须标 source (架构 § 21.1)
//   - mock 数据标 source=mock://... (❷-3 决策 #5)
//   - 缺数据显式 unavailable, 不显示 0 (❷-3 决策 #5)

export type DecisionStatus = "pending" | "decided" | "cancelled";

/** 单条决策项 (DB decision_items 表的 TS 投影) */
export interface DecisionItem {
  id: string;
  title: string;
  description: string;
  status: DecisionStatus;
  owner: string;
  metric_id: string | null;
  snapshot_id: string | null;
  /** 决策时刻的事实快照 (JSON 对象, key 为指标名, value 为数值或结构) */
  fact_snapshot: Record<string, unknown>;
  /** AI 缓存的建议 (后端存在则用, 不存在则 null 等刷新) */
  ai_suggestion: AIResponse | null;
  decision_text: string | null;
  decided_at: string | null;
  created_at: string;
}

/** AI 4 层响应 */
export interface AIResponse {
  /** 实际数据层 — 必须有 source 标签 */
  fact: FactItem[];
  /** 推断层 — 基于 fact 的 LLM 推断 (cached) */
  inference: InferenceItem[];
  /** 建议层 — 行动建议 (user-triggered, not cached) */
  suggestion: SuggestionItem[];
  /** 未知层 — 信息不足以判断的项 */
  unknown: UnknownItem[];
}

export interface FactItem {
  label: string;
  value: number | string | null;
  unit?: string;
  /** 数据来源 (mock://... 或 connector id 或 metric id) */
  source: string;
}

export interface InferenceItem {
  text: string;
  /** 0-1, LLM 置信度 */
  confidence: number;
}

export interface SuggestionItem {
  text: string;
  /** 建议的责任人 */
  owner: string;
}

export interface UnknownItem {
  text: string;
  /** 建议补充的数据类型 (e.g. "客户 A 续约意向") */
  need?: string;
}

/** 提交决策的 PATCH payload */
export interface DecisionPatchPayload {
  status: DecisionStatus;
  decision_text: string;
}

/** 创建决策的 POST payload (手动建项) */
export interface DecisionCreatePayload {
  title: string;
  description: string;
  owner: string;
}
