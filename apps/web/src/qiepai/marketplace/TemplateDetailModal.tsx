// qiepai · 场景模板详情 Modal (Phase ❹)
//
// 布局:
//   - header (name + category + source + close)
//   - body (description + payload JSON viewer + tags + metadata grid)
//   - ratings list (scroll max-height 240px)
//   - rate panel (RatingStars interactive + textarea + submit)
//   - footer (Cancel + Copy this template)
//
// 数据来源: 父组件传 template + ratings (已经 fetch 完毕)
// 行为:
//   - onCopy: 父组件触发实际 POST, copying 状态显示 loading
//   - onRate: 父组件触发实际 POST, 乐观更新本地 ratings
//   - Esc 关闭

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { RatingStars } from "./RatingStars";
import {
  TEMPLATE_CATEGORY_LABEL,
  TEMPLATE_CATEGORY_TONE,
  TEMPLATE_SOURCE_LABEL,
  TEMPLATE_SOURCE_TONE,
  type MarketplaceTemplate,
  type TemplateRating,
} from "./types";

export interface TemplateDetailModalProps {
  /** 完整 template (含 payload) — null 表示 loading 或 fetch 失败 */
  template: MarketplaceTemplate | null;
  /** 详情 fetch 状态: null + loading=true → 显示 loading;null + error → 显示 not-found */
  loading?: boolean;
  error?: boolean;
  ratings: TemplateRating[];
  /** 复制中状态 (避免重复点击) */
  copying: boolean;
  /** 当前 user_id (用于标记 "我的评分") */
  currentUserId: string;
  onClose: () => void;
  onCopy: (template: MarketplaceTemplate) => Promise<boolean>;
  onRate: (
    templateId: string,
    rating: number,
    comment: string,
  ) => Promise<boolean>;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** payload JSON viewer (极简 syntax highlight: key 蓝色 + string 绿色) */
function PayloadJsonViewer({ payload }: { payload: Record<string, unknown> }): ReactNode {
  const text = formatJson(payload);
  return (
    <pre
      className="max-h-72 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3 font-mono text-[10px] leading-relaxed text-slate-700"
      data-testid="template-detail-payload"
    >
      {text}
    </pre>
  );
}

export function TemplateDetailModal({
  template,
  loading,
  error,
  ratings,
  copying,
  currentUserId,
  onClose,
  onCopy,
  onRate,
}: TemplateDetailModalProps): ReactNode {
  const [myRating, setMyRating] = useState<number>(0);
  const [myComment, setMyComment] = useState<string>("");
  const [submittingRate, setSubmittingRate] = useState(false);
  const [rateError, setRateError] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);

  // Esc 关闭 (copying 中不响应)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !copying && !submittingRate) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, copying, submittingRate]);

  // 初始化: 仅在 template.id 或 currentUserId 变化时重新预填,
  // 避免 ratings 后续更新 (e.g. 自己提交后) 重置 user 正在编辑的 comment
  useEffect(() => {
    if (template === null) {
      setMyRating(0);
      setMyComment("");
      setRateError(null);
      setCopyError(null);
      return;
    }
    const existing = ratings.find((r) => r.user_id === currentUserId);
    if (existing !== undefined) {
      setMyRating(existing.rating);
      setMyComment(existing.comment ?? "");
    } else {
      setMyRating(0);
      setMyComment("");
    }
    setRateError(null);
    setCopyError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template?.id, currentUserId]);

  const handleRateSubmit = async () => {
    if (template === null) return;
    if (myRating < 1 || myRating > 5) {
      setRateError("请先选择评分 (1-5 星)");
      return;
    }
    setSubmittingRate(true);
    setRateError(null);
    try {
      const ok = await onRate(template.id, myRating, myComment.trim());
      if (!ok) {
        setRateError("评分失败, 请稍后重试");
      }
    } catch (err) {
      setRateError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmittingRate(false);
    }
  };

