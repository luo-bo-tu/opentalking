// qiepai · 决策项单卡 (Phase ❷-5)
//
// 列表中的一张卡: title + description + status badge + owner + created_at
// + fact_snapshot 简显 (前 2-3 个 key/value).

import type { ReactNode } from "react";

import type { DecisionItem, DecisionStatus } from "./types";

export interface DecisionItemCardProps {
  item: DecisionItem;
  active: boolean;
  onClick: (id: string) => void;
}

const STATUS_LABEL: Record<DecisionStatus, string> = {
  pending: "待决",
  decided: "已定",
  cancelled: "取消",
};

const STATUS_TONE: Record<DecisionStatus, string> = {
  pending: "border-amber-200 bg-amber-50 text-amber-700",
  decided: "border-emerald-200 bg-emerald-50 text-emerald-700",
  cancelled: "border-slate-200 bg-slate-50 text-slate-500",
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

export function DecisionItemCard({
  item,
  active,
  onClick,
}: DecisionItemCardProps): ReactNode {
  const factKeys = Object.keys(item.fact_snapshot).filter(
    (k) => k !== "source" && k !== "as_of",
  );
  const preview = factKeys.slice(0, 3);

  return (
    <button
      type="button"
      onClick={() => onClick(item.id)}
      data-testid={`decision-card-${item.id}`}
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
          data-testid={`decision-status-${item.id}`}
        >
          {STATUS_LABEL[item.status]}
        </span>
      </header>

      <p className="line-clamp-2 text-[11px] leading-relaxed text-slate-600">
        {item.description}
      </p>

      {preview.length > 0 ? (
        <div className="mt-2 space-y-0.5 border-t border-slate-100 pt-2 text-[10px] text-slate-500">
          {preview.map((k) => {
            const v = item.fact_snapshot[k];
            const display =
              typeof v === "number"
                ? v.toLocaleString("zh-CN")
                : typeof v === "string"
                  ? v
                  : JSON.stringify(v);
            return (
              <div
                key={k}
                className="flex items-baseline justify-between gap-2"
              >
                <span className="truncate text-slate-500">{k}</span>
                <span className="shrink-0 font-mono tabular-nums text-slate-700">
                  {display}
                </span>
              </div>
            );
          })}
          {factKeys.length > preview.length ? (
            <p className="text-[9px] text-slate-400">
              +{factKeys.length - preview.length} 项更多 (点击查看)
            </p>
          ) : null}
        </div>
      ) : null}

      <footer className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] text-slate-400">
        <span>责任人 · {item.owner}</span>
        <span className="font-mono">{formatTime(item.created_at)}</span>
      </footer>
    </button>
  );
}
