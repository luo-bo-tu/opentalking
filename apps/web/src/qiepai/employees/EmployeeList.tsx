// qiepai · 数字员工列表 (Phase ❷-6)
//
// 左栏列表: status filter + EmployeeCard 列表
// filter: 全部 / 草稿 / 配置中 / 待发布 / 已发布 / 已暂停 / 已退役

import type { ReactNode } from "react";

import { EmployeeCard } from "./EmployeeCard";
import type { Employee, EmployeeStatus } from "./types";

export type EmployeeStatusFilter = "all" | EmployeeStatus;

export interface EmployeeListProps {
  items: Employee[];
  filter: EmployeeStatusFilter;
  onFilterChange: (filter: EmployeeStatusFilter) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const FILTERS: Array<{ key: EmployeeStatusFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "draft", label: "草稿" },
  { key: "configuring", label: "配置中" },
  { key: "ready", label: "待发布" },
  { key: "published", label: "已发布" },
  { key: "suspended", label: "已暂停" },
  { key: "retired", label: "已退役" },
];

export function EmployeeList({
  items,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
}: EmployeeListProps): ReactNode {
  const filtered =
    filter === "all" ? items : items.filter((i) => i.status === filter);

  return (
    <div
      className="flex h-full min-h-0 flex-col rounded-lg border border-slate-200 bg-white"
      data-testid="employee-list"
    >
      {/* filter tabs */}
      <nav
        className="flex flex-wrap items-center gap-1 border-b border-slate-200 p-2"
        aria-label="数字员工 lifecycle 状态过滤"
      >
        {FILTERS.map((f) => {
          const active = filter === f.key;
          const count =
            f.key === "all"
              ? items.length
              : items.filter((i: Employee) => i.status === (f.key as EmployeeStatus))
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
              data-testid={`employee-filter-${f.key}`}
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
              ? "暂无数字员工"
              : `暂无${FILTERS.find((f) => f.key === filter)?.label ?? filter}数字员工`}
          </p>
        ) : (
          filtered.map((item) => (
            <EmployeeCard
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
