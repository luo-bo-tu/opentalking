// qiepai · 决策中心 mock 数据 (Phase ❷-5 前端先行)
//
// 后端 /qiepai/decisions 还在 stub, 前端先用这份 mock 渲染真实 UI 结构.
// 数据语义合理 (营收数字 / 客户集中度 / 应收都是 ❷-4 mock JSON 已有的),
// 后端就绪后所有 fetch 自动切真, 这份文件作废.
//
// 数据来源全部标 source=mock://..., UI 顶部显式标 "mock 模式".

import type { AIResponse, DecisionItem } from "./types";

export const MOCK_DECISIONS: DecisionItem[] = [
  {
    id: "dec-001",
    title: "Q4 营收预警应对",
    description:
      "近 30 天营收环比下降 3%, 需要评估是否调整销售策略或追加资源投入。",
    status: "pending",
    owner: "财务总监",
    metric_id: "metric-revenue-monthly",
    snapshot_id: "snap-2026-07",
    fact_snapshot: {
      revenue_current_month: 4823500,
      revenue_previous_month: 4972680,
      revenue_change_pct: -3.0,
      yoy_change_pct: 12.4,
      source: "mock://sales-trend/v1",
      as_of: "2026-07-30T00:00:00+08:00",
    },
    ai_suggestion: null,
    decision_text: null,
    decided_at: null,
    created_at: "2026-07-30T10:15:00+08:00",
  },
  {
    id: "dec-002",
    title: "客户集中度过高 - Top 3 占 78%",
    description:
      "前三大客户贡献 78% 营收, 单一客户流失将造成显著冲击, 需评估客户拓展节奏。",
    status: "pending",
    owner: "销售总监",
    metric_id: "metric-customer-concentration",
    snapshot_id: "snap-2026-07",
    fact_snapshot: {
      top3_concentration_pct: 78.0,
      top1_customer_revenue: 1680000,
      top2_customer_revenue: 1120000,
      top3_customer_revenue: 980000,
      total_revenue: 4823500,
      source: "mock://customer-concentration/v1",
      as_of: "2026-07-30T00:00:00+08:00",
    },
    ai_suggestion: null,
    decision_text: null,
    decided_at: null,
    created_at: "2026-07-29T14:42:00+08:00",
  },
  {
    id: "dec-003",
    title: "应收账款专项回收计划",
    description:
      "AR 余额超 5000 万, 4 家客户逾期超 90 天, 需要法务介入阈值判断。",
    status: "decided",
    owner: "财务总监",
    metric_id: "metric-ar-aging",
    snapshot_id: "snap-2026-07",
    fact_snapshot: {
      ar_total: 52340000,
      ar_overdue_90d_count: 4,
      ar_overdue_90d_amount: 8420000,
      ar_overdue_60d_amount: 6150000,
      source: "mock://orders-ar/v1",
      as_of: "2026-07-30T00:00:00+08:00",
    },
    ai_suggestion: null,
    decision_text:
      "启动专项催收小组, 90 天以上逾期客户由法务介入发函, 60 天客户由销售总监电话跟进。",
    decided_at: "2026-07-25T16:20:00+08:00",
    created_at: "2026-07-20T09:30:00+08:00",
  },
  {
    id: "dec-004",
    title: "Q3 销售目标冲刺方案",
    description: "Q3 已过 2/3, 目标达成率 87%, 剩 1 个月需评估冲刺投入产出。",
    status: "cancelled",
    owner: "销售总监",
    metric_id: "metric-target-attainment",
    snapshot_id: "snap-2026-q3",
    fact_snapshot: {
      attainment_pct: 87.0,
      q3_target: 18000000,
      q3_actual: 15660000,
      gap: 2340000,
      remaining_days: 30,
      source: "mock://target-attainment/v1",
      as_of: "2026-07-20T00:00:00+08:00",
    },
    ai_suggestion: null,
    decision_text:
      "Q3 冲刺投入产出比偏低, 资源转 Q4 重新评估, 取消本季冲刺方案。",
    decided_at: "2026-07-22T11:00:00+08:00",
    created_at: "2026-07-15T15:00:00+08:00",
  },
  {
    id: "dec-005",
    title: "7 月现金流缺口预警",
    description: "经营现金流连续 2 月为负, 需评估融资或应付账款延期方案。",
    status: "pending",
    owner: "CFO",
    metric_id: "metric-cashflow",
    snapshot_id: "snap-2026-07",
    fact_snapshot: {
      operating_cashflow_jul: -1850000,
      operating_cashflow_jun: -920000,
      cash_balance: 12400000,
      monthly_fixed_outflow: 6800000,
      source: "mock://financial-kpi/v1",
      as_of: "2026-07-30T00:00:00+08:00",
    },
    ai_suggestion: null,
    decision_text: null,
    decided_at: null,
    created_at: "2026-07-31T08:30:00+08:00",
  },
];

