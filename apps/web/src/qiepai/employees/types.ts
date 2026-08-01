// qiepai · 数字员工类型定义 (Phase ❷-6)
//
// 设计原则 (架构 v1.1 § 2 + ❷-6 子阶段 § 6.2):
//   - 数字员工 employee 与 persona 共存, 1:1 关联 (❷-3 decision #2)
//   - publish state machine: draft → configuring → ready → published → suspended → retired
//   - 发布前检查: readiness_p0 AND readiness_p1 AND sync_state OK (架构 § 21.5)
//   - 状态机拒绝跳跃 (架构 § 21.5 硬约束)
//   - mock 数据标 source=mock://... (❷-3 decision #5)

/** 数字员工 lifecycle 状态机 (架构 v1.1 § 21.5) */
export type EmployeeStatus =
  | "draft"
  | "configuring"
  | "ready"
  | "published"
  | "suspended"
  | "retired";

/** 同步状态 (revision 同步到 persona / runtime 的状态) */
export type SyncState = "pending" | "in_sync" | "error" | "drifted";

/** revision publish state (跟 employee status 同义, 但存在数据库里) */
export type RevisionPublishState =
  | "draft"
  | "configuring"
  | "ready"
  | "published"
  | "suspended"
  | "retired";

/** 单条 revision (DB employee_revisions 表的 TS 投影) */
export interface EmployeeRevision {
  id: string;
  employee_id: string;
  revision_number: number;
  /** workspace 文件 hash (用于审计) */
  workspace_file_hash: string;
  /** 配置快照 (JSON) */
  config_snapshot: Record<string, unknown>;
  publish_state: RevisionPublishState;
  /** P0 强制项: workspace 完整 + persona 已建 + config 校验通过 */
  readiness_p0: boolean;
  /** P1 建议项: skill set 完整 + 验收测试通过 + 备份完成 */
  readiness_p1: boolean;
  sync_state: SyncState;
  /** readiness 失败的简短原因 (可选, UI 显示) */
  readiness_reason: string | null;
  created_at: string;
}

/** Persona 1:1 关联引用 (DB employees.persona_id → personas.id) */
export interface PersonaRef {
  id: string;
  display_name: string;
}

/** 单条数字员工 (DB employees 表的 TS 投影) */
export interface Employee {
  id: string;
  display_name: string;
  role: string;
  status: EmployeeStatus;
  current_revision_id: string | null;
  persona_id: string | null;
  /** 数据来源 (mock://... 或后端实际来源) */
  source: string;
  created_at: string;
}

/** Lifecycle 状态机合法转换 (架构 § 21.5) */
export const LIFECYCLE_TRANSITIONS: Record<EmployeeStatus, EmployeeStatus[]> = {
  draft: ["configuring"],
  configuring: ["ready"],
  ready: ["published"],
  published: ["suspended", "retired"],
  suspended: ["published", "retired"],
  retired: [], // 终态
};

/** 所有 lifecycle 状态 (UI 渲染顺序) */
export const LIFECYCLE_STATES: EmployeeStatus[] = [
  "draft",
  "configuring",
  "ready",
  "published",
  "suspended",
  "retired",
];

/** 发布前 readiness 校验结果 */
export interface ReadinessCheck {
  /** 全部通过 = true */
  passed: boolean;
  /** 未满足的项列表 (用于 tooltip) */
  issues: string[];
}

/** 校验发布前置条件 (❷-6 § 6.2 + 架构 § 21.5) */
export function checkPublishReadiness(
  revision: EmployeeRevision | null,
): ReadinessCheck {
  const issues: string[] = [];
  if (revision === null) {
    issues.push("无当前 revision");
    return { passed: false, issues };
  }
  if (!revision.readiness_p0) {
    issues.push("readiness_p0 未通过 (workspace / persona / config 校验未完成)");
  }
  if (!revision.readiness_p1) {
    issues.push("readiness_p1 未通过 (skill set / 验收 / 备份 未完成)");
  }
  if (revision.sync_state === "error") {
    issues.push("sync_state = error (同步异常, 需排查)");
  }
  if (revision.sync_state === "drifted") {
    issues.push("sync_state = drifted (与 persona 漂移, 需重新同步)");
  }
  return { passed: issues.length === 0, issues };
}

/** status 颜色 / 标签 (UI 用) */
export const LIFECYCLE_LABEL: Record<EmployeeStatus, string> = {
  draft: "草稿",
  configuring: "配置中",
  ready: "待发布",
  published: "已发布",
  suspended: "已暂停",
  retired: "已退役",
};

export const LIFECYCLE_TONE: Record<EmployeeStatus, string> = {
  draft: "border-slate-200 bg-slate-50 text-slate-600",
  configuring: "border-amber-200 bg-amber-50 text-amber-700",
  ready: "border-cyan-200 bg-cyan-50 text-cyan-700",
  published: "border-emerald-200 bg-emerald-50 text-emerald-700",
  suspended: "border-orange-200 bg-orange-50 text-orange-700",
  retired: "border-slate-300 bg-slate-100 text-slate-500",
};

export const SYNC_STATE_LABEL: Record<SyncState, string> = {
  pending: "待同步",
  in_sync: "已同步",
  error: "同步异常",
  drifted: "漂移",
};

export const SYNC_STATE_TONE: Record<SyncState, string> = {
  pending: "border-slate-200 bg-slate-50 text-slate-600",
  in_sync: "border-emerald-200 bg-emerald-50 text-emerald-700",
  error: "border-red-200 bg-red-50 text-red-700",
  drifted: "border-orange-200 bg-orange-50 text-orange-700",
};
