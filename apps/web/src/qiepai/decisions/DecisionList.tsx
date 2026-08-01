// qiepai · 决策项列表 (Phase ❷-5)
//
// 左栏列表: status filter + DecisionItemCard 列表
// filter tabs: 全部 / 待决 / 已定 / 取消 (跟 DecisionStatus 对齐)

import type { ReactNode } from "react";

import { DecisionItemCard } from "./DecisionItemCard";
import type { DecisionItem, DecisionStatus } from "./types";

export type StatusFilter = "all" | DecisionStatus;

export interface DecisionListProps {
  items: DecisionItem[];
  filter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const FILTERS: Array<{ key: StatusFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "pending", label: "待决" },
  { key: "decided", label: "已定" },
  { key: "cancelled", label: "取消" },
];

export function DecisionList({
  items,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
}: DecisionListProps): ReactNode {
  const filtered =
    filter === "all" ? items : items.filter((i) => i.status === filter);

  return (
    <div
      className="flex h-full min-h-0 flex-col rounded-lg border border-slate-200 bg-white"
      data-testid="decision-list"
    >
      {/* filter tabs */}
      <nav
        className="flex items-center gap-1 border-b border-slate-200 p-2"
        aria-label="决策状态过滤"
      >
        {FILTERS.map((f) => {
          const active = filter === f.key;
          const count =
            f.key === "all"
              ? items.length
              : items.filter((i) => i.status === f.key).length;
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
              data-testid={`decision-filter-${f.key}`}
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
              ? "暂无决策项"
              : `暂无${FILTERS.find((f) => f.key === filter)?.label ?? filter}决策项`}
          </p>
        ) : (
          filtered.map((item) => (
            <DecisionItemCard
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