  const handleCopy = async () => {
    if (template === null) return;
    setCopyError(null);
    try {
      const ok = await onCopy(template);
      if (!ok) {
        setCopyError("复制失败, 请稍后重试");
      }
    } catch (err) {
      setCopyError(err instanceof Error ? err.message : String(err));
    }
  };

  // template 尚未拿到 (loading 或 error) → 渲染状态面板
  if (template === null) {
    const statusTitle = error
      ? "模板详情加载失败"
      : loading
      ? "加载中..."
      : "模板信息不可用";
    const statusBody = error
      ? "后端 GET /templates/{id} 返回错误, 可能是该模板已被删除或服务暂时不可用。"
      : loading
      ? "正在从后端拉取模板完整 payload..."
      : "请稍后重试或关闭。";
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
        onClick={() => {
          if (!copying && !submittingRate) onClose();
        }}
        data-testid="template-detail-modal-backdrop"
        role="dialog"
        aria-modal="true"
      >
        <div
          className="flex w-full max-w-md flex-col gap-4 rounded-xl border border-slate-200 bg-white p-6 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
          data-testid="template-detail-modal-loading"
        >
          <h2 className="text-base font-semibold text-slate-950">{statusTitle}</h2>
          <p className="text-xs leading-relaxed text-slate-600">{statusBody}</p>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={copying || submittingRate}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:opacity-50"
            >
              关闭
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
      onClick={() => {
        if (!copying && !submittingRate) onClose();
      }}
      data-testid="template-detail-modal-backdrop"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="template-detail-modal"
      >
        {/* header */}
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${TEMPLATE_CATEGORY_TONE[template.category]}`}
              >
                {TEMPLATE_CATEGORY_LABEL[template.category]}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 text-[9px] font-medium ${TEMPLATE_SOURCE_TONE[template.source]}`}
              >
                {TEMPLATE_SOURCE_LABEL[template.source]}
              </span>
              {template.industry !== null ? (
                <span className="text-[10px] text-slate-500">
                  · {template.industry}
                </span>
              ) : null}
            </div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">
              {template.name}
            </h2>
            <div className="mt-1 flex items-center gap-3 text-xs">
              <RatingStars
                value={template.rating_avg}
                readonly
                size="sm"
                showNumeric
                ratingCount={template.rating_count}
              />
              <span className="text-[10px] text-slate-500">
                {template.use_count} 次使用
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={copying || submittingRate}
            className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="关闭"
            title="关闭 (Esc)"
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
          {/* description */}
          <section>
            <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              简介
            </h3>
            <p className="text-xs leading-relaxed text-slate-700">
              {template.description}
            </p>
          </section>

