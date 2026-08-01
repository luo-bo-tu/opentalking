// qiepai · 决策中心顶层组件 (Phase ❷-5)
//
// 布局: header + 左 60% DecisionList + 右 40% RightAssistant
// 数据: 优先 fetch /qiepai/decisions, 失败 fallback MOCK_DECISIONS
// 决策提交: 弹 DecisionDetailModal, PATCH + 本地乐观更新

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiGet } from "../../lib/api";

import { DecisionDetailModal } from "./DecisionDetailModal";
import {
  DecisionList,
  type StatusFilter,
} from "./DecisionList";
import { MOCK_DECISIONS } from "./mockData";
import { RightAssistant } from "./RightAssistant";
import type { DecisionItem, DecisionPatchPayload } from "./types";

const AUTO_REFRESH_MS: number | null = null;

export default function DecisionsTab(): ReactNode {
  const [items, setItems] = useState<DecisionItem[] | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);
  const [isMock, setIsMock] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<DecisionItem[]>("/qiepai/decisions");
      if (!Array.isArray(data)) {
        // 后端 stub 返回 {"status":"stub", ...} (object), 走 fallback
        throw new Error("Expected DecisionItem[]");
      }
      setItems(data);
      setIsMock(false);
      setErrorCount(0);
    } catch {
      // 后端 stub / 网络错 → fallback mock
      setItems(MOCK_DECISIONS);
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
    setModalOpen(true);
  }, []);

  const handleSubmitDecision = useCallback(
    async (id: string, patch: DecisionPatchPayload): Promise<void> => {
      // 本地乐观更新 (无论后端是否成功)
      setItems((prev) => {
        if (prev === null) return prev;
        return prev.map((item) =>
          item.id === id
            ? {
                ...item,
                status: patch.status,
                decision_text: patch.decision_text,
                decided_at:
                  patch.status === "pending"
                    ? null
                    : new Date().toISOString(),
              }
            : item,
        );
      });
    },
    [],
  );

  const selectedItem =
    items?.find((i) => i.id === selectedId) ?? null;

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4">
      {/* header */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">qiepai · Decisions</p>
          <h1 className="text-base font-semibold text-slate-950">决策中心</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          {isMock ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
              title="后端 /qiepai/decisions 尚未实装, 当前显示前端 mock 数据"
              data-testid="decisions-mock-badge"
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

      {/* 2-column: 60% / 40% */}
      <section className="grid min-h-[600px] flex-1 grid-cols-1 gap-4 lg:grid-cols-[3fr_2fr]">
        {items === null ? (
          <div className="col-span-full rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-700">
            决策项数据加载中...
          </div>
        ) : (
          <>
            <DecisionList
              items={items}
              filter={filter}
              onFilterChange={setFilter}
              selectedId={selectedId}
              onSelect={handleCardClick}
            />
            <RightAssistant selected={selectedItem} />
          </>
        )}
      </section>

      {/* Modal */}
      {modalOpen && selectedItem !== null ? (
        <DecisionDetailModal
          item={selectedItem}
          onClose={() => setModalOpen(false)}
          onSubmit={handleSubmitDecision}
        />
      ) : null}
    </main>
  );
}
