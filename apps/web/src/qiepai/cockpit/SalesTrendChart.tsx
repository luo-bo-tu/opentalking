// qiepai · 销售趋势折线图 (Phase ❷-4)
//
// Hand-rolled SVG line chart — no recharts/d3 dependency (per ❷-4 spec,
// no new deps allowed). 12 months of revenue drawn as a polyline with
// axis dots. The as_of/source footer is the same provenance label as
// KpiCard so the operator can correlate the line with its data source.

import type { ReactNode } from "react";

export interface SalesTrendItem {
  month: string;
  revenue: number;
  orders: number;
}

export interface SalesTrendChartData {
  metric_id: string;
  items: SalesTrendItem[] | null;
  source: string | null;
  as_of: string | null;
  freshness_seconds: number | null;
}

export interface SalesTrendChartProps {
  data: SalesTrendChartData | null;
}

const W = 480;
const H = 220;
const PAD_X = 36;
const PAD_Y = 20;
const STROKE = "#0891b2";

export function SalesTrendChart({ data }: SalesTrendChartProps): ReactNode {
  if (!data || !data.items || data.items.length === 0) {
    return (
      <p className="text-xs text-slate-400" data-testid="sales-trend-unavailable">
        数据暂不可用
      </p>
    );
  }

  const items = data.items;
  const innerW = W - PAD_X * 2;
  const innerH = H - PAD_Y * 2;
  const maxRev = Math.max(...items.map((i) => i.revenue));
  const minRev = Math.min(...items.map((i) => i.revenue));
  const xStep = items.length > 1 ? innerW / (items.length - 1) : 0;

  const points = items.map((item, idx) => {
    const x = PAD_X + idx * xStep;
    const norm = maxRev === minRev ? 0.5 : (item.revenue - minRev) / (maxRev - minRev);
    const y = PAD_Y + innerH - norm * innerH;
    return { x, y, item, idx };
  });

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
    .join(" ");

  // Y-axis tick lines (3 evenly spaced)
  const yTicks = [0, 0.5, 1].map((t) => {
    const y = PAD_Y + innerH - t * innerH;
    const val = minRev + t * (maxRev - minRev);
    return { y, val };
  });

  return (
    <div className="space-y-2" data-testid="sales-trend-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-44 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="销售趋势折线图"
      >
        {/* Y axis ticks + labels */}
        {yTicks.map((t, i) => (
          <g key={`yt-${i}`}>
            <line
              x1={PAD_X}
              x2={W - PAD_X}
              y1={t.y}
              y2={t.y}
              stroke="#e2e8f0"
              strokeWidth={1}
              strokeDasharray={i === 0 ? "0" : "2 3"}
            />
            <text
              x={PAD_X - 6}
              y={t.y + 3}
              textAnchor="end"
              fontSize={9}
              fill="#94a3b8"
            >
              {t.val >= 1e4 ? `${(t.val / 1e4).toFixed(0)}万` : t.val.toFixed(0)}
            </text>
          </g>
        ))}
        {/* X axis baseline */}
        <line
          x1={PAD_X}
          x2={W - PAD_X}
          y1={PAD_Y + innerH}
          y2={PAD_Y + innerH}
          stroke="#cbd5e1"
          strokeWidth={1}
        />
        {/* line path */}
        <path d={pathD} fill="none" stroke={STROKE} strokeWidth={2} strokeLinejoin="round" />
        {/* dots */}
        {points.map((p) => (
          <circle key={`pt-${p.idx}`} cx={p.x} cy={p.y} r={2.5} fill={STROKE} />
        ))}
        {/* X labels (every other month to avoid clutter) */}
        {points.map((p) => {
          if (p.idx % 2 !== 0 && p.idx !== points.length - 1) return null;
          return (
            <text
              key={`xt-${p.idx}`}
              x={p.x}
              y={H - 4}
              textAnchor="middle"
              fontSize={9}
              fill="#94a3b8"
            >
              {p.item.month.slice(5)}
            </text>
          );
        })}
      </svg>
      <p
        className="truncate font-mono text-[10px] text-slate-400"
        title={data.source ?? ""}
      >
        {data.source}
      </p>
    </div>
  );
}