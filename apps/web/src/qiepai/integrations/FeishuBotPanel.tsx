// qiepai · 飞书机器人配置 Panel (Phase ❸-1)
//
// 顶部 header + 3-button 工具栏 (添加群 / 测试投递 / 立即刷新) + 群列表网格.
// 数据来源: GET /api/qiepai/integrations/feishu/groups, 失败 fallback MOCK_GROUPS.
// 模式: 乐观更新 + POST 失败不阻塞 (mock fallback), 跟 DecisionsTab / EmployeesTab 一致.
//
// 添加群: 调 POST /groups, 失败时本地添加 (mock add).
// 删除群: 调 DELETE /groups/{id}, 失败时本地移除 (mock del).
// 测试投递: 打开 TestWebhookModal.

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiDelete, apiGet, apiPost } from "../../lib/api";

import { FeishuGroupCard } from "./FeishuGroupCard";
import { TestWebhookModal } from "./TestWebhookModal";
import { MOCK_GROUPS } from "./mockData";
import type {
  FeishuGroup,
  FeishuGroupCreatePayload,
  FeishuGroupCreateResponse,
  FeishuGroupsResponse,
} from "./types";

type AddGroupStatus =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string };

interface AddGroupFormState {
  chat_id: string;
  chat_name: string;
  credential_kind: "webhook" | "bot_token";
  webhook_url: string;
  bot_token: string;
}

const EMPTY_FORM: AddGroupFormState = {
  chat_id: "",
  chat_name: "",
  credential_kind: "webhook",
  webhook_url: "",
  bot_token: "",
};