          {/* tags */}
          {template.tags.length > 0 ? (
            <section>
              <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">
                标签
              </h3>
              <div className="flex flex-wrap gap-1">
                {template.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          {/* payload JSON viewer */}
          <section>
            <h3 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              模板配置 (payload)
            </h3>
            <PayloadJsonViewer payload={template.payload} />
            <p className="mt-1 text-[10px] text-slate-400">
              来源: {template.data_source ?? "未声明 (backend ❹ 暂未返回)"} · asOf{" "}
              {template.as_of !== undefined ? formatTime(template.as_of) : "—"}
            </p>
          </section>

          {/* metadata grid */}
          <section className="grid grid-cols-2 gap-2 rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-[10px] sm:grid-cols-4">
            <div>
              <p className="text-slate-400">使用次数</p>
              <p className="mt-0.5 font-mono text-slate-700 tabular-nums">
                {template.use_count}
              </p>
            </div>
            <div>
              <p className="text-slate-400">评分人数</p>
              <p className="mt-0.5 font-mono text-slate-700 tabular-nums">
                {template.rating_count}
              </p>
            </div>
            <div>
              <p className="text-slate-400">创建</p>
              <p className="mt-0.5 font-mono text-slate-700">
                {formatTime(template.created_at)}
              </p>
            </div>
            <div>
              <p className="text-slate-400">最近更新</p>
              <p className="mt-0.5 font-mono text-slate-700">
                {formatTime(template.updated_at)}
              </p>
            </div>
          </section>

          {/* ratings list */}
          <section>
            <h3 className="mb-2 flex items-center justify-between text-[10px] font-medium uppercase tracking-wide text-slate-400">
              <span>用户评分 ({ratings.length})</span>
              {ratings.length > 3 ? (
                <span className="text-[10px] normal-case text-slate-400">
                  滚动查看更多
                </span>
              ) : null}
            </h3>
            {ratings.length === 0 ? (
              <div className="rounded border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-400">
                暂无评分, 成为第一个评分者。
              </div>
            ) : (
              <ul
                className="max-h-60 space-y-2 overflow-y-auto pr-1"
                data-testid="template-detail-ratings"
              >
                {ratings.map((r) => (
                  <li
                    key={r.id}
                    className={`rounded-md border p-2 ${
                      r.user_id === currentUserId
                        ? "border-cyan-200 bg-cyan-50/40"
                        : "border-slate-200 bg-white"
                    }`}
                    data-testid={`template-detail-rating-${r.id}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <RatingStars value={r.rating} readonly size="sm" />
                        <span className="font-mono text-[10px] text-slate-500">
                          {r.user_id}
                          {r.user_id === currentUserId ? " (我)" : ""}
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-400">
                        {formatTime(r.created_at)}
                      </span>
                    </div>
                    {r.comment !== null && r.comment.length > 0 ? (
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-600">
                        {r.comment}
                      </p>
                    ) : (
                      <p className="mt-1 text-[10px] italic text-slate-400">
                        (无评论)
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* rate panel */}
          <section className="rounded-md border border-slate-200 bg-slate-50 p-3">
            <h3 className="mb-2 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              {ratings.some((r) => r.user_id === currentUserId)
                ? "更新我的评分"
                : "为这个模板评分"}
            </h3>
            <div className="flex items-center gap-2">
              <RatingStars
                value={myRating}
                size="md"
                onChange={setMyRating}
              />
              {myRating > 0 ? (
                <span className="text-[10px] text-slate-500">
                  已选 {myRating} 星
                </span>
              ) : (
                <span className="text-[10px] text-slate-400">点击评分</span>
              )}
            </div>
            <textarea
              value={myComment}
              onChange={(e) => setMyComment(e.target.value)}
              rows={2}
              disabled={submittingRate}
              placeholder="可选 · 留下你的使用体验 (例如: 客服效率提升明显)"
              className="mt-2 w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs leading-relaxed text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
              data-testid="template-detail-rate-comment"
            />
            {rateError !== null ? (
              <p
                className="mt-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700"
                data-testid="template-detail-rate-error"
              >
                {rateError}
              </p>
            ) : null}
            <button
              type="button"
              onClick={() => void handleRateSubmit()}
              disabled={submittingRate || myRating < 1}
              className="mt-2 rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="template-detail-rate-submit"
            >
              {submittingRate ? "提交中..." : "提交评分"}
            </button>
          </section>

          {/* copy error */}
          {copyError !== null ? (
            <p
              className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700"
              data-testid="template-detail-copy-error"
            >
              {copyError}
            </p>
          ) : null}
        </div>

        {/* footer */}
        <footer className="flex items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 p-3">
          <p className="text-[10px] text-slate-400">
            复制后将创建数字员工 (走 employees 生命周期)
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={copying || submittingRate}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:opacity-50"
            >
              关闭
            </button>
            <button
              type="button"
              onClick={() => void handleCopy()}
              disabled={copying}
              className="rounded-md border border-emerald-600 bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="template-detail-copy-button"
            >
              {copying ? "复制中..." : "复制此模板"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}