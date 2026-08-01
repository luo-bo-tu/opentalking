// qiepai · 业务任务列表 (Phase ❷-6)
//
// 左栏列表: status filter + TaskItemCard 列表
// filter tabs: 全部 / 待办 / 进行中 / 已完成 / 已取消 (跟 TaskStatus 对齐)

import type { ReactNode } from "react";

import { TaskItemCard } from "./TaskItemCard";
import type { TaskItem, TaskStatus, TaskStatusFilter } from "./types";

export interface TaskListProps {
  items: TaskItem[];
  filter: TaskStatusFilter;
  onFilterChange: (filter: TaskStatusFilter) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const FILTERS: Array<{ key: TaskStatusFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "todo", label: "待办" },
  { key: "in_progress", label: "进行中" },
  { key: "done", label: "已完成" },
  { key: "cancelled", label: "已取消" },
];

export function TaskList({
  items,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
}: TaskListProps): ReactNode {
  const filtered =
    filter === "all" ? items : items.filter((i) => i.status === filter);

  return (
    <div
      className="flex h-full min-h-0 flex-col rounded-lg border border-slate-200 bg-white"
      data-testid="task-list"
    >
      {/* filter tabs */}
      <nav
        className="flex flex-wrap items-center gap-1 border-b border-slate-200 p-2"
        aria-label="任务状态过滤"
      >
        {FILTERS.map((f) => {
          const active = filter === f.key;
          const count =
            f.key === "all"
              ? items.length
              : items.filter((i: TaskItem) => i.status === (f.key as TaskStatus))
                .length;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => onFilterChange(f.key)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                active
                  ? "bg-cyan-50 text-cyan-700"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
              }`}
              data-testid={`task-filter-${f.key}`}
            >
              {f.label}
              <span className="ml-1 text-[10px] tabular-nums text-slate-400">
                {count}
              </span>
            </button>
          );
        })}
      </nav>

      {/* list */}
      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {filtered.length === 0 ? (
          <p className="rounded border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">
            {filter === "all"
              ? "暂无任务"
              : `暂无${FILTERS.find((f) => f.key === filter)?.label ?? filter}任务`}
          </p>
        ) : (
          filtered.map((item) => (
            <TaskItemCard
              key={item.id}
              item={item}
              active={item.id === selectedId}
              onClick={onSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}
