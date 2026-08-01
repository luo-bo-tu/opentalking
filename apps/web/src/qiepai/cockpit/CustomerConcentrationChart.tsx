// qiepai · 客户集中度饼图 (Phase ❷-4)
//
// Hand-rolled SVG pie chart for the Top 5 customer share. Each slice is
// an SVG path of the form "M cx cy L x1 y1 A r r 0 large_arc 1 x2 y2 Z",
// with `large_arc` set when the slice spans more than half the circle.
// Legend on the right uses the same color as the slice + share_pct.

import type { ReactNode } from "react";

export interface CustomerConcentrationItem {
  customer: string;
  share_pct: number;
  revenue_ytd: number;
}

export interface CustomerConcentrationChartData {
  metric_id: string;
  items: CustomerConcentrationItem[] | null;
  source: string | null;
  as_of: string | null;
  freshness_seconds: number | null;
}

export interface CustomerConcentrationChartProps {
  data: CustomerConcentrationChartData | null;
}

const PIE_COLORS = ["#0891b2", "#06b6d4", "#22d3ee", "#67e8f9", "#a5f3fc"];
const PIE_W = 200;
const PIE_H = 200;
const PIE_CX = 100;
const PIE_CY = 100;
const PIE_R = 80;

export function CustomerConcentrationChart({
  data,
}: CustomerConcentrationChartProps): ReactNode {
  if (!data || !data.items || data.items.length === 0) {
    return (
      <p
        className="text-xs text-slate-400"
        data-testid="customer-concentration-unavailable"
      >
        数据暂不可用
      </p>
    );
  }

  const items = data.items;
  const total = items.reduce((s, i) => s + (i.share_pct || 0), 0);
  let cursor = -Math.PI / 2; // start at top

  const slices = items.map((item, idx) => {
    const portion = total > 0 ? item.share_pct / total : 0;
    const angle = portion * 2 * Math.PI;
    const startX = PIE_CX + PIE_R * Math.cos(cursor);
    const startY = PIE_CY + PIE_R * Math.sin(cursor);
    const endX = PIE_CX + PIE_R * Math.cos(cursor + angle);
    const endY = PIE_CY + PIE_R * Math.sin(cursor + angle);
    const largeArc = angle > Math.PI ? 1 : 0;
    const d = `M ${PIE_CX} ${PIE_CY} L ${startX} ${startY} A ${PIE_R} ${PIE_R} 0 ${largeArc} 1 ${endX} ${endY} Z`;
    cursor += angle;
    return { d, color: PIE_COLORS[idx % PIE_COLORS.length], item, idx };
  });

  return (
    <div
      className="flex flex-col gap-3 sm:flex-row sm:items-start"
      data-testid="customer-concentration-chart"
    >
      <svg
        viewBox={`0 0 ${PIE_W} ${PIE_H}`}
        className="h-40 w-40 shrink-0 self-center sm:self-auto"
        role="img"
        aria-label="客户集中度饼图"
      >
        {slices.map((s) => (
          <path key={s.idx} d={s.d} fill={s.color} stroke="white" strokeWidth={1.5} />
        ))}
      </svg>
      <div className="min-w-0 flex-1 space-y-1.5 text-xs">
        {items.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: PIE_COLORS[idx % PIE_COLORS.length] }}
            />
            <span className="min-w-0 flex-1 truncate text-slate-700">
              {item.customer}
            </span>
            <span className="font-mono tabular-nums text-slate-900">
              {(item.share_pct ?? 0).toFixed(1)}%
            </span>
          </div>
        ))}
        <p
          className="truncate pt-1 font-mono text-[10px] text-slate-400"
          title={data.source ?? ""}
        >
          {data.source}
        </p>
      </div>
    </div>
  );
}