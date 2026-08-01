// qiepai · AI 助手单层渲染 (Phase ❷-5)
//
// 4 层统一组件: fact / inference / suggestion / unknown.
// 每层有 icon + 标题 + 内容, 空数组不渲染 (架构 § 21.2).
//
// 颜色契约 (跟 CockpitTab 一致):
//   fact        → blue  (实际数据)
//   inference   → purple (推断)
//   suggestion  → green  (行动建议)
//   unknown     → amber  (信息不足)

import type { ReactNode } from "react";

export type AssistantLayerKind = "fact" | "inference" | "suggestion" | "unknown";

export interface AssistantLayerProps {
  kind: AssistantLayerKind;
  /** 该层条目数 (空数组时不渲染) */
  count: number;
  children: ReactNode;
  /** suggestion 层特有: 显示刷新按钮 */
  onRefresh?: () => void;
  refreshing?: boolean;
}

const KIND_META: Record<
  AssistantLayerKind,
  { icon: string; label: string; tone: string; ring: string }
> = {
  fact: {
    icon: "📊",
    label: "事实 (fact)",
    tone: "border-blue-200 bg-blue-50/60",
    ring: "text-blue-700",
  },
  inference: {
    icon: "🔍",
    label: "推断 (inference)",
    tone: "border-purple-200 bg-purple-50/60",
    ring: "text-purple-700",
  },
  suggestion: {
    icon: "💡",
    label: "建议 (suggestion)",
    tone: "border-emerald-200 bg-emerald-50/60",
    ring: "text-emerald-700",
  },
  unknown: {
    icon: "⚠️",
    label: "未知 (unknown)",
    tone: "border-amber-200 bg-amber-50/60",
    ring: "text-amber-700",
  },
};

export function AssistantLayer({
  kind,
  count,
  children,
  onRefresh,
  refreshing,
}: AssistantLayerProps): ReactNode {
  const meta = KIND_META[kind];

  // 空数组不渲染 section (架构 § 21.2)
  if (count === 0) {
    return null;
  }

  return (
    <section
      className={`rounded-lg border ${meta.tone} p-3`}
      data-testid={`assistant-layer-${kind}`}
    >
      <header className="mb-2 flex items-center justify-between">
        <h3 className={`text-xs font-semibold ${meta.ring}`}>
          <span className="mr-1">{meta.icon}</span>
          {meta.label}
          <span className="ml-1.5 text-[10px] font-normal text-slate-500">
            ({count})
          </span>
        </h3>
        {onRefresh ? (
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="rounded border border-emerald-200 bg-white px-2 py-0.5 text-[10px] font-medium text-emerald-700 transition hover:border-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
            title="重新生成建议 (不缓存)"
          >
            {refreshing ? "刷新中..." : "刷新"}
          </button>
        ) : null}
      </header>
      <div className="space-y-2">{children}</div>
    </section>
  );
}
