// qiepai · 业务任务详情面板 (Phase ❷-6)
//
// 右栏详情: 完整描述 + 决策关联 + 责任员工 + status 转换按钮 + source 信息
// status 转换遵循 TASK_TRANSITIONS (前端校验, 后端是权威)

import type { ReactNode } from "react";

import type {
  TaskItem,
  TaskPatchPayload,
  TaskStatus,
} from "./types";
import { TASK_TRANSITIONS } from "./types";

export interface TaskDetailPanelProps {
  item: TaskItem;
  onTransition: (id: string, patch: TaskPatchPayload) => Promise<void>;
}

const STATUS_LABEL: Record<TaskStatus, string> = {
  todo: "待办",
  in_progress: "进行中",
  done: "已完成",
  cancelled: "已取消",
};

const STATUS_TONE: Record<TaskStatus, string> = {
  todo: "border-slate-300 bg-slate-100 text-slate-700",
  in_progress: "border-cyan-300 bg-cyan-100 text-cyan-700",
  done: "border-emerald-300 bg-emerald-100 text-emerald-700",
  cancelled: "border-slate-300 bg-slate-100 text-slate-500",
};

const ACTION_LABEL: Record<TaskStatus, string> = {
  todo: "重置为待办",
  in_progress: "开始 / 重新进行",
  done: "标记为已完成",
  cancelled: "取消任务",
};

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function TaskDetailPanel({
  item,
  onTransition,
}: TaskDetailPanelProps): ReactNode {
  const allowed = TASK_TRANSITIONS[item.status];

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white"
      data-testid="task-detail"
    >
      {/* header */}
      <header className="space-y-2 border-b border-slate-200 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[10px] font-medium text-slate-500">
              业务任务 · {item.id}
            </p>
            <h2 className="mt-0.5 line-clamp-2 text-base font-semibold text-slate-950">
              {item.title}
            </h2>
          </div>
          <span
            className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${STATUS_TONE[item.status]}`}
          >
            {STATUS_LABEL[item.status]}
          </span>
        </div>
        <p className="text-xs leading-relaxed text-slate-600">
          {item.description}
        </p>
      </header>

      {/* meta */}
      <section className="grid grid-cols-2 gap-3 border-b border-slate-200 p-4 text-xs">
        <div>
          <p className="text-[10px] text-slate-400">责任员工</p>
          <p className="mt-0.5 font-medium text-slate-700">
            {item.assignee_name ?? "未分配"}
          </p>
          {item.assignee_id !== null ? (
            <p className="mt-0.5 font-mono text-[10px] text-slate-400">
              {item.assignee_id}
            </p>
          ) : null}
        </div>
        <div>
          <p className="text-[10px] text-slate-400">创建时间</p>
          <p className="mt-0.5 font-mono text-slate-700">
            {formatTime(item.created_at)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400">优先级</p>
          <p className="mt-0.5 font-medium text-slate-700">{item.priority}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400">数据来源</p>
          <p
            className="mt-0.5 truncate font-mono text-[11px] text-slate-700"
            title={item.source}
          >
            {item.source}
          </p>
        </div>
        {item.decision_id !== null ? (
          <div className="col-span-2">
            <p className="text-[10px] text-slate-400">关联决策项</p>
            <div className="mt-0.5 rounded border border-purple-100 bg-purple-50 p-2">
              <p className="font-mono text-[11px] text-purple-700">
                {item.decision_id}
              </p>
              <p className="mt-0.5 text-xs text-slate-700">
                {item.decision_title ?? "(决策标题未缓存)"}
              </p>
            </div>
          </div>
        ) : null}
      </section>

      {/* 状态转换 */}
      <section className="border-b border-slate-200 p-4">
        <h3 className="mb-2 text-xs font-semibold text-slate-700">
          状态转换
        </h3>
        {allowed.length === 0 ? (
          <p className="rounded border border-dashed border-slate-200 p-3 text-[11px] text-slate-400">
            当前状态无可用转换
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {allowed.map((next) => (
              <button
                key={next}
                type="button"
                onClick={() => void onTransition(item.id, { status: next })}
                className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700"
                data-testid={`task-transition-${next}`}
                title={`状态变更为 ${STATUS_LABEL[next]}`}
              >
                {ACTION_LABEL[next]}
              </button>
            ))}
          </div>
        )}
        <p className="mt-2 text-[10px] text-slate-400">
          前端校验合法转换, 实际以 backend PATCH 为准
        </p>
      </section>

      {/* footer */}
      <footer className="mt-auto p-4 text-[10px] text-slate-400">
        数据来源全部标 source, 缺数据显式 unavailable (❷-3 decision #5)
      </footer>
    </div>
  );
}