/** AI 4 层响应 mock (与 MOCK_DECISIONS 一一对应, dec-005 信息不全 → 含 unknown) */
export const MOCK_AI_RESPONSES: Record<string, AIResponse> = {
  "dec-001": {
    fact: [
      {
        label: "本月营收",
        value: 4823500,
        unit: "元",
        source: "mock://sales-trend/v1",
      },
      {
        label: "上月营收",
        value: 4972680,
        unit: "元",
        source: "mock://sales-trend/v1",
      },
      {
        label: "环比变化",
        value: -3.0,
        unit: "%",
        source: "computed",
      },
      {
        label: "同比变化",
        value: 12.4,
        unit: "%",
        source: "computed",
      },
    ],
    inference: [
      {
        text: "营收环比下降 3%, 但同比仍增长 12.4%, 属短期波动而非趋势性下滑。",
        confidence: 0.82,
      },
      {
        text: "初步判断客户 A 续约延迟贡献约 60% 降幅, 需 CRM 数据确认。",
        confidence: 0.74,
      },
    ],
    suggestion: [
      {
        text: "联系客户 A 确认续约时间表, 必要时提供 3% 续约优惠锁定 Q4。",
        owner: "销售总监",
      },
      {
        text: "调整 Q4 销售预测至 5200 万, 预留 5% 缓冲应对波动。",
        owner: "财务总监",
      },
    ],
    unknown: [
      {
        text: "客户 A 续约意向数据缺失, 需补充 CRM 跟进记录。",
        need: "CRM 跟进记录",
      },
    ],
  },
  "dec-002": {
    fact: [
      {
        label: "Top 3 集中度",
        value: 78.0,
        unit: "%",
        source: "mock://customer-concentration/v1",
      },
      {
        label: "Top 1 客户营收",
        value: 1680000,
        unit: "元",
        source: "mock://customer-concentration/v1",
      },
      {
        label: "Top 2 客户营收",
        value: 1120000,
        unit: "元",
        source: "mock://customer-concentration/v1",
      },
      {
        label: "Top 3 客户营收",
        value: 980000,
        unit: "元",
        source: "mock://customer-concentration/v1",
      },
    ],
    inference: [
      {
        text: "Top 3 集中度 78% 显著高于行业警戒线 60%, 单一客户流失冲击巨大。",
        confidence: 0.91,
      },
      {
        text: "中等客户 (Top 4-10) 仅占 15%, 中腰部客户拓展空间充足。",
        confidence: 0.78,
      },
    ],
    suggestion: [
      {
        text: "Q4 启动中腰部客户拓展计划, 目标新增 5 家 100 万级客户。",
        owner: "销售总监",
      },
      {
        text: "建立 Top 3 客户专属服务团队, 续约率纳入 KPI 强制考核。",
        owner: "销售总监",
      },
    ],
    unknown: [
      {
        text: "Top 3 客户行业分布未知, 缺乏行业相关性分析。",
        need: "客户行业标签",
      },
    ],
  },
  "dec-003": {
    fact: [
      {
        label: "AR 余额",
        value: 52340000,
        unit: "元",
        source: "mock://orders-ar/v1",
      },
      {
        label: "90 天+ 逾期客户数",
        value: 4,
        unit: "家",
        source: "mock://orders-ar/v1",
      },
      {
        label: "90 天+ 逾期金额",
        value: 8420000,
        unit: "元",
        source: "mock://orders-ar/v1",
      },
    ],
    inference: [
      {
        text: "90 天+ 逾期金额占 AR 16%, 已超过行业可接受阈值 10%。",
        confidence: 0.88,
      },
      {
        text: "若 90 天+ 客户全部坏账, 将直接侵蚀当季利润 32%。",
        confidence: 0.83,
      },
    ],
    suggestion: [
      {
        text: "已决策: 启动专项催收小组, 90 天+ 由法务介入发函。",
        owner: "财务总监",
      },
    ],
    unknown: [],
  },
  "dec-004": {
    fact: [
      {
        label: "Q3 达成率",
        value: 87.0,
        unit: "%",
        source: "mock://target-attainment/v1",
      },
      {
        label: "Q3 目标",
        value: 18000000,
        unit: "元",
        source: "mock://target-attainment/v1",
      },
      {
        label: "Q3 已完成",
        value: 15660000,
        unit: "元",
        source: "mock://target-attainment/v1",
      },
      {
        label: "差距",
        value: 2340000,
        unit: "元",
        source: "computed",
      },
    ],
    inference: [
      {
        text: "冲刺 234 万缺口需投入额外折扣约 80 万, ROI 不及 Q4 投入。",
        confidence: 0.71,
      },
    ],
    suggestion: [
      {
        text: "已决策: 取消 Q3 冲刺, 资源转入 Q4。",
        owner: "销售总监",
      },
    ],
    unknown: [],
  },
  "dec-005": {
    fact: [
      {
        label: "7 月经营现金流",
        value: -1850000,
        unit: "元",
        source: "mock://financial-kpi/v1",
      },
      {
        label: "6 月经营现金流",
        value: -920000,
        unit: "元",
        source: "mock://financial-kpi/v1",
      },
      {
        label: "现金余额",
        value: 12400000,
        unit: "元",
        source: "mock://financial-kpi/v1",
      },
      {
        label: "月固定支出",
        value: 6800000,
        unit: "元",
        source: "mock://financial-kpi/v1",
      },
    ],
    inference: [
      {
        text: "按当前现金消耗速度, 现金余额可支撑约 1.7 个月运营。",
        confidence: 0.86,
      },
      {
        text: "现金流为负主因是 AR 回收延迟, 与应收账款问题同源。",
        confidence: 0.79,
      },
    ],
    suggestion: [
      {
        text: "优先解决 AR 回收 (见决策项 dec-003), 若 30 天内未改善启动融资。",
        owner: "CFO",
      },
      {
        text: "与 Top 3 供应商协商应付账款延期 30 天, 缓解短期现金压力。",
        owner: "CFO",
      },
    ],
    unknown: [
      {
        text: "Q3 是否有大额订单回款未确定, 现金流预测存在 ±40% 误差。",
        need: "Q3 订单管线",
      },
      {
        text: "银行授信额度未在系统中, 紧急融资能力评估缺失。",
        need: "银行授信额度",
      },
    ],
  },
};
