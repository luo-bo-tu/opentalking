// qiepai · 订单 / 应收 堆叠柱图 (Phase ❷-4)
//
// Hand-rolled SVG stacked bar chart: 12 months × (orders + ar_outstanding).
// Each bar is two stacked rectangles; orders (cyan) on the bottom,
// ar_outstanding (amber) on top. The visual "thickness" of the amber
// segment shows the AR load relative to current orders.

import type { ReactNode } from "react";

export interface OrdersArItem {
  month: string;
  orders: number;
  ar_outstanding: number;
}

export interface OrdersArChartData {
  metric_id: string;
  items: OrdersArItem[] | null;
  source: string | null;
  as_of: string | null;
  freshness_seconds: number | null;
}

export interface OrdersArChartProps {
  data: OrdersArChartData | null;
}

const W = 480;
const H = 220;
const PAD_X = 32;
const PAD_Y = 20;
const COLOR_ORDERS = "#0891b2";
const COLOR_AR = "#fbbf24";

export function OrdersArChart({ data }: OrdersArChartProps): ReactNode {
  if (!data || !data.items || data.items.length === 0) {
    return (
      <p className="text-xs text-slate-400" data-testid="orders-ar-unavailable">
        数据暂不可用
      </p>
    );
  }

  const items = data.items;
  const innerW = W - PAD_X * 2;
  const innerH = H - PAD_Y * 2;
  const maxTotal = Math.max(
    ...items.map((i) => (i.orders ?? 0) + (i.ar_outstanding ?? 0)),
  );
  const slot = innerW / items.length;
  const barW = slot * 0.65;

  const yTicks = [0, 0.5, 1].map((t) => {
    const y = PAD_Y + innerH - t * innerH;
    const val = t * maxTotal;
    return { y, val };
  });

  return (
    <div className="space-y-2" data-testid="orders-ar-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-44 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="订单应收堆叠柱图"
      >
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
        {items.map((item, idx) => {
          const total = (item.orders ?? 0) + (item.ar_outstanding ?? 0);
          const ordersH = maxTotal > 0 ? ((item.orders ?? 0) / maxTotal) * innerH : 0;
          const arH = maxTotal > 0 ? ((item.ar_outstanding ?? 0) / maxTotal) * innerH : 0;
          const x = PAD_X + idx * slot + (slot - barW) / 2;
          const ordersY = PAD_Y + innerH - ordersH;
          const arY = ordersY - arH;
          return (
            <g key={`bar-${idx}`}>
              <rect
                x={x}
                y={ordersY}
                width={barW}
                height={Math.max(ordersH, 0)}
                fill={COLOR_ORDERS}
              />
              <rect
                x={x}
                y={arY}
                width={barW}
                height={Math.max(arH, 0)}
                fill={COLOR_AR}
              />
              {idx % 2 === 0 ? (
                <text
                  x={x + barW / 2}
                  y={H - 4}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#94a3b8"
                >
                  {item.month.slice(5)}
                </text>
              ) : null}
              {total === 0 ? null : null}
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 rounded-sm"
            style={{ backgroundColor: COLOR_ORDERS }}
          />
          订单
        </span>
        <span className="inline-flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 rounded-sm"
            style={{ backgroundColor: COLOR_AR }}
          />
          应收
        </span>
        <p
          className="ml-auto truncate font-mono text-slate-400"
          title={data.source ?? ""}
        >
          {data.source}
        </p>
      </div>
    </div>
  );
}