// qiepai · 场景模板浏览 grid (Phase ❹)
//
// 顶部 toolbar: category filter chips (全部 + 5 category) + sort dropdown (latest/popular/rating) + 数量
// 网格: 1/2/3 列响应, 用 TemplateCard 渲染
// 空态: "暂无场景模板, 点击右上「+ 上传模板」贡献你的场景"

import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { TemplateCard } from "./TemplateCard";
import {
  TEMPLATE_CATEGORY_LABEL,
  TEMPLATE_SORT_LABEL,
  type MarketplaceTemplate,
  type TemplateCategory,
  type TemplateSort,
} from "./types";

export interface TemplateGridProps {
  templates: MarketplaceTemplate[] | null;
  onSelect: (id: string) => void;
}

type CategoryFilter = "all" | TemplateCategory;

const CATEGORY_FILTERS: Array<{ key: CategoryFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "customer_service", label: TEMPLATE_CATEGORY_LABEL.customer_service },
  { key: "sales", label: TEMPLATE_CATEGORY_LABEL.sales },
  { key: "finance", label: TEMPLATE_CATEGORY_LABEL.finance },
  { key: "hr", label: TEMPLATE_CATEGORY_LABEL.hr },
  { key: "ops", label: TEMPLATE_CATEGORY_LABEL.ops },
];

const SORT_OPTIONS: Array<{ key: TemplateSort; label: string }> = [
  { key: "latest", label: TEMPLATE_SORT_LABEL.latest },
  { key: "popular", label: TEMPLATE_SORT_LABEL.popular },
  { key: "rating", label: TEMPLATE_SORT_LABEL.rating },
];

function compareTemplates(
  a: MarketplaceTemplate,
  b: MarketplaceTemplate,
  sort: TemplateSort,
): number {
  switch (sort) {
    case "latest":
      // created_at desc
      return b.created_at.localeCompare(a.created_at);
    case "popular":
      // use_count desc, 同 use_count 时按 rating_avg desc
      if (b.use_count !== a.use_count) return b.use_count - a.use_count;
      return b.rating_avg - a.rating_avg;
    case "rating":
      // rating_avg desc, 同 avg 时按 rating_count desc
      if (b.rating_avg !== a.rating_avg) return b.rating_avg - a.rating_avg;
      return b.rating_count - a.rating_count;
  }
}

export function TemplateGrid({
  templates,
  onSelect,
}: TemplateGridProps): ReactNode {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [sort, setSort] = useState<TemplateSort>("latest");

  const visible = useMemo(() => {
    if (templates === null) return [];
    const filtered =
      categoryFilter === "all"
        ? templates
        : templates.filter((t) => t.category === categoryFilter);
    return [...filtered].sort((a, b) => compareTemplates(a, b, sort));
  }, [templates, categoryFilter, sort]);

  if (templates === null) {
    return (
      <div
        className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-700"
        data-testid="template-grid-loading"
      >
        模板数据加载中...
      </div>
    );
  }

  return (
    <section
      className="flex flex-col gap-3"
      data-testid="template-grid"
    >
      {/* toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm">
        <nav
          className="flex flex-wrap items-center gap-1"
          aria-label="模板分类过滤"
        >
          {CATEGORY_FILTERS.map((f) => {
            const active = categoryFilter === f.key;
            const count =
              f.key === "all"
                ? templates.length
                : templates.filter((t) => t.category === f.key).length;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setCategoryFilter(f.key)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  active
                    ? "bg-cyan-50 text-cyan-700"
                    : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                }`}
                data-testid={`template-grid-filter-${f.key}`}
              >
                {f.label}
                <span className="ml-1 text-[10px] tabular-nums text-slate-400">
                  {count}
                </span>
              </button>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500">
            排序 ·
          </span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as TemplateSort)}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus:border-cyan-400 focus:outline-none"
            data-testid="template-grid-sort"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.key} value={opt.key}>
                {opt.label}
              </option>
            ))}
          </select>
          <span className="text-[10px] text-slate-400 tabular-nums">
            共 {visible.length} 个
          </span>
        </div>
      </div>

      {/* grid or empty */}
      {visible.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-white p-8 text-center text-xs text-slate-400"
          data-testid="template-grid-empty"
        >
          <p className="text-sm font-medium text-slate-500">
            暂无场景模板
          </p>
          <p>点击右上「+ 上传模板」贡献你的场景, 让团队复用你的最佳实践。</p>
        </div>
      ) : (
        <div
          className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
          data-testid="template-grid-list"
        >
          {visible.map((t) => (
            <TemplateCard key={t.id} template={t} onClick={onSelect} />
          ))}
        </div>
      )}
    </section>
  );
}