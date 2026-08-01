// qiepai · readiness 状态徽章 (Phase ❷-6)
//
// 三种 readiness 徽章: readiness_p0 / readiness_p1 / sync_state
// 显示: 通过 (绿) / 未通过 (红/橙) + 简短原因 tooltip

import type { ReactNode } from "react";

import type { SyncState } from "./types";
import { SYNC_STATE_LABEL, SYNC_STATE_TONE } from "./types";

export interface ReadinessBadgeProps {
  /** 徽章类型 */
  kind: "p0" | "p1" | "sync";
  /** 是否通过 (对 p0/p1) 或 sync_state 值 */
  passed?: boolean;
  syncState?: SyncState;
  /** 未通过时的简短原因 (tooltip) */
  reason?: string | null;
  /** 显示文案 (默认自动) */
  label?: string;
}

const P0_LABEL_PASS = "P0 通过";
const P0_LABEL_FAIL = "P0 未通过";
const P1_LABEL_PASS = "P1 通过";
const P1_LABEL_FAIL = "P1 未通过";

export function ReadinessBadge({
  kind,
  passed,
  syncState,
  reason,
  label,
}: ReadinessBadgeProps): ReactNode {
  if (kind === "sync") {
    if (syncState === undefined) return null;
    const tone = SYNC_STATE_TONE[syncState];
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${tone}`}
        title={reason ?? SYNC_STATE_LABEL[syncState]}
        data-testid={`readiness-sync-${syncState}`}
      >
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-60" />
        sync · {label ?? SYNC_STATE_LABEL[syncState]}
      </span>
    );
  }

  const isPass = passed === true;
  const defaultLabel =
    kind === "p0"
      ? isPass
        ? P0_LABEL_PASS
        : P0_LABEL_FAIL
      : isPass
        ? P1_LABEL_PASS
        : P1_LABEL_FAIL;
  const displayLabel = label ?? defaultLabel;
  const tone = isPass
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-red-200 bg-red-50 text-red-700";

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${tone}`}
      title={reason ?? displayLabel}
      data-testid={`readiness-${kind}-${isPass ? "pass" : "fail"}`}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-60" />
      {displayLabel}
    </span>
  );
}
