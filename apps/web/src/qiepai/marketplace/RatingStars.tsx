// qiepai · 5 星评分组件 (Phase ❹)
//
// 双模式:
//   - readonly: 显示实心/半实心/空心 star + 数字 (e.g. "4.5"), TemplateCard + TemplateDetailModal 用
//   - interactive: hover 预览 + click 提交 onChange(value), TemplateDetailModal 评分面板用
//
// SVG star path (跟 ❷-5 DecisionItemCard 风格一致的 amber 色),
// size sm/md 双档 (UI 密度).

import { useState } from "react";
import type { ReactNode } from "react";

export interface RatingStarsProps {
  /** 当前评分 0-5, 支持 0.5 半星 */
  value: number;
  /** 只读模式 (TemplateCard 默认) */
  readonly?: boolean;
  /** interactive 模式提交回调 */
  onChange?: (value: number) => void;
  /** sm (卡片小) / md (详情中) */
  size?: "sm" | "md";
  /** 是否显示右侧数字 (e.g. "4.5 (38)"), TemplateCard 必显, DetailModal 默认隐藏 (避免重复) */
  showNumeric?: boolean;
  /** showNumeric 时的评分总数 (用于括号, e.g. "4.5 (38)") */
  ratingCount?: number;
}

const SIZE_PX: Record<"sm" | "md", number> = {
  sm: 14,
  md: 20,
};

const STAR_PATH =
  "M12 2.5l3.09 6.26 6.91 1-5 4.87 1.18 6.87L12 17.77l-6.18 3.25L7 14.63 2 9.76l6.91-1L12 2.5z";

/** 计算单颗星 fill ratio: 0 = 空, 0.5 = 半, 1 = 实 */
function fillRatio(value: number, starIndex: number): number {
  const diff = value - starIndex;
  if (diff >= 1) return 1;
  if (diff >= 0.5) return 0.5;
  if (diff > 0) return 0.5;
  return 0;
}

interface StarButtonProps {
  index: number;
  size: number;
  fill: number;
  hoverFill: number;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onClick: () => void;
}

/** 单颗星 (SVG with linearGradient for half-fill) */
function Star({
  index,
  size,
  fill,
  hoverFill,
  onMouseEnter,
  onMouseLeave,
  onClick,
}: StarButtonProps): ReactNode {
  const effectiveFill = hoverFill > 0 ? hoverFill : fill;
  const gradientId = `rating-star-grad-${index}-${effectiveFill.toFixed(2)}`;
  const isInteractive = onClick !== undefined;
  return (
    <button
      type="button"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={onClick}
      disabled={!isInteractive}
      className={`inline-flex shrink-0 items-center justify-center ${
        isInteractive
          ? "cursor-pointer transition hover:scale-110"
          : "cursor-default"
      }`}
      style={{ width: size, height: size, padding: 0, background: "transparent", border: "none" }}
      aria-label={`评分 ${effectiveFill} 颗星 (第 ${index + 1} 颗)`}
      data-testid={`rating-star-${index}`}
    >
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset={`${effectiveFill * 100}%`} stopColor="#f59e0b" />
            <stop offset={`${effectiveFill * 100}%`} stopColor="#e2e8f0" />
          </linearGradient>
        </defs>
        <path
          d={STAR_PATH}
          fill={`url(#${gradientId})`}
          stroke="#f59e0b"
          strokeWidth={0.5}
        />
      </svg>
    </button>
  );
}

export function RatingStars({
  value,
  readonly = false,
  onChange,
  size = "sm",
  showNumeric = false,
  ratingCount,
}: RatingStarsProps): ReactNode {
  const px = SIZE_PX[size];
  const [hover, setHover] = useState<number | null>(null);
  const isInteractive = !readonly && onChange !== undefined;

  // 数值范围 clamp 到 0-5
  const safeValue = Math.min(5, Math.max(0, value));

  const handleClick = (starIndex: number) => {
    if (!isInteractive) return;
    // 1-5 整数 (无半星交互)
    onChange?.(starIndex + 1);
  };

  return (
    <span
      className="inline-flex items-center gap-0.5"
      data-testid="rating-stars"
      data-value={safeValue.toFixed(1)}
      data-readonly={readonly ? "true" : "false"}
    >
      {[0, 1, 2, 3, 4].map((idx) => {
        const fill = fillRatio(safeValue, idx);
        const hoverFill =
          isInteractive && hover !== null ? fillRatio(hover, idx) : 0;
        return (
          <Star
            key={idx}
            index={idx}
            size={px}
            fill={fill}
            hoverFill={hoverFill}
            onMouseEnter={() => {
              if (isInteractive) setHover(idx + 1);
            }}
            onMouseLeave={() => {
              if (isInteractive) setHover(null);
            }}
            onClick={() => handleClick(idx)}
          />
        );
      })}
      {showNumeric ? (
        <span
          className={`ml-1 tabular-nums font-medium text-slate-700 ${
            size === "md" ? "text-xs" : "text-[10px]"
          }`}
          data-testid="rating-stars-numeric"
        >
          {safeValue.toFixed(1)}
          {ratingCount !== undefined && ratingCount > 0 ? (
            <span className="ml-0.5 text-slate-400">({ratingCount})</span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}