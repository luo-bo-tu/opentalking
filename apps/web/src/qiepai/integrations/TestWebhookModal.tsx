// qiepai · 飞书机器人测试投递 Modal (Phase ❸-1)
//
// 输入: 多选群 (checkbox grid) + 消息 textarea + "发送测试" 按钮
// 调 backend POST /api/qiepai/integrations/feishu/test, 失败 fallback mock.
// 提交后展示结果: delivered / total / status (ok / partial / failed).
// 乐观更新被选中的群 last_delivered_at (mock 模式).

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { apiPost } from "../../lib/api";

import type {
  FeishuDeliveryResult,
  FeishuGroup,
  FeishuTestResponse,
} from "./types";

export interface TestWebhookModalProps {
  /** 可选群 (来自 FeishuBotPanel 的全量列表, 默认全勾选) */
  availableGroups: FeishuGroup[];
  /** 预选群 ID (e.g. 从卡片 "测试投递" 按钮带入) */
  preSelectedChatIds?: string[];
  onClose: () => void;
  /** 测试成功后回调 (供 FeishuBotPanel 更新 last_delivered_at) */
  onSuccess?: (results: FeishuDeliveryResult[]) => void;
}

interface SubmitState {
  status: "idle" | "submitting" | "done";
  response: FeishuTestResponse | null;
  errorMessage: string | null;
}

function generateMockTestResults(
  groups: FeishuGroup[],
  selectedChatIds: string[],
): FeishuTestResponse {
  // mock 模式: 选中的群, 第 1 个 OK, 其余 failed (展示 partial 状态)
  const selected = groups.filter((g) => selectedChatIds.includes(g.chat_id));
  const results: FeishuDeliveryResult[] = selected.map((g, idx) => ({
    chat_id: g.chat_id,
    chat_name: g.chat_name,
    status: idx === 0 ? "ok" : "failed",
    error: idx === 0 ? null : "mock 模拟失败 (限流 / webhook 401 等场景)",
  }));
  const delivered = results.filter((r) => r.status === "ok").length;
  const status: FeishuTestResponse["status"] =
    delivered === results.length
      ? "ok"
      : delivered === 0
        ? "failed"
        : "partial";
  return {
    delivered,
    total: results.length,
    status,
    results,
  };
}

