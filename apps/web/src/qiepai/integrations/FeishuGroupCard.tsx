// qiepai · 飞书单群卡片 (Phase ❸-1)
//
// 显示一个飞书群绑定:
//   - chat_name + chat_id (monospace)
//   - credential_kind (webhook / bot_token) + 截断预览
//   - last_delivered_at + last_delivery_status (架构 §21.1 三态渲染)
//   - status (active / inactive / error) badge
//   - 删除按钮 (调 onDelete prop, 由父组件决定真后端还是 mock)
//
// 数据来源: 父组件传 FeishuGroup, 不在此组件里 fetch.
// hover 历史投递: 卡片右上 hover 显示最近 3 条 (mock recent_deliveries).

import { useState } from "react";
import type { ReactNode } from "react";

import type { FeishuGroup } from "./types";

export interface FeishuGroupCardProps {
  group: FeishuGroup;
  onDelete?: (group: FeishuGroup) => void;
  onTest?: (group: FeishuGroup) => void;
}

const STATUS_LABEL: Record<FeishuGroup["status"], string> = {
  active: "已启用",
  inactive: "已停用",
  error: "异常",
};

const STATUS_TONE: Record<FeishuGroup["status"], string> = {
  active: "border-emerald-200 bg-emerald-50 text-emerald-700",
  inactive: "border-slate-200 bg-slate-50 text-slate-600",
  error: "border-red-200 bg-red-50 text-red-700",
};

const DELIVERY_STATUS_LABEL: Record<string, string> = {
  ok: "成功",
  failed: "失败",
  rate_limited: "限流",
};

function formatAsOf(asOf: unknown): string | null {
  if (typeof asOf !== "string" || asOf.length === 0) return null;
  try {
    const d = new Date(asOf);
    if (Number.isNaN(d.getTime())) return asOf;
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return asOf;
  }
}

function freshnessSeconds(asOf: string): number | null {
  try {
    const d = new Date(asOf);
    if (Number.isNaN(d.getTime())) return null;
    return Math.floor((Date.now() - d.getTime()) / 1000);
  } catch {
    return null;
  }
}

export function FeishuGroupCard({
  group,
  onDelete,
  onTest,
}: FeishuGroupCardProps): ReactNode {
  const [hovered, setHovered] = useState(false);
  const lastAsOf = formatAsOf(group.last_delivered_at);
  const asOf = formatAsOf(group.as_of);
  const fresh = group.as_of ? freshnessSeconds(group.as_of) : null;
  const isStale = fresh !== null && fresh > 86_400;
  const credentialLabel =
    group.credential_kind === "webhook"
      ? `webhook · ${group.webhook_url}`
      : `bot_token · ${group.bot_token_masked ?? "(未配置)"}`;
  const recentDeliveries = group.recent_deliveries ?? [];

  return (
    <article
      className="relative rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-cyan-200 hover:shadow-md"
      data-testid={`feishu-group-card-${group.id}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* hover 历史投递浮层 (mock recent_deliveries) */}
      {hovered && recentDeliveries.length > 0 ? (
        <div
          className="absolute right-3 top-3 z-10 w-72 rounded-md border border-slate-200 bg-white p-2 shadow-lg"
          data-testid={`feishu-group-card-${group.id}-history`}
        >
          <p className="mb-1 text-[10px] font-medium text-slate-500">
            最近 {recentDeliveries.length} 条投递
          </p>
          <ul className="space-y-1">
            {recentDeliveries.slice(0, 3).map((d) => (
              <li
                key={d.id}
                className="border-b border-slate-100 pb-1 text-[10px] last:border-b-0 last:pb-0"
              >
                <div className="flex items-center justify-between gap-1">
                  <span
                    className={`shrink-0 rounded px-1 text-[9px] font-medium ${
                      d.status === "ok"
                        ? "bg-emerald-50 text-emerald-700"
                        : d.status === "failed"
                          ? "bg-red-50 text-red-700"
                          : "bg-amber-50 text-amber-700"
                    }`}
                  >
                    {DELIVERY_STATUS_LABEL[d.status] ?? d.status}
                  </span>
                  <span className="truncate font-mono text-slate-400">
                    {formatAsOf(d.created_at)}
                  </span>
                </div>
                <p className="mt-0.5 truncate text-slate-700" title={d.message_preview}>
                  {d.message_preview}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* header: chat_name + status badge */}
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
            飞书群
          </p>
          <h3 className="mt-0.5 truncate text-sm font-semibold text-slate-950">
            {group.chat_name}
          </h3>
          <p
            className="mt-0.5 truncate font-mono text-[10px] text-slate-500"
            title={group.chat_id}
          >
            {group.chat_id}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${STATUS_TONE[group.status]}`}
          data-testid={`feishu-group-status-${group.status}`}
        >
          {STATUS_LABEL[group.status]}
        </span>
      </header>

      {/* credential */}
      <div className="mt-3">
        <p className="text-[10px] text-slate-400">凭证</p>
        <p
          className="mt-0.5 truncate font-mono text-[11px] text-slate-700"
          title={credentialLabel}
        >
          {credentialLabel}
        </p>
      </div>

      {/* last delivered */}
      <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
        <div>
          <p className="text-slate-400">上次投递</p>
          {lastAsOf !== null ? (
            <p className="mt-0.5 font-mono text-slate-700">{lastAsOf}</p>
          ) : (
            <p className="mt-0.5 text-slate-400">从未投递</p>
          )}
        </div>
        <div>
          <p className="text-slate-400">上次状态</p>
          {group.last_delivery_status !== null ? (
            <p
              className={`mt-0.5 font-medium ${
                group.last_delivery_status === "ok"
                  ? "text-emerald-700"
                  : group.last_delivery_status === "failed"
                    ? "text-red-700"
                    : "text-amber-700"
              }`}
            >
              {DELIVERY_STATUS_LABEL[group.last_delivery_status] ??
                group.last_delivery_status}
            </p>
          ) : (
            <p className="mt-0.5 text-slate-400">—</p>
          )}
        </div>
      </div>

      {/* source + as_of */}
      <div className="mt-3 flex items-center justify-between gap-2 text-[10px]">
        <p className="truncate font-mono text-slate-400" title={group.source}>
          {group.source}
        </p>
        {asOf !== null ? (
          <span
            className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium ${
              isStale
                ? "bg-amber-50 text-amber-700"
                : "bg-slate-50 text-slate-500"
            }`}
            title={isStale ? "数据快照已超过 24 小时" : "数据快照时间"}
          >
            {isStale ? "过期 · " : ""}
            asOf {asOf}
          </span>
        ) : null}
      </div>

      {/* actions */}
      <footer className="mt-3 flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
        {onTest !== undefined ? (
          <button
            type="button"
            onClick={() => onTest(group)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-medium text-slate-600 transition hover:border-cyan-300 hover:text-cyan-700"
            data-testid={`feishu-group-test-${group.id}`}
            title="对该群发送测试消息"
          >
            测试投递
          </button>
        ) : null}
        {onDelete !== undefined ? (
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm(
                  `确认删除飞书群「${group.chat_name}」?\n删除后将停止向该群投递消息。`,
                )
              ) {
                onDelete(group);
              }
            }}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-medium text-slate-600 transition hover:border-red-300 hover:text-red-700"
            data-testid={`feishu-group-delete-${group.id}`}
            title="解除该飞书群绑定"
          >
            删除
          </button>
        ) : null}
      </footer>
    </article>
  );
}