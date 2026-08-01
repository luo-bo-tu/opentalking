// qiepai · lifecycle 状态机 UI (Phase ❷-6)
//
// 6 个状态卡 (draft / configuring / ready / published / suspended / retired)
// 显示当前状态高亮 + 合法 next 转换按钮
// 拒绝跳跃: 按钮 disabled if 不是合法 next (LIFECYCLE_TRANSITIONS)

import type { ReactNode } from "react";

import type { EmployeeStatus } from "./types";
import {
  LIFECYCLE_LABEL,
  LIFECYCLE_STATES,
  LIFECYCLE_TONE,
  LIFECYCLE_TRANSITIONS,
} from "./types";

export interface LifecycleStateMachineProps {
  current: EmployeeStatus;
  /** 点击合法转换按钮触发 */
  onTransition?: (next: EmployeeStatus) => void;
  /** 禁用所有按钮 (例如发布校验失败) */
  disabled?: boolean;
}

export function LifecycleStateMachine({
  current,
  onTransition,
  disabled = false,
}: LifecycleStateMachineProps): ReactNode {
  const allowed = LIFECYCLE_TRANSITIONS[current];
  const currentIndex = LIFECYCLE_STATES.indexOf(current);

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white p-3"
      data-testid="lifecycle-state-machine"
    >
      {/* 状态进度条 (横向) */}
      <div className="mb-3 flex items-center gap-1" aria-label="lifecycle 进度">
        {LIFECYCLE_STATES.map((state, idx) => {
          const isCurrent = state === current;
          const isPast = idx < currentIndex && current !== "retired";
          const isFuture = idx > currentIndex;
          return (
            <div
              key={state}
              className="flex flex-1 items-center gap-1"
              data-testid={`lifecycle-step-${state}`}
            >
              <div
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold ${
                  isCurrent
                    ? "border-cyan-500 bg-cyan-100 text-cyan-700 ring-2 ring-cyan-200"
                    : isPast
                      ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                      : isFuture
                        ? "border-slate-200 bg-slate-50 text-slate-400"
                        : "border-slate-200 bg-slate-50 text-slate-500"
                }`}
                title={LIFECYCLE_LABEL[state]}
              >
                {idx + 1}
              </div>
              {idx < LIFECYCLE_STATES.length - 1 ? (
                <div
                  className={`h-0.5 flex-1 ${
                    isPast || (isCurrent && current === "retired")
                      ? "bg-emerald-300"
                      : "bg-slate-200"
                  }`}
                />
              ) : null}
            </div>
          );
        })}
      </div>

      {/* 状态标签网格 */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {LIFECYCLE_STATES.map((state) => {
          const isCurrent = state === current;
          return (
            <div
              key={state}
              className={`rounded-md border px-2 py-1.5 text-center ${
                isCurrent
                  ? "border-cyan-400 bg-cyan-50"
                  : "border-slate-200 bg-slate-50"
              }`}
            >
              <span
                className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                  isCurrent ? LIFECYCLE_TONE[state] : "border-slate-200 bg-white text-slate-500"
                }`}
              >
                {LIFECYCLE_LABEL[state]}
              </span>
            </div>
          );
        })}
      </div>

      {/* 合法转换按钮 */}
      <div className="mt-3 border-t border-slate-100 pt-3">
        <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-slate-500">
          合法转换 (从 {LIFECYCLE_LABEL[current]} 出发)
        </p>
        {allowed.length === 0 ? (
          <p className="rounded border border-dashed border-slate-200 p-3 text-[11px] text-slate-400">
            终态 (retired), 不可再转换
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {allowed.map((next) => (
              <button
                key={next}
                type="button"
                onClick={() => onTransition?.(next)}
                disabled={disabled || onTransition === undefined}
                className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                data-testid={`lifecycle-transition-${next}`}
                title={`状态变更为 ${LIFECYCLE_LABEL[next]}`}
              >
                → {LIFECYCLE_LABEL[next]}
              </button>
            ))}
          </div>
        )}
        <p className="mt-2 text-[10px] text-slate-400">
          架构 § 21.5: 状态机拒绝跳跃, 后端是权威
        </p>
      </div>
    </div>
  );
}
