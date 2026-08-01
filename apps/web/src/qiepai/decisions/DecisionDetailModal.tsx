// qiepai · 决策项详情 Modal (Phase ❷-5)
//
// 点击 DecisionItemCard 后弹出: 完整 fact_snapshot + 决策文本输入 + 状态切换 + 提交
// 提交时尝试 PATCH /qiepai/decisions/{id}, 失败则本地乐观更新 (mock 模式).

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { buildApiUrl } from "../../lib/api";
import type {
  DecisionItem,
  DecisionPatchPayload,
  DecisionStatus,
} from "./types";

export interface DecisionDetailModalProps {
  item: DecisionItem;
  onClose: () => void;
  onSubmit: (id: string, patch: DecisionPatchPayload) => Promise<void>;
}

const STATUS_OPTIONS: Array<{ value: DecisionStatus; label: string }> = [
  { value: "pending", label: "待决 (待处理)" },
  { value: "decided", label: "已定 (已决策)" },
  { value: "cancelled", label: "取消 (不再跟进)" },
];

function formatAsOf(asOf: unknown): string | null {
  if (typeof asOf !== "string") return null;
  try {
    const d = new Date(asOf);
    if (Number.isNaN(d.getTime())) return asOf;
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return asOf;
  }
}

export function DecisionDetailModal({
  item,
  onClose,
  onSubmit,
}: DecisionDetailModalProps): ReactNode {
  const [status, setStatus] = useState<DecisionStatus>(item.status);
  const [decisionText, setDecisionText] = useState(item.decision_text ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const factEntries = Object.entries(item.fact_snapshot).filter(
    ([k]) => k !== "source" && k !== "as_of",
  );
  const source =
    typeof item.fact_snapshot.source === "string"
      ? item.fact_snapshot.source
      : null;
  const asOf = formatAsOf(item.fact_snapshot.as_of);

  const handleSubmit = async () => {
    if (decisionText.trim().length === 0 && status !== "pending") {
      setSubmitError("决策文本不能为空 (非 pending 状态)");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      // 先尝试 PATCH, 失败不阻塞 (后端 stub 友好)
      try {
        await fetch(
          buildApiUrl(`/qiepai/decisions/${encodeURIComponent(item.id)}`),
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status, decision_text: decisionText }),
          },
        );
      } catch {
        // 静默忽略网络错误, 本地乐观更新
      }
      await onSubmit(item.id, { status, decision_text: decisionText });
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
      onClick={onClose}
      data-testid="decision-modal-backdrop"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="decision-modal"
      >
        {/* header */}
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div className="min-w-0">
            <p className="text-[10px] font-medium text-slate-500">
              决策详情 · {item.id}
            </p>
            <h2 className="mt-0.5 text-base font-semibold text-slate-950">
              {item.title}
            </h2>
            <p className="mt-1 text-xs text-slate-600">{item.description}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            title="关闭 (Esc)"
            aria-label="关闭"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </header>

        {/* body */}
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {/* meta */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-[10px] text-slate-400">责任人</p>
              <p className="mt-0.5 font-medium text-slate-700">{item.owner}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400">创建时间</p>
              <p className="mt-0.5 font-mono text-slate-700">
                {item.created_at}
              </p>
            </div>
            {source ? (
              <div className="col-span-2">
                <p className="text-[10px] text-slate-400">事实快照来源</p>
                <p
                  className="mt-0.5 truncate font-mono text-[11px] text-slate-700"
                  title={source}
                >
                  {source}
                </p>
                {asOf ? (
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    asOf {asOf}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          {/* fact_snapshot 完整表格 */}
          <section>
            <h3 className="mb-2 text-xs font-semibold text-slate-700">
              事实快照 (完整)
            </h3>
            <div className="overflow-hidden rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-slate-100">
                  {factEntries.map(([k, v]) => (
                    <tr key={k} className="hover:bg-slate-50">
                      <td className="w-1/3 px-3 py-1.5 text-slate-500">
                        {k}
                      </td>
                      <td className="px-3 py-1.5 font-mono tabular-nums text-slate-950">
                        {typeof v === "number"
                          ? v.toLocaleString("zh-CN")
                          : typeof v === "string"
                            ? v
                            : JSON.stringify(v)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* 决策输入 */}
          <section>
            <h3 className="mb-2 text-xs font-semibold text-slate-700">
              录入决策
            </h3>
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="decision-status"
                  className="mb-1 block text-[10px] text-slate-500"
                >
                  状态
                </label>
                <select
                  id="decision-status"
                  value={status}
                  onChange={(e) =>
                    setStatus(e.target.value as DecisionStatus)
                  }
                  className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-cyan-400 focus:outline-none"
                  data-testid="decision-status-select"
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label
                  htmlFor="decision-text"
                  className="mb-1 block text-[10px] text-slate-500"
                >
                  决策文本 (decision_text)
                </label>
                <textarea
                  id="decision-text"
                  value={decisionText}
                  onChange={(e) => setDecisionText(e.target.value)}
                  rows={4}
                  className="w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs leading-relaxed text-slate-700 focus:border-cyan-400 focus:outline-none"
                  placeholder="例如: 启动专项催收小组, 90 天+ 客户由法务介入..."
                  data-testid="decision-text-input"
                />
              </div>
              {submitError !== null ? (
                <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700">
                  {submitError}
                </p>
              ) : null}
            </div>
          </section>
        </div>

        {/* footer */}
        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 p-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting}
            className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="decision-submit"
          >
            {submitting ? "提交中..." : "提交决策"}
          </button>
        </footer>
      </div>
    </div>
  );
}