export function FeishuBotPanel(): ReactNode {
  const [groups, setGroups] = useState<FeishuGroup[] | null>(null);
  const [isMock, setIsMock] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<AddGroupFormState>(EMPTY_FORM);
  const [addStatus, setAddStatus] = useState<AddGroupStatus>({ kind: "idle" });

  const [testOpen, setTestOpen] = useState(false);
  const [preSelectedChatIds, setPreSelectedChatIds] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    try {
      const response = await apiGet<FeishuGroupsResponse>(
        "/qiepai/integrations/feishu/groups",
      );
      if (!Array.isArray(response.items)) {
        throw new Error("Expected {items: FeishuGroup[], total: number}");
      }
      setGroups(response.items);
      setIsMock(false);
      setErrorCount(0);
    } catch {
      // 后端 stub 友好: fallback mock
      setGroups(MOCK_GROUPS);
      setIsMock(true);
      setErrorCount(1);
    }
    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleAddGroup = useCallback(async () => {
    if (addForm.chat_id.trim().length === 0) {
      setAddStatus({ kind: "error", message: "chat_id 不能为空" });
      return;
    }
    if (
      addForm.credential_kind === "webhook" &&
      addForm.webhook_url.trim().length === 0
    ) {
      setAddStatus({ kind: "error", message: "webhook_url 不能为空" });
      return;
    }
    if (
      addForm.credential_kind === "bot_token" &&
      addForm.bot_token.trim().length === 0
    ) {
      setAddStatus({ kind: "error", message: "bot_token 不能为空" });
      return;
    }

    setAddStatus({ kind: "submitting" });

    const payload: FeishuGroupCreatePayload = {
      chat_id: addForm.chat_id.trim(),
      credential_kind: addForm.credential_kind,
    };
    if (addForm.chat_name.trim().length > 0) {
      payload.chat_name = addForm.chat_name.trim();
    }
    if (addForm.credential_kind === "webhook") {
      payload.webhook_url = addForm.webhook_url.trim();
    } else {
      payload.bot_token = addForm.bot_token.trim();
    }

    // 1) 乐观更新本地 (UI 立即响应)
    const optimisticId = `mock-grp-${Date.now()}`;
    const trimmedWebhook = addForm.webhook_url.trim();
    const maskedWebhook =
      addForm.credential_kind === "webhook"
        ? trimmedWebhook.length > 12
          ? `${trimmedWebhook.slice(0, 4)}****${trimmedWebhook.slice(-4)}`
          : trimmedWebhook
        : "";
    const trimmedToken = addForm.bot_token.trim();
    const maskedToken =
      addForm.credential_kind === "bot_token"
        ? trimmedToken.length > 8
          ? `${trimmedToken.slice(0, 4)}****${trimmedToken.slice(-4)}`
          : trimmedToken
        : null;
    const optimisticGroup: FeishuGroup = {
      id: optimisticId,
      chat_id: addForm.chat_id.trim(),
      chat_name: addForm.chat_name.trim() || addForm.chat_id.trim(),
      webhook_url: maskedWebhook,
      bot_token_masked: maskedToken,
      credential_kind: addForm.credential_kind,
      status: "active",
      last_delivered_at: null,
      last_delivery_status: null,
      source: "mock://feishu/groups/v1 (本地乐观更新)",
      as_of: new Date().toISOString(),
      recent_deliveries: [],
    };
    setGroups((prev) =>
      prev === null ? [optimisticGroup] : [optimisticGroup, ...prev],
    );

    // 2) 真正调后端 POST
    //    - success: 用后端返回的 item 替换 optimistic, 关闭 modal + reset form
    //    - failure: rollback optimistic (不保留假数据), 显示 inline error, 不关闭 modal 让用户重试
    try {
      const response = await apiPost<FeishuGroupCreateResponse>(
        "/qiepai/integrations/feishu/groups",
        payload,
      );
      // 后端成功: 用后端返回的 item 替换 optimistic
      if (response && response.item && typeof response.item.id === "string") {
        setGroups((prev) =>
          prev === null
            ? [response.item]
            : prev.map((g) => (g.id === optimisticId ? response.item : g)),
        );
      }
      // success → 关闭 modal, reset form
      setAddStatus({ kind: "idle" });
      setAddForm(EMPTY_FORM);
      setAddOpen(false);
    } catch (err) {
      console.warn("[FeishuBotPanel] POST /groups failed:", err);
      // 失败: rollback optimistic (避免假数据), 不关闭 modal, 让用户看到错误 + 可重试
      setGroups((prev) =>
        prev === null ? prev : prev.filter((g) => g.id !== optimisticId),
      );
      const message =
        err instanceof Error && err.message.length > 0
          ? err.message
          : "保存失败, 请稍后重试";
      setAddStatus({ kind: "error", message });
      // 不 reset form, 不关闭 modal, 用户可修改后重新提交
    }
  }, [addForm]);

  const handleDeleteGroup = useCallback(async (group: FeishuGroup) => {
    // 1) 乐观移除本地
    setGroups((prev) =>
      prev === null ? prev : prev.filter((g) => g.id !== group.id),
    );
    // 2) 真正调后端 DELETE, 失败 rollback
    try {
      await apiDelete<{ deleted: boolean; id: string }>(
        `/qiepai/integrations/feishu/groups/${encodeURIComponent(group.id)}`,
      );
    } catch (err) {
      // 失败 rollback: 把 group 加回去
      console.warn("[FeishuBotPanel] DELETE /groups/{id} failed:", err);
      setGroups((prev) => {
        if (prev === null) return prev;
        if (prev.some((g) => g.id === group.id)) return prev;
        return [group, ...prev];
      });
    }
  }, []);

  const handleOpenTestForGroup = useCallback((group: FeishuGroup) => {
    setPreSelectedChatIds([group.chat_id]);
    setTestOpen(true);
  }, []);

  const handleOpenTestAll = useCallback(() => {
    setPreSelectedChatIds([]);
    setTestOpen(true);
  }, []);

  // 测试投递成功后, 更新被投递的群 last_delivered_at (mock 模式)
  const handleTestSuccess = useCallback(
    (results: Array<{ chat_id: string; status: "ok" | "failed" }>) => {
      const now = new Date().toISOString();
      const resultMap = new Map(
        results.map((r) => [r.chat_id, r.status] as const),
      );
      setGroups((prev) =>
        prev === null
          ? prev
          : prev.map((g) => {
              const r = resultMap.get(g.chat_id);
              if (r === undefined) return g;
              return {
                ...g,
                last_delivered_at: now,
                last_delivery_status: r,
              };
            }),
      );
    },
    [],
  );

  return (
    <section
      className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4"
      data-testid="feishu-bot-panel"
    >
      {/* header */}
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">
            qiepai · Integrations / Feishu
          </p>
          <h1 className="text-base font-semibold text-slate-950">飞书机器人</h1>
          <p className="mt-0.5 text-[10px] text-slate-400">
            绑定飞书群, 让 qiepai 数字员工向群里投递日报 / 告警 / 审批消息
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          {isMock ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
              title="后端 /qiepai/integrations/feishu/* 尚未实装, 当前显示前端 mock 数据"
              data-testid="feishu-mock-badge"
            >
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
              mock 模式
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                errorCount === 0 ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
            {errorCount === 0
              ? "数据源 OK"
              : `${errorCount} 个 endpoint 异常`}
          </span>
          <span>
            手动刷新 · 上次{" "}
            {lastRefresh.toLocaleTimeString("zh-CN", { hour12: false })}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700"
            data-testid="feishu-refresh"
          >
            立即刷新
          </button>
        </div>
      </header>

      {/* 工具栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span className="font-medium">
            已绑定群 ({groups?.length ?? 0})
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleOpenTestAll}
            disabled={groups === null || groups.length === 0}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="feishu-test-all-button"
          >
            测试投递
          </button>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700"
            data-testid="feishu-add-button"
          >
            + 添加群
          </button>
        </div>
      </div>

      {/* 群列表 */}
      {groups === null ? (
        <div
          className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-700"
          data-testid="feishu-loading"
        >
          飞书群数据加载中...
        </div>
      ) : groups.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-white p-8 text-center text-xs text-slate-400"
          data-testid="feishu-empty"
        >
          <p className="text-sm font-medium text-slate-500">
            暂无飞书机器人绑定
          </p>
          <p>点击右上角「+ 添加群」开始绑定飞书群, 让数字员工向群里投递消息。</p>
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="mt-2 rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700"
          >
            + 添加群
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((g) => (
            <FeishuGroupCard
              key={g.id}
              group={g}
              onDelete={handleDeleteGroup}
              onTest={handleOpenTestForGroup}
            />
          ))}
        </div>
      )}

      {/* 添加群 modal */}
      {addOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
          onClick={() => {
            if (addStatus.kind !== "submitting") {
              setAddOpen(false);
              setAddForm(EMPTY_FORM);
              setAddStatus({ kind: "idle" });
            }
          }}
          data-testid="add-group-modal-backdrop"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            data-testid="add-group-modal"
          >
            <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
              <div>
                <p className="text-[10px] font-medium text-slate-500">
                  飞书机器人 · 添加群
                </p>
                <h2 className="mt-0.5 text-base font-semibold text-slate-950">
                  绑定新飞书群
                </h2>
                <p className="mt-1 text-xs text-slate-600">
                  填写 chat_id 和凭证 (webhook 或 bot_token 二选一)。
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setAddOpen(false);
                  setAddForm(EMPTY_FORM);
                  setAddStatus({ kind: "idle" });
                }}
                disabled={addStatus.kind === "submitting"}
                className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
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
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              <div>
                <label
                  htmlFor="add-chat-id"
                  className="mb-1 block text-[10px] font-medium text-slate-600"
                >
                  chat_id <span className="text-red-500">*</span>
                </label>
                <input
                  id="add-chat-id"
                  type="text"
                  value={addForm.chat_id}
                  onChange={(e) =>
                    setAddForm((p) => ({ ...p, chat_id: e.target.value }))
                  }
                  placeholder="例如: oc_xxxxxxxxxxxx"
                  disabled={addStatus.kind === "submitting"}
                  className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                  data-testid="add-chat-id-input"
                />
              </div>
              <div>
                <label
                  htmlFor="add-chat-name"
                  className="mb-1 block text-[10px] font-medium text-slate-600"
                >
                  chat_name (可选, 用于 UI 显示)
                </label>
                <input
                  id="add-chat-name"
                  type="text"
                  value={addForm.chat_name}
                  onChange={(e) =>
                    setAddForm((p) => ({ ...p, chat_name: e.target.value }))
                  }
                  placeholder="例如: 财务审计日报群"
                  disabled={addStatus.kind === "submitting"}
                  className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                  data-testid="add-chat-name-input"
                />
              </div>
              <div>
                <p className="mb-1 block text-[10px] font-medium text-slate-600">
                  凭证类型 <span className="text-red-500">*</span>
                </p>
                <div className="flex gap-2">
                  {(
                    [
                      ["webhook", "webhook_url (推荐)"],
                      ["bot_token", "bot_token (app)"],
                    ] as Array<["webhook" | "bot_token", string]>
                  ).map(([kind, label]) => (
                    <label
                      key={kind}
                      className={`flex flex-1 cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-xs transition ${
                        addForm.credential_kind === kind
                          ? "border-cyan-200 bg-cyan-50/60"
                          : "border-slate-200 bg-white hover:border-slate-300"
                      }`}
                    >
                      <input
                        type="radio"
                        name="credential_kind"
                        value={kind}
                        checked={addForm.credential_kind === kind}
                        onChange={() =>
                          setAddForm((p) => ({
                            ...p,
                            credential_kind: kind,
                          }))
                        }
                        disabled={addStatus.kind === "submitting"}
                        className="h-3.5 w-3.5 text-cyan-600 focus:ring-cyan-500"
                        data-testid={`add-credential-kind-${kind}`}
                      />
                      <span className="font-medium text-slate-700">{label}</span>
                    </label>
                  ))}
                </div>
              </div>
              {addForm.credential_kind === "webhook" ? (
                <div>
                  <label
                    htmlFor="add-webhook-url"
                    className="mb-1 block text-[10px] font-medium text-slate-600"
                  >
                    webhook_url <span className="text-red-500">*</span>
                  </label>
                  <input
                    id="add-webhook-url"
                    type="text"
                    value={addForm.webhook_url}
                    onChange={(e) =>
                      setAddForm((p) => ({
                        ...p,
                        webhook_url: e.target.value,
                      }))
                    }
                    placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                    disabled={addStatus.kind === "submitting"}
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                    data-testid="add-webhook-url-input"
                  />
                </div>
              ) : (
                <div>
                  <label
                    htmlFor="add-bot-token"
                    className="mb-1 block text-[10px] font-medium text-slate-600"
                  >
                    bot_token <span className="text-red-500">*</span>
                  </label>
                  <input
                    id="add-bot-token"
                    type="password"
                    value={addForm.bot_token}
                    onChange={(e) =>
                      setAddForm((p) => ({
                        ...p,
                        bot_token: e.target.value,
                      }))
                    }
                    placeholder="t-xxxxxxxxxxxx"
                    disabled={addStatus.kind === "submitting"}
                    className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                    data-testid="add-bot-token-input"
                  />
                </div>
              )}
              {addStatus.kind === "error" ? (
                <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700">
                  {addStatus.message}
                </p>
              ) : null}
            </div>
            <footer className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 p-3">
              <button
                type="button"
                onClick={() => {
                  setAddOpen(false);
                  setAddForm(EMPTY_FORM);
                  setAddStatus({ kind: "idle" });
                }}
                disabled={addStatus.kind === "submitting"}
                className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleAddGroup()}
                disabled={addStatus.kind === "submitting"}
                className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                data-testid="add-group-submit"
              >
                {addStatus.kind === "submitting" ? "提交中..." : "提交"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}

      {/* 测试投递 modal */}
      {testOpen && groups !== null ? (
        <TestWebhookModal
          availableGroups={groups}
          preSelectedChatIds={
            preSelectedChatIds.length > 0 ? preSelectedChatIds : undefined
          }
          onClose={() => setTestOpen(false)}
          onSuccess={handleTestSuccess}
        />
      ) : null}
    </section>
  );
}