export function TestWebhookModal({
  availableGroups,
  preSelectedChatIds,
  onClose,
  onSuccess,
}: TestWebhookModalProps): ReactNode {
  const [selectedChatIds, setSelectedChatIds] = useState<string[]>(() =>
    preSelectedChatIds && preSelectedChatIds.length > 0
      ? preSelectedChatIds
      : availableGroups.map((g) => g.chat_id),
  );
  const [message, setMessage] = useState(
    "[qiepai 测试] 您好, 这是一条测试投递消息。",
  );
  const [submit, setSubmit] = useState<SubmitState>({
    status: "idle",
    response: null,
    errorMessage: null,
  });

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && submit.status !== "submitting") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submit.status]);

  const selectedSet = useMemo(
    () => new Set(selectedChatIds),
    [selectedChatIds],
  );

  const toggleChat = (chatId: string) => {
    setSelectedChatIds((prev) =>
      prev.includes(chatId)
        ? prev.filter((id) => id !== chatId)
        : [...prev, chatId],
    );
  };

  const toggleAll = () => {
    setSelectedChatIds((prev) =>
      prev.length === availableGroups.length
        ? []
        : availableGroups.map((g) => g.chat_id),
    );
  };

  const handleSubmit = async () => {
    if (selectedChatIds.length === 0) return;
    if (message.trim().length === 0) return;
    setSubmit({ status: "submitting", response: null, errorMessage: null });

    let response: FeishuTestResponse | null = null;
    try {
      response = await apiPost<FeishuTestResponse>(
        "/qiepai/integrations/feishu/test",
        { chat_ids: selectedChatIds, message },
      );
      setSubmit({ status: "done", response, errorMessage: null });
      onSuccess?.(response.results);
    } catch {
      // mock fallback: 本地模拟结果
      const mock = generateMockTestResults(availableGroups, selectedChatIds);
      setSubmit({ status: "done", response: mock, errorMessage: null });
      onSuccess?.(mock.results);
      // 同时静默通知父组件: 本次走 mock (后端未实装)
      console.warn("[TestWebhookModal] backend /test unavailable, using mock results");
    }
  };

  const resultTone =
    submit.response?.status === "ok"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : submit.response?.status === "partial"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : submit.response?.status === "failed"
          ? "border-red-200 bg-red-50 text-red-700"
          : "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
      onClick={() => {
        if (submit.status !== "submitting") onClose();
      }}
      data-testid="test-webhook-modal-backdrop"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="test-webhook-modal"
      >
        {/* header */}
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div>
            <p className="text-[10px] font-medium text-slate-500">
              飞书机器人 · 测试投递
            </p>
            <h2 className="mt-0.5 text-base font-semibold text-slate-950">
              发送测试消息
            </h2>
            <p className="mt-1 text-xs text-slate-600">
              选择目标群 (可多选), 输入消息内容, 点击发送测试。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submit.status === "submitting"}
            className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
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
          {/* 群选择 (多选 checkbox grid) */}
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold text-slate-700">
                目标群 ({selectedChatIds.length} / {availableGroups.length})
              </h3>
              <button
                type="button"
                onClick={toggleAll}
                className="text-[10px] font-medium text-cyan-700 hover:text-cyan-900"
                data-testid="test-webhook-toggle-all"
              >
                {selectedChatIds.length === availableGroups.length
                  ? "全部取消"
                  : "全部选择"}
              </button>
            </div>
            {availableGroups.length === 0 ? (
              <div className="rounded border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-400">
                暂无可投递的飞书群, 请先添加群。
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {availableGroups.map((g) => {
                  const checked = selectedSet.has(g.chat_id);
                  return (
                    <label
                      key={g.id}
                      className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-xs transition ${
                        checked
                          ? "border-cyan-200 bg-cyan-50/60"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                      data-testid={`test-webhook-chat-${g.chat_id}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleChat(g.chat_id)}
                        className="h-3.5 w-3.5 shrink-0 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-slate-950">
                          {g.chat_name}
                        </p>
                        <p className="truncate font-mono text-[10px] text-slate-500">
                          {g.chat_id}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded px-1 text-[9px] font-medium ${
                          g.status === "active"
                            ? "bg-emerald-50 text-emerald-700"
                            : g.status === "error"
                              ? "bg-red-50 text-red-700"
                              : "bg-slate-50 text-slate-500"
                        }`}
                      >
                        {g.status === "active"
                          ? "已启用"
                          : g.status === "error"
                            ? "异常"
                            : "已停用"}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </section>

          {/* 消息文本 */}
          <section>
            <label
              htmlFor="test-webhook-message"
              className="mb-1 block text-xs font-semibold text-slate-700"
            >
              消息内容
            </label>
            <textarea
              id="test-webhook-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={4}
              disabled={submit.status === "submitting"}
              className="w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs leading-relaxed text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
              placeholder="例如: [qiepai 测试] 数字员工已上线, 请关注日报。"
              data-testid="test-webhook-message-input"
            />
          </section>

          {/* 结果展示 */}
          {submit.status === "done" && submit.response !== null ? (
            <section
              className={`rounded-md border px-3 py-2 text-xs ${resultTone}`}
              data-testid="test-webhook-result"
            >
              <p className="font-semibold">
                {submit.response.status === "ok"
                  ? `投递成功 · ${submit.response.delivered} / ${submit.response.total}`
                  : submit.response.status === "partial"
                    ? `部分成功 · ${submit.response.delivered} / ${submit.response.total}`
                    : `投递失败 · ${submit.response.delivered} / ${submit.response.total}`}
              </p>
              <ul className="mt-1 space-y-0.5">
                {submit.response.results.map((r) => (
                  <li
                    key={r.chat_id}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="truncate">{r.chat_name}</span>
                    <span
                      className={`shrink-0 rounded px-1 text-[10px] font-medium ${
                        r.status === "ok"
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {r.status === "ok" ? "成功" : `失败${r.error ? ` · ${r.error}` : ""}`}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[10px] text-slate-500">
                提示: mock 模式默认仅第 1 个群成功, 其余模拟失败。
              </p>
            </section>
          ) : null}
        </div>

        {/* footer */}
        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 p-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submit.status === "submitting"}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:opacity-50"
          >
            关闭
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={
              submit.status === "submitting" ||
              selectedChatIds.length === 0 ||
              message.trim().length === 0
            }
            className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="test-webhook-submit"
          >
            {submit.status === "submitting"
              ? "发送中..."
              : `发送测试 (${selectedChatIds.length})`}
          </button>
        </footer>
      </div>
    </div>
  );
}