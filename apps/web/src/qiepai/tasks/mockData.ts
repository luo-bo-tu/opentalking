// qiepai · 业务任务 mock 数据 (Phase ❷-6 前端先行)
//
// 后端 /qiepai/tasks 还在 ❷-1 stub, 前端先用这份 mock 渲染真实 UI 结构.
// 数据语义合理 (与 ❷-4 mock JSON / ❷-5 mock decisions 关联),
// 后端就绪后所有 fetch 自动切真, 这份文件作废.
//
// 数据来源全部标 source=mock://..., UI 顶部显式标 "mock 模式".

import type { TaskItem } from "./types";

export const MOCK_TASKS: TaskItem[] = [
  {
    id: "task-001",
    title: "专项催收小组组建 (来自决策 dec-003)",
    description:
      "决策 dec-003 已定: 启动专项催收小组, 90 天+ 客户由法务介入发函。本任务跟踪执行进度。",
    decision_id: "dec-003",
    decision_title: "应收账款专项回收计划",
    assignee_id: "emp-cfo-001",
    assignee_name: "财务数字员工 - 招财",
    status: "in_progress",
    priority: "high",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-26T09:00:00+08:00",
  },
  {
    id: "task-002",
    title: "客户 A 续约时间表确认",
    description:
      "Q4 营收预警应对 (dec-001) 推断客户 A 续约延迟贡献约 60% 降幅, 需 CRM 数据确认 + 联系客户。",
    decision_id: "dec-001",
    decision_title: "Q4 营收预警应对",
    assignee_id: "emp-sales-002",
    assignee_name: "销售数字员工 - 小销",
    status: "in_progress",
    priority: "urgent",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-30T14:20:00+08:00",
  },
  {
    id: "task-003",
    title: "中腰部客户拓展计划制定",
    description:
      "决策 dec-002 已建议 Q4 启动中腰部客户拓展计划, 目标新增 5 家 100 万级客户, 需销售总监出方案。",
    decision_id: "dec-002",
    decision_title: "客户集中度过高 - Top 3 占 78%",
    assignee_id: "emp-sales-002",
    assignee_name: "销售数字员工 - 小销",
    status: "todo",
    priority: "high",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-30T16:00:00+08:00",
  },
  {
    id: "task-004",
    title: "Top 3 客户专属服务团队组建",
    description:
      "建立 Top 3 客户专属服务团队, 续约率纳入 KPI 强制考核。",
    decision_id: "dec-002",
    decision_title: "客户集中度过高 - Top 3 占 78%",
    assignee_id: null,
    assignee_name: null,
    status: "todo",
    priority: "normal",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-30T16:05:00+08:00",
  },
  {
    id: "task-005",
    title: "Q3 冲刺取消后资源转 Q4 重排",
    description:
      "决策 dec-004 取消 Q3 冲刺, 资源转入 Q4, 需销售总监出资源重排方案。",
    decision_id: "dec-004",
    decision_title: "Q3 销售目标冲刺方案",
    assignee_id: "emp-sales-002",
    assignee_name: "销售数字员工 - 小销",
    status: "done",
    priority: "normal",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-22T14:00:00+08:00",
  },
  {
    id: "task-006",
    title: "现金流缺口应急方案 (来自决策 dec-005)",
    description:
      "决策 dec-005 建议优先解决 AR 回收 (dec-003), 若 30 天内未改善启动融资。本任务跟踪融资评估准备。",
    decision_id: "dec-005",
    decision_title: "7 月现金流缺口预警",
    assignee_id: null,
    assignee_name: null,
    status: "cancelled",
    priority: "low",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-31T09:00:00+08:00",
  },
  {
    id: "task-007",
    title: "供应商应付账款延期谈判",
    description:
      "决策 dec-005 建议与 Top 3 供应商协商应付账款延期 30 天, 需采购总监联系。",
    decision_id: "dec-005",
    decision_title: "7 月现金流缺口预警",
    assignee_id: "emp-cfo-001",
    assignee_name: "财务数字员工 - 招财",
    status: "todo",
    priority: "high",
    source: "mock://business-tasks/v1",
    created_at: "2026-07-31T09:30:00+08:00",
  },
];
