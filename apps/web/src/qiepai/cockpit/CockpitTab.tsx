// qiepai · 老板驾驶舱顶层组件 (Phase ❷-4)
//
// 顶层布局:
//   - 顶部 1 行: 标题 + 刷新状态 + 立即刷新按钮 (❷-4 decision #7: 手动刷新, 不轮询)
//   - 5 张 KPI 卡 (grid 1/2/5)
//   - 4 个图表 (grid 1/2)
//
// 数据来源: 5 个 endpoint 并发拉,任一失败不阻塞其他。Mock 数据是静态的,
// 轮询没意义;用户点 "立即刷新" 才重新拉。

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiGet } from "../../lib/api";
import { KpiCard, type KpiData } from "./KpiCard";
import { SalesTrendChart, type SalesTrendChartData } from "./SalesTrendChart";
import {
  CustomerConcentrationChart,
  type CustomerConcentrationChartData,
} from "./CustomerConcentrationChart";
import { OrdersArChart, type OrdersArChartData } from "./OrdersArChart";
import {
  TargetAttainmentChart,
  type TargetAttainmentChartData,
} from "./TargetAttainmentChart";

interface KpiResponse {
  kpis: KpiData[];
}

// Per ❷-4 decision #7: no auto-refresh. Mock data does not change, so
// polling adds noise without value. `null` means "do not setInterval".
// Set to a positive number (e.g. 5000) to re-enable polling later.
const AUTO_REFRESH_MS: number | null = null;

export default function CockpitTab(): ReactNode {
  const [kpis, setKpis] = useState<KpiData[] | null>(null);
  const [salesTrend, setSalesTrend] = useState<SalesTrendChartData | null>(
    null,
  );
  const [customer, setCustomer] = useState<
    CustomerConcentrationChartData | null
  >(null);
  const [ordersAr, setOrdersAr] = useState<OrdersArChartData | null>(null);
  const [targetAttainment, setTargetAttainment] = useState<
    TargetAttainmentChartData | null
  >(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      apiGet<KpiResponse>("/qiepai/cockpit/kpis"),
      apiGet<SalesTrendChartData>("/qiepai/cockpit/charts/sales-trend"),
      apiGet<CustomerConcentrationChartData>(
        "/qiepai/cockpit/charts/customer-concentration",
      ),
      apiGet<OrdersArChartData>("/qiepai/cockpit/charts/orders-ar"),
      apiGet<TargetAttainmentChartData>(
        "/qiepai/cockpit/charts/target-attainment",
      ),
    ]);

    let errs = 0;
    if (results[0].status === "fulfilled") {
      setKpis(results[0].value.kpis);
    } else {
      setKpis(null);
      errs += 1;
    }
    if (results[1].status === "fulfilled") {
      setSalesTrend(results[1].value);
    } else {
      setSalesTrend(null);
      errs += 1;
    }
    if (results[2].status === "fulfilled") {
      setCustomer(results[2].value);
    } else {
      setCustomer(null);
      errs += 1;
    }
    if (results[3].status === "fulfilled") {
      setOrdersAr(results[3].value);
    } else {
      setOrdersAr(null);
      errs += 1;
    }
    if (results[4].status === "fulfilled") {
      setTargetAttainment(results[4].value);
    } else {
      setTargetAttainment(null);
      errs += 1;
    }

    setErrorCount(errs);
    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    if (AUTO_REFRESH_MS !== null) {
      const id = window.setInterval(() => void refresh(), AUTO_REFRESH_MS);
      return () => window.clearInterval(id);
    }
    return undefined;
  }, [refresh]);

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4">
      {/* header */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">qiepai · Cockpit</p>
          <h1 className="text-base font-semibold text-slate-950">老板驾驶舱</h1>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                errorCount === 0 ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
            {errorCount === 0 ? "全部数据源 OK" : `${errorCount} 个数据源异常`}
          </span>
          <span>
            手动刷新 · 上次{" "}
            {lastRefresh.toLocaleTimeString("zh-CN", { hour12: false })}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700"
          >
            立即刷新
          </button>
        </div>
      </section>

      {/* 5 KPI cards */}
      <section
        className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5"
        data-testid="cockpit-kpi-grid"
      >
        {kpis === null ? (
          <div className="col-span-full rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-700">
            KPI 数据暂不可用
          </div>
        ) : (
          kpis.map((kpi) => <KpiCard key={kpi.id} kpi={kpi} />)
        )}
      </section>

      {/* 4 charts: 2x2 grid on lg+ screens */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3">
            <h2 className="text-sm font-semibold text-slate-950">
              销售趋势 (近 12 月)
            </h2>
          </header>
          <SalesTrendChart data={salesTrend} />
        </article>
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3">
            <h2 className="text-sm font-semibold text-slate-950">
              客户集中度 (Top 5)
            </h2>
          </header>
          <CustomerConcentrationChart data={customer} />
        </article>
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3">
            <h2 className="text-sm font-semibold text-slate-950">
              订单 / 应收结构 (近 12 月)
            </h2>
          </header>
          <OrdersArChart data={ordersAr} />
        </article>
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3">
            <h2 className="text-sm font-semibold text-slate-950">
              目标达成 (季度)
            </h2>
          </header>
          <TargetAttainmentChart data={targetAttainment} />
        </article>
      </section>
    </main>
  );
}