// qiepai · 老板驾驶舱 KPI 卡片 (Phase ❷-4)
//
// Renders one KPI card in the 5-card grid. Implements the three-state
// contract from 架构 § 21.1 + ❷-3 loader docstring:
//
//   - value !== null  → render big number + unit (formatted by card_format)
//   - value === null  → render "数据暂不可用" (gray, no number)
//   - is_stale === true → render "过期" badge in top-right corner
//   - source          → always render at the bottom in monospace, so
//                       the operator never forgets this is mock data

import type { ReactNode } from "react";

export interface KpiData {
  id: string;
  name: string;
  value: number | null;
  value_label: string | null;
  unit: string;
  card_format: "currency_cny" | "percent_0_100" | "percent_0_1" | "ratio_decimal" | string;
  trend: null;
  source: string | null;
  as_of: string | null;
  freshness_seconds: number | null;
  is_stale: boolean;
}

export interface KpiCardProps {
  kpi: KpiData;
}

/** Format a KPI number according to its `card_format`. */
function formatValue(value: number, cardFormat: string): string {
  if (cardFormat === "currency_cny") {
    if (value >= 1e8) return `${(value / 1e8).toFixed(2)} 亿元`;
    if (value >= 1e4) return `${(value / 1e4).toFixed(2)} 万元`;
    return `${value.toLocaleString("zh-CN")} 元`;
  }
  if (cardFormat === "percent_0_100") {
    return `${value.toFixed(1)}%`;
  }
  if (cardFormat === "percent_0_1") {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (cardFormat === "ratio_decimal") {
    return value.toFixed(2);
  }
  return value.toLocaleString("zh-CN");
}

/** Render `as_of` as a short Beijing-time label. */
function formatAsOf(asOf: string | null): string | null {
  if (!asOf) return null;
  try {
    const d = new Date(asOf);
    if (Number.isNaN(d.getTime())) return asOf;
    return d.toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return asOf;
  }
}

export function KpiCard({ kpi }: KpiCardProps): ReactNode {
  const {
    name,
    value,
    value_label,
    card_format,
    is_stale,
    source,
    as_of,
  } = kpi;

  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
  const asOfLabel = formatAsOf(as_of);

  return (
    <article className="relative rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {is_stale ? (
        <span
          className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
          title={`数据已过期 (freshness_seconds > 86400)`}
        >
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
          过期
        </span>
      ) : null}

      <header className="mb-2 pr-12">
        <h3 className="text-xs font-medium text-slate-500">{name}</h3>
        {value_label ? (
          <p className="mt-0.5 text-[11px] text-slate-400">{value_label}</p>
        ) : null}
      </header>

      <div className="flex items-baseline gap-2">
        {hasValue ? (
          <p
            className="text-2xl font-bold tabular-nums text-slate-950"
            data-testid={`kpi-value-${kpi.id}`}
          >
            {formatValue(value as number, card_format)}
          </p>
        ) : (
          <p
            className="text-sm font-medium text-slate-400"
            data-testid={`kpi-unavailable-${kpi.id}`}
          >
            数据暂不可用
          </p>
        )}
      </div>

      <footer className="mt-3 space-y-1 border-t border-slate-100 pt-2 text-[10px] text-slate-400">
        {asOfLabel ? <p>更新于 {asOfLabel}</p> : null}
        {source ? (
          <p
            className="truncate font-mono"
            title={source}
            data-testid={`kpi-source-${kpi.id}`}
          >
            {source}
          </p>
        ) : null}
      </footer>
    </article>
  );
}