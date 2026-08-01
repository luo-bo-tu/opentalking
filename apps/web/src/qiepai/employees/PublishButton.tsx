// qiepai · publish 按钮 (Phase ❷-6)
//
// 前端校验 (❷-6 § 6.2 + 架构 § 21.5):
//   - readiness_p0 = true
//   - readiness_p1 = true
//   - sync_state != 'error'
//   - sync_state != 'drifted'
// 全部满足 → enabled, 否则 disabled + tooltip 列出未满足项
// 后端是真权威 (前端 disabled 是 UX 提示, 实际以 backend 422 为准)

import type { ReactNode } from "react";

import type { EmployeeRevision, EmployeeStatus } from "./types";
import { checkPublishReadiness } from "./types";

export interface PublishButtonProps {
  /** 当前 employee 状态 (决定按钮文案 + 可发布的下一态) */
  currentStatus: EmployeeStatus;
  /** 当前 revision (用于 readiness 校验) */
  currentRevision: EmployeeRevision | null;
  /** 点击触发 publish */
  onPublish: (targetStatus: EmployeeStatus) => void;
}

/** 按钮文案 (按当前状态映射发布目标) */
function getPublishLabel(status: EmployeeStatus): string | null {
  switch (status) {
    case "draft":
      return null; // draft 不在按钮组, 走 LifecycleStateMachine 的 configuring 按钮
    case "configuring":
      return null; // 同上
    case "ready":
      return "发布数字员工 (→ published)";
    case "published":
      return "暂停数字员工 (→ suspended)";
    case "suspended":
      return "恢复数字员工 (→ published)";
    case "retired":
      return null; // 终态
  }
}

function getPublishTarget(status: EmployeeStatus): EmployeeStatus | null {
  switch (status) {
    case "ready":
      return "published";
    case "published":
      return "suspended";
    case "suspended":
      return "published";
    default:
      return null;
  }
}

export function PublishButton({
  currentStatus,
  currentRevision,
  onPublish,
}: PublishButtonProps): ReactNode {
  const label = getPublishLabel(currentStatus);
  const target = getPublishTarget(currentStatus);

  if (label === null || target === null) {
    return (
      <div
        className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-400"
        data-testid="publish-button-empty"
      >
        当前状态 ({currentStatus}) 无 publish 操作, 请用 lifecycle 状态机的合法转换按钮
      </div>
    );
  }

  const check = checkPublishReadiness(currentRevision);
  const blockedByReadiness = currentStatus === "ready" && !check.passed;

  return (
    <div
      className={`rounded-lg border p-3 ${
        check.passed
          ? "border-emerald-200 bg-emerald-50/40"
          : "border-amber-200 bg-amber-50/40"
      }`}
      data-testid="publish-button"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
            发布前置检查
          </p>
          <p
            className={`mt-0.5 text-xs font-semibold ${
              check.passed ? "text-emerald-700" : "text-amber-700"
            }`}
          >
            {check.passed ? "✓ 全部通过, 可以发布" : `⚠ ${check.issues.length} 项未满足`}
          </p>
          {!check.passed ? (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-slate-600">
              {check.issues.map((issue, idx) => (
                <li key={idx}>{issue}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => onPublish(target)}
          disabled={blockedByReadiness}
          className="shrink-0 rounded-md border border-emerald-600 bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="publish-button-action"
          title={
            blockedByReadiness
              ? `发布未满足: ${check.issues.join("; ")}`
              : "发布到下一状态 (前端校验通过, 后端是权威)"
          }
        >
          {label}
        </button>
      </div>
      <p className="mt-2 text-[10px] text-slate-400">
        前端校验是 UX 提示, 实际以 backend 422 为准
      </p>
    </div>
  );
}
