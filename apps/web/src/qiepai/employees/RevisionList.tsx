// qiepai · revision 历史列表 (Phase ❷-6)
//
// 展示 employee 的所有 revision, 按 revision_number 倒序
// 每条: workspace_file_hash + readiness_p0/p1 徽章 + sync_state 徽章 + created_at

import type { ReactNode } from "react";

import { ReadinessBadge } from "./ReadinessBadge";
import type { EmployeeRevision } from "./types";
import {
  LIFECYCLE_LABEL,
  LIFECYCLE_TONE,
} from "./types";

export interface RevisionListProps {
  revisions: EmployeeRevision[];
  /** 当前 revision id (高亮) */
  currentRevisionId: string | null;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function shortHash(hash: string): string {
  // sha256:0001c1...d4e5 → 0001c1...d4e5
  const idx = hash.indexOf(":");
  return idx >= 0 ? hash.slice(idx + 1) : hash;
}

export function RevisionList({
  revisions,
  currentRevisionId,
}: RevisionListProps): ReactNode {
  // 倒序 (新 revision 在前)
  const sorted = [...revisions].sort(
    (a, b) => b.revision_number - a.revision_number,
  );

  return (
    <div
      className="rounded-lg border border-slate-200 bg-white"
      data-testid="revision-list"
    >
      <header className="border-b border-slate-200 p-3">
        <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
          Revision 历史
        </p>
        <p className="mt-0.5 text-xs text-slate-700">
          共 {sorted.length} 个 revision, 最新在前
        </p>
      </header>

      <div className="max-h-[420px] space-y-2 overflow-y-auto p-2">
        {sorted.length === 0 ? (
          <p className="rounded border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">
            暂无 revision
          </p>
        ) : (
          sorted.map((rev) => {
            const isCurrent = rev.id === currentRevisionId;
            return (
              <article
                key={rev.id}
                className={`rounded-lg border p-3 ${
                  isCurrent
                    ? "border-cyan-400 bg-cyan-50/40 ring-1 ring-cyan-200"
                    : "border-slate-200 bg-white"
                }`}
                data-testid={`revision-${rev.id}`}
              >
                <header className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-950">
                      Rev #{rev.revision_number}
                      {isCurrent ? (
                        <span className="ml-2 rounded-full border border-cyan-200 bg-cyan-50 px-1.5 py-0.5 text-[9px] font-medium text-cyan-700">
                          当前
                        </span>
                      ) : null}
                    </p>
                    <p
                      className="mt-0.5 truncate font-mono text-[10px] text-slate-500"
                      title={rev.workspace_file_hash}
                    >
                      hash · {shortHash(rev.workspace_file_hash)}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${LIFECYCLE_TONE[rev.publish_state]}`}
                  >
                    {LIFECYCLE_LABEL[rev.publish_state]}
                  </span>
                </header>

                <div className="flex flex-wrap items-center gap-1.5">
                  <ReadinessBadge kind="p0" passed={rev.readiness_p0} reason={rev.readiness_reason} />
                  <ReadinessBadge kind="p1" passed={rev.readiness_p1} reason={rev.readiness_reason} />
                  <ReadinessBadge
                    kind="sync"
                    syncState={rev.sync_state}
                    reason={rev.readiness_reason}
                  />
                </div>

                <footer className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] text-slate-400">
                  <span>{rev.id}</span>
                  <span className="font-mono">{formatTime(rev.created_at)}</span>
                </footer>
              </article>
            );
          })
        )}
      </div>
    </div>
  );
}
