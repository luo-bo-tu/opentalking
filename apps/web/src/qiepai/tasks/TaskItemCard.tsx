// qiepai · 业务任务单卡 (Phase ❷-6)
//
// 列表中的一张卡: title + status badge + priority badge + decision 关联
// + assignee + description 摘要 + created_at

import type { ReactNode } from "react";

import type { TaskItem, TaskPriority, TaskStatus } from "./types";

export interface TaskItemCardProps {
  item: TaskItem;
  active: boolean;
  onClick: (id: string) => void;
}

const STATUS_LABEL: Record<TaskStatus, string> = {
  todo: "待办",
  in_progress: "进行中",
  done: "已完成",
  cancelled: "已取消",
};

const STATUS_TONE: Record<TaskStatus, string> = {
  todo: "border-slate-200 bg-slate-50 text-slate-700",
  in_progress: "border-cyan-200 bg-cyan-50 text-cyan-700",
  done: "border-emerald-200 bg-emerald-50 text-emerald-700",
  cancelled: "border-slate-200 bg-slate-50 text-slate-400",
};

const PRIORITY_LABEL: Record<TaskPriority, string> = {
  low: "低",
  normal: "中",
  high: "高",
  urgent: "紧急",
};

const PRIORITY_TONE: Record<TaskPriority, string> = {
  low: "text-slate-400",
  normal: "text-slate-500",
  high: "text-amber-700",
  urgent: "text-red-700",
};

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function TaskItemCard({
  item,
  active,
  onClick,
}: TaskItemCardProps): ReactNode {
  return (
    <button
      type="button"
      onClick={() => onClick(item.id)}
      data-testid={`task-card-${item.id}`}
      className={`w-full rounded-lg border bg-white p-3 text-left shadow-sm transition ${
        active
          ? "border-cyan-400 ring-2 ring-cyan-200"
          : "border-slate-200 hover:border-cyan-300"
      }`}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <h3 className="line-clamp-2 text-sm font-semibold text-slate-950">
          {item.title}
        </h3>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_TONE[item.status]}`}
          data-testid={`task-status-${item.id}`}
        >
          {STATUS_LABEL[item.status]}
        </span>
      </header>

      <p className="line-clamp-2 text-[11px] leading-relaxed text-slate-600">
        {item.description}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-100 pt-2 text-[10px] text-slate-500">
        {item.decision_id !== null ? (
          <span
            className="inline-flex items-center gap-1 rounded border border-purple-100 bg-purple-50 px-1.5 py-0.5 text-[10px] text-purple-700"
            title={`关联决策项: ${item.decision_title ?? item.decision_id}`}
          >
            <span className="font-mono">{item.decision_id}</span>
          </span>
        ) : null}
        <span className={`font-medium ${PRIORITY_TONE[item.priority]}`}>
          优先级 · {PRIORITY_LABEL[item.priority]}
        </span>
        <span className="text-slate-400">
          {item.assignee_name ?? "未分配"}
        </span>
      </div>

      <footer className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] text-slate-400">
        <span>{item.id}</span>
        <span className="font-mono">{formatTime(item.created_at)}</span>
      </footer>
    </button>
  );
}
