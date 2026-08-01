// qiepai · 业务任务类型定义 (Phase ❷-6)
//
// 设计原则 (架构 v1.1 § 2 + ❷-6 子阶段):
//   - 业务任务不复用 OpenClaw tasks, 单独建 (❷-3 decision #3)
//   - 与 decision_item 关联 (decision_id FK, 可空)
//   - mock 数据标 source=mock://... (❷-3 decision #5)
//   - 缺数据显式 unavailable, 不显示 0

/** 任务状态机 (❷-6 子阶段 § 6.1) */
export type TaskStatus = "todo" | "in_progress" | "done" | "cancelled";

/** 任务优先级 (UI 提示, 后端可扩展) */
export type TaskPriority = "low" | "normal" | "high" | "urgent";

/** 单条业务任务 (DB business_tasks 表的 TS 投影) */
export interface TaskItem {
  id: string;
  title: string;
  description: string;
  /** 关联决策项 id (可空, 见 decisions 表 FK) */
  decision_id: string | null;
  /** 关联决策项标题 (冗余存, 避免前端再查决策) */
  decision_title: string | null;
  /** 责任员工 id (employees.id, 可空表示未分配) */
  assignee_id: string | null;
  /** 责任员工 display_name (冗余存) */
  assignee_name: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  /** 数据来源 (mock://... 或后端实际来源) */
  source: string;
  created_at: string;
}

/** 状态过滤 */
export type TaskStatusFilter = "all" | TaskStatus;

/** 状态变更 payload (PATCH /qiepai/tasks/{id}) */
export interface TaskPatchPayload {
  status: TaskStatus;
}

/** 任务状态机合法跳转 (UI 端校验, 后端是权威) */
export const TASK_TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  todo: ["in_progress", "cancelled"],
  in_progress: ["done", "cancelled", "todo"],
  done: ["in_progress"], // 重开
  cancelled: ["todo"], // 重启
};
