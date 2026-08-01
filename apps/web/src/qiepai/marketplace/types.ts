// qiepai · 场景模板 Marketplace 类型契约 (Phase ❹)
//
// 数据契约对齐 backend `/api/qiepai/marketplace/*`:
//   GET    /templates                         -> {items: MarketplaceTemplate[], total}
//   GET    /templates/{id}                    -> MarketplaceTemplate (含完整 payload)
//   POST   /templates                         -> {item: MarketplaceTemplate}
//   PATCH  /templates/{id}                    -> {item: MarketplaceTemplate}
//   DELETE /templates/{id}                    -> {deleted, id}
//   POST   /templates/{id}/ratings            -> {item: TemplateRating}
//   GET    /templates/{id}/ratings            -> {items: TemplateRating[], total}
//   GET    /templates/{id}/copies             -> {items: TemplateCopyRecord[], total}
//   POST   /templates/{id}/copy               -> {copy_id, template_id, target_employee_id, ...}
//
// 设计原则 (架构 v1.1 + ❷-3 决策 #5):
//   - payload 是 JSON 配置快照 (avatar_id / voice_id / tts_provider / stt_provider / llm_provider / system_prompt 等)
//   - 三态渲染契约: number / null / 过期 (架构 §21.1)
//   - mock 数据 source 显式标 "mock://..."

/** 模板分类 (跟 DB scene_templates.category 对齐) */
export type TemplateCategory =
  | "customer_service"
  | "sales"
  | "finance"
  | "hr"
  | "ops";

/** 模板来源 */
export type TemplateSource = "user" | "builtin" | "imported";

/** 复制状态 */
export type TemplateCopyStatus = "pending" | "success" | "failed";

/** payload 字段 (DB scene_templates.payload JSON 投影) */
export interface TemplatePayloadField {
  avatar_id?: string;
  voice_id?: string;
  tts_provider?: string;
  tts_model?: string;
  tts_voice?: string;
  stt_provider?: string;
  llm_provider?: string;
  llm_model?: string;
  system_prompt?: string;
  knowledge_base_ids?: string[];
  [key: string]: unknown;
}

/** 单条场景模板 (DB scene_templates 表的 TS 投影) */
export interface MarketplaceTemplate {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  industry: string | null;
  tags: string[];
  source: TemplateSource;
  use_count: number;
  rating_avg: number;
  rating_count: number;
  payload: TemplatePayloadField;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** 数据来源, mock 时为 "mock://...";backend 真接口暂未返回 (Phase ❹ 已知 gap) */
  data_source?: string;
  /** 数据快照时间 (ISO);backend 真接口暂未返回 (Phase ❹ 已知 gap) */
  as_of?: string;
}

/** 单条评分 (DB scene_template_ratings 表的 TS 投影) */
export interface TemplateRating {
  id: string;
  template_id: string;
  user_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

/** GET /templates 响应 */
export interface TemplatesListResponse {
  items: MarketplaceTemplate[];
  total: number;
}

/** GET /templates/{id}/ratings 响应 */
export interface TemplateRatingsResponse {
  items: TemplateRating[];
  total: number;
}

/** POST /templates 请求体 (上传模板) */
export interface TemplateCreatePayload {
  name: string;
  description: string;
  category: TemplateCategory;
  industry: string | null;
  tags: string[];
  payload: TemplatePayloadField;
}

/** POST /templates/{id}/ratings 请求体 (评分) */
export interface TemplateRatePayload {
  rating: number;
  comment: string | null;
}

/** POST /templates/{id}/copy 响应 */
export interface TemplateCopyResponse {
  copy_id: string;
  template_id: string;
  target_employee_id: string;
  target_employee_display_name: string;
  status: TemplateCopyStatus;
}

/** GET /templates/{id}/copies 响应 */
export interface TemplateCopiesResponse {
  items: TemplateCopyRecord[];
  total: number;
}

/** 单条复制记录 (DB scene_template_copies 表的 TS 投影) */
export interface TemplateCopyRecord {
  id: string;
  template_id: string;
  copied_by: string;
  target_employee_id: string | null;
  created_at: string;
}

/** Category 元数据 (中文 label + 颜色 tone, UI 用) */
export const TEMPLATE_CATEGORY_LABEL: Record<TemplateCategory, string> = {
  customer_service: "客服",
  sales: "销售",
  finance: "财务",
  hr: "人事",
  ops: "运维",
};

export const TEMPLATE_CATEGORY_TONE: Record<TemplateCategory, string> = {
  customer_service: "border-blue-200 bg-blue-50 text-blue-700",
  sales: "border-emerald-200 bg-emerald-50 text-emerald-700",
  finance: "border-amber-200 bg-amber-50 text-amber-700",
  hr: "border-purple-200 bg-purple-50 text-purple-700",
  ops: "border-slate-200 bg-slate-50 text-slate-600",
};

export const TEMPLATE_SOURCE_LABEL: Record<TemplateSource, string> = {
  user: "用户上传",
  builtin: "内置",
  imported: "导入",
};

export const TEMPLATE_SOURCE_TONE: Record<TemplateSource, string> = {
  user: "border-cyan-200 bg-cyan-50 text-cyan-700",
  builtin: "border-violet-200 bg-violet-50 text-violet-700",
  imported: "border-orange-200 bg-orange-50 text-orange-700",
};

/** Sort 选项 */
export type TemplateSort = "latest" | "popular" | "rating";

export const TEMPLATE_SORT_LABEL: Record<TemplateSort, string> = {
  latest: "最新",
  popular: "最热",
  rating: "高评分",
};