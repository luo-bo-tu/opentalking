// qiepai · 目标达成进度条 (Phase ❷-4)
//
// Four horizontal progress bars (one per quarter). Each bar uses
// attainment (0-1.2 scale) — quarters over 100% render in emerald
// (over-achieved); quarters under 80% in amber (at risk); 80-100%
// in cyan (on track). Q3/Q4 (未发生) render as gray "暂无数据".

import type { ReactNode } from "react";

export interface TargetAttainmentItem {
  quarter: string;
  target: number;
  actual: number | null;
  attainment: number | null;
}

export interface TargetAttainmentChartData {
  metric_id: string;
  items: TargetAttainmentItem[] | null;
  source: string | null;
  as_of: string | null;
  freshness_seconds: number | null;
}

export interface TargetAttainmentChartProps {
  data: TargetAttainmentChartData | null;
}

const SCALE_MAX = 1.2; // bars render relative to 120% attainment.

function barColor(attainment: number | null): string {
  if (attainment === null || attainment === undefined) return "bg-slate-200";
  if (attainment > 1) return "bg-emerald-500";
  if (attainment >= 0.8) return "bg-cyan-600";
  return "bg-amber-500";
}

function formatYuan(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)} 亿元`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)} 万元`;
  return `${value.toLocaleString("zh-CN")} 元`;
}

export function TargetAttainmentChart({
  data,
}: TargetAttainmentChartProps): ReactNode {
  if (!data || !data.items || data.items.length === 0) {
    return (
      <p
        className="text-xs text-slate-400"
        data-testid="target-attainment-unavailable"
      >
        数据暂不可用
      </p>
    );
  }

  const items = data.items;

  return (
    <div className="space-y-3" data-testid="target-attainment-chart">
      {items.map((item, idx) => {
        const hasValue =
          item.attainment !== null && item.attainment !== undefined;
        const attainment = hasValue ? (item.attainment as number) : 0;
        const pct = hasValue ? Math.min(attainment, SCALE_MAX) / SCALE_MAX : 0;
        const over = hasValue && attainment > 1;
        const color = barColor(hasValue ? attainment : null);

        return (
          <div key={idx} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-slate-700">{item.quarter}</span>
              <span className="font-mono tabular-nums text-slate-500">
                {hasValue ? `${(attainment * 100).toFixed(1)}%` : "暂无数据"}
              </span>
            </div>
            <div className="relative h-3 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full transition-all ${color}`}
                style={{ width: `${(pct * 100).toFixed(1)}%` }}
              />
              {over ? (
                <span
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-bold text-emerald-700"
                  title={`超额完成 ${((attainment - 1) * 100).toFixed(1)}%`}
                >
                  ✓
                </span>
              ) : null}
            </div>
            <div className="flex justify-between text-[10px] text-slate-400">
              <span>目标 {formatYuan(item.target)}</span>
              <span>
                {item.actual !== null
                  ? `实际 ${formatYuan(item.actual)}`
                  : "实际 暂无数据"}
              </span>
            </div>
          </div>
        );
      })}
      <p
        className="truncate pt-1 font-mono text-[10px] text-slate-400"
        title={data.source ?? ""}
      >
        {data.source}
      </p>
    </div>
  );
}