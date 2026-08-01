// qiepai · 数字员工单卡 (Phase ❷-6)
//
// 列表中的一张卡: display_name + role + status badge + lifecycle 进度条
// + persona 关联标识 (1:1 已建显示 ✓ / 未建显示 ○)

import type { ReactNode } from "react";

import type { Employee } from "./types";
import {
  LIFECYCLE_LABEL,
  LIFECYCLE_STATES,
  LIFECYCLE_TONE,
} from "./types";

export interface EmployeeCardProps {
  item: Employee;
  active: boolean;
  onClick: (id: string) => void;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function EmployeeCard({
  item,
  active,
  onClick,
}: EmployeeCardProps): ReactNode {
  const currentIndex = LIFECYCLE_STATES.indexOf(item.status);

  return (
    <button
      type="button"
      onClick={() => onClick(item.id)}
      data-testid={`employee-card-${item.id}`}
      className={`w-full rounded-lg border bg-white p-3 text-left shadow-sm transition ${
        active
          ? "border-cyan-400 ring-2 ring-cyan-200"
          : "border-slate-200 hover:border-cyan-300"
      }`}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-950">
            {item.display_name}
          </h3>
          <p className="text-[11px] text-slate-500">{item.role}</p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${LIFECYCLE_TONE[item.status]}`}
          data-testid={`employee-status-${item.id}`}
        >
          {LIFECYCLE_LABEL[item.status]}
        </span>
      </header>

      {/* 简化 lifecycle 进度条 */}
      <div className="mb-2 flex items-center gap-0.5" aria-label="lifecycle">
        {LIFECYCLE_STATES.map((state, idx) => {
          const isPast = idx < currentIndex;
          const isCurrent = idx === currentIndex;
          return (
            <div
              key={state}
              className={`h-1.5 flex-1 rounded-full ${
                isCurrent
                  ? "bg-cyan-500"
                  : isPast
                    ? "bg-emerald-400"
                    : "bg-slate-200"
              }`}
              title={`${idx + 1}. ${LIFECYCLE_LABEL[state]}`}
            />
          );
        })}
      </div>

      <div className="flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] text-slate-500">
        <span
          className={`inline-flex items-center gap-1 ${
            item.persona_id !== null ? "text-purple-700" : "text-slate-400"
          }`}
          title={
            item.persona_id !== null
              ? `已关联 persona: ${item.persona_id}`
              : "未关联 persona (1:1 待建)"
          }
        >
          {item.persona_id !== null ? "✓ persona 1:1" : "○ 无 persona"}
        </span>
        <span className="font-mono">{item.id}</span>
      </div>

      <footer className="mt-1 flex items-center justify-between text-[10px] text-slate-400">
        <span>创建于 {formatTime(item.created_at)}</span>
      </footer>
    </button>
  );
}
