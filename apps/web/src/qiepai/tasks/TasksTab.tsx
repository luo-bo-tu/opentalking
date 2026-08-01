// qiepai · 业务任务顶层组件 (Phase ❷-6)
//
// 布局: header + 左 50% TaskList + 右 50% TaskDetailPanel
// 数据: 优先 fetch /qiepai/tasks (返回 {items, total}), 失败 fallback MOCK_TASKS
// 状态转换: 乐观更新 + PATCH /qiepai/tasks/{id}, 失败 rollback (同 DecisionsTab 模式)

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiGet, buildApiUrl } from "../../lib/api";

import { MOCK_TASKS } from "./mockData";
import { TaskDetailPanel } from "./TaskDetailPanel";
import { TaskList } from "./TaskList";
import type {
  TaskItem,
  TaskPatchPayload,
  TaskStatusFilter,
} from "./types";

const AUTO_REFRESH_MS: number | null = null;

export default function TasksTab(): ReactNode {
  const [items, setItems] = useState<TaskItem[] | null>(null);
  const [filter, setFilter] = useState<TaskStatusFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);
  const [isMock, setIsMock] = useState(false);

  const refresh = useCallback(async () => {
    try {
      // 后端 list endpoint 返回 {items: TaskItem[], total: number}
      const response = await apiGet<{ items: TaskItem[]; total: number }>(
        "/qiepai/tasks",
      );
      // 取 .items; 网络错 / shape 不对 由 catch 兜底
      const data = response.items;
      setItems(data);
      setIsMock(false);
      setErrorCount(0);
    } catch {
      // 后端 stub / 网络错 → fallback mock
      setItems(MOCK_TASKS);
      setIsMock(true);
      setErrorCount(1);
    }
    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    if (AUTO_REFRESH_MS !== null) {
      const id = window.setInterval(() => void refresh(), AUTO_REFRESH_MS);
      return () => window.clearInterval(id);
    }
    return undefined;
  }, [refresh]);

  // 默认选中第一条 (filter 后)
  useEffect(() => {
    if (items === null || selectedId !== null) return;
    const filtered =
      filter === "all"
        ? items
        : items.filter((i) => i.status === filter);
    if (filtered.length > 0) {
      setSelectedId(filtered[0].id);
    } else if (items.length > 0) {
      setSelectedId(items[0].id);
    }
  }, [items, filter, selectedId]);

  const handleCardClick = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const handleTransition = useCallback(
    async (id: string, patch: TaskPatchPayload): Promise<void> => {
      const newStatus = patch.status;
      // 1) 乐观更新本地 (UI 立即响应)
      const originalStatus = items?.find((i) => i.id === id)?.status ?? null;
      setItems((prev) => {
        if (prev === null) return prev;
        return prev.map((item) =>
          item.id === id ? { ...item, status: newStatus } : item,
        );
      });
      // 2) 真正调后端 PATCH /qiepai/tasks/{id}
      try {
        const res = await fetch(
          buildApiUrl(`/qiepai/tasks/${encodeURIComponent(id)}`),
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus }),
          },
        );
        if (!res.ok) {
          throw new Error(`PATCH /qiepai/tasks/${id} failed: HTTP ${res.status}`);
        }
      } catch (err) {
        // 3) 失败 rollback (404 / 422 / 409 / 网络错都 rollback)
        setItems((prev) => {
          if (prev === null || originalStatus === null) return prev;
          return prev.map((item) =>
            item.id === id ? { ...item, status: originalStatus } : item,
          );
        });
        console.error("[TasksTab] handleTransition failed:", err);
      }
    },
    [items],
  );

  const selectedItem = items?.find((i) => i.id === selectedId) ?? null;

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4">
      {/* header */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">qiepai · Tasks</p>
          <h1 className="text-base font-semibold text-slate-950">业务任务</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          {isMock ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
              title="后端 /qiepai/tasks 尚未实装, 当前显示前端 mock 数据"
              data-testid="tasks-mock-badge"
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
            {errorCount === 0 ? "数据源 OK" : `${errorCount} 个数据源异常`}
          </span>
          <span>
            手动刷新 · 上次{" "}
            {lastRefresh.toLocaleTimeString("zh-CN", { hour12: false })}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700"
          >
            立即刷新
          </button>
        </div>
      </section>

      {/* 2-column: 50% / 50% */}
      <section className="grid min-h-[600px] flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        {items === null ? (
          <div className="col-span-full rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-700">
            业务任务数据加载中...
          </div>
        ) : selectedItem === null ? (
          <>
            <TaskList
              items={items}
              filter={filter}
              onFilterChange={setFilter}
              selectedId={selectedId}
              onSelect={handleCardClick}
            />
            <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-xs text-slate-400">
              从左侧选择一条任务查看详情
            </div>
          </>
        ) : (
          <>
            <TaskList
              items={items}
              filter={filter}
              onFilterChange={setFilter}
              selectedId={selectedId}
              onSelect={handleCardClick}
            />
            <TaskDetailPanel
              item={selectedItem}
              onTransition={handleTransition}
            />
          </>
        )}
      </section>
    </main>
  );
}
