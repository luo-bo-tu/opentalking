// qiepai · 场景模板单卡 (Phase ❹)
//
// TemplateGrid 渲染的单张卡:
//   - name (h3) + category badge + source badge
//   - description (2 行 truncate)
//   - RatingStars (readonly sm) + use_count ("142 次使用" + users 图标)
//   - tags (chip list, max 3 + "+N")
//
// hover: cyan-200 border + shadow-md (跟 FeishuGroupCard 一致)
// click: 调 onClick prop 打开 TemplateDetailModal

import type { ReactNode } from "react";

import { RatingStars } from "./RatingStars";
import {
  TEMPLATE_CATEGORY_LABEL,
  TEMPLATE_CATEGORY_TONE,
  TEMPLATE_SOURCE_LABEL,
  TEMPLATE_SOURCE_TONE,
  type MarketplaceTemplate,
} from "./types";

export interface TemplateCardProps {
  template: MarketplaceTemplate;
  onClick: (id: string) => void;
}

const MAX_TAGS_VISIBLE = 3;

export function TemplateCard({
  template,
  onClick,
}: TemplateCardProps): ReactNode {
  const tagsVisible = template.tags.slice(0, MAX_TAGS_VISIBLE);
  const tagsOverflow = template.tags.length - tagsVisible.length;

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onClick(template.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick(template.id);
        }
      }}
      className="flex h-full cursor-pointer flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:shadow-md focus:border-cyan-400 focus:outline-none"
      data-testid={`template-card-${template.id}`}
    >
      {/* header: name + badges */}
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
            场景模板
          </p>
          <h3 className="mt-0.5 truncate text-sm font-semibold text-slate-950">
            {template.name}
          </h3>
          {template.industry !== null ? (
            <p className="mt-0.5 truncate text-[10px] text-slate-500">
              {template.industry}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span
            className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${TEMPLATE_CATEGORY_TONE[template.category]}`}
            data-testid={`template-card-category-${template.id}`}
          >
            {TEMPLATE_CATEGORY_LABEL[template.category]}
          </span>
          <span
            className={`rounded px-1.5 py-0.5 text-[9px] font-medium ${TEMPLATE_SOURCE_TONE[template.source]}`}
            title={`来源 · ${TEMPLATE_SOURCE_LABEL[template.source]}`}
          >
            {TEMPLATE_SOURCE_LABEL[template.source]}
          </span>
        </div>
      </header>

      {/* description */}
      <p
        className="mt-3 line-clamp-2 text-xs leading-relaxed text-slate-600"
        title={template.description}
      >
        {template.description}
      </p>

      {/* rating + use_count */}
      <div className="mt-3 flex items-center justify-between gap-2">
        <RatingStars
          value={template.rating_avg}
          readonly
          size="sm"
          showNumeric
          ratingCount={template.rating_count}
        />
        <span
          className="inline-flex shrink-0 items-center gap-1 rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-600"
          title={`已被使用 ${template.use_count} 次`}
          data-testid={`template-card-use-count-${template.id}`}
        >
          <svg
            className="h-3 w-3"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
            />
          </svg>
          {template.use_count} 次使用
        </span>
      </div>

      {/* tags */}
      {template.tags.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1">
          {tagsVisible.map((tag) => (
            <span
              key={tag}
              className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-600"
            >
              {tag}
            </span>
          ))}
          {tagsOverflow > 0 ? (
            <span
              className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-400"
              title={template.tags.slice(MAX_TAGS_VISIBLE).join(" / ")}
            >
              +{tagsOverflow}
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}