// qiepai · 右侧 AI 决策助手 (Phase ❷-5)
//
// 4 层分层渲染: fact / inference / suggestion / unknown
// 数据来源: 优先 fetch /qiepai/decisions/{id}/ai-suggestion, 失败 fallback MOCK_AI_RESPONSES
// suggestion 层提供刷新按钮 (不缓存, 用户触发)

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiGet } from "../../lib/api";

import { MOCK_AI_RESPONSES } from "./mockData";
import type { AIResponse, DecisionItem } from "./types";
import { AssistantLayer } from "./AssistantLayer";

export interface RightAssistantProps {
  /** 当前选中的决策项; null 时显示空态 */
  selected: DecisionItem | null;
}

export function RightAssistant({ selected }: RightAssistantProps): ReactNode {
  const [response, setResponse] = useState<AIResponse | null>(
    selected?.ai_suggestion ?? null,
  );
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isMock, setIsMock] = useState(false);

  const loadInitial = useCallback(async (id: string) => {
    setError(null);
    try {
      const data = await apiGet<AIResponse>(
        `/qiepai/decisions/${encodeURIComponent(id)}/ai-suggestion`,
      );
      if (
        data === null ||
        typeof data !== "object" ||
        !Array.isArray(data.fact)
      ) {
        throw new Error("Invalid AIResponse shape");
      }
      setResponse(data);
      setIsMock(false);
    } catch {
      // 后端 stub / 网络错 → fallback mock
      const mock = MOCK_AI_RESPONSES[id];
      setResponse(
        mock ?? {
          fact: [],
          inference: [],
          suggestion: [],
          unknown: [
            {
              text: "AI 助手尚未生成建议, 请点击下方「刷新建议」按钮。",
              need: "AI 助手接入",
            },
          ],
        },
      );
      setIsMock(true);
    }
  }, []);

  // 选中项变化时重置
  useEffect(() => {
    if (selected === null) {
      setResponse(null);
      setError(null);
      setIsMock(false);
      return;
    }
    // 优先用决策项自带的 ai_suggestion (后端可能在 PATCH 时返回)
    if (selected.ai_suggestion !== null) {
      setResponse(selected.ai_suggestion);
      setIsMock(false);
      return;
    }
    void loadInitial(selected.id);
  }, [selected, loadInitial]);

  const handleRefresh = useCallback(async () => {
    if (selected === null) return;
    setRefreshing(true);
    setError(null);
    try {
      const data = await apiGet<AIResponse>(
        `/qiepai/decisions/${encodeURIComponent(selected.id)}/ai-suggestion`,
      );
      if (
        data === null ||
        typeof data !== "object" ||
        !Array.isArray(data.fact)
      ) {
        throw new Error("Invalid AIResponse shape");
      }
      setResponse(data);
      setIsMock(false);
    } catch {
      // 刷新也 fallback mock
      const mock = MOCK_AI_RESPONSES[selected.id];
      setResponse(
        mock ?? {
          fact: [],
          inference: [],
          suggestion: [],
          unknown: [
            {
              text: "AI 助手暂无数据, 请稍后再试或补充决策项信息。",
            },
          ],
        },
      );
      setIsMock(true);
    } finally {
      setRefreshing(false);
    }
  }, [selected]);

  // 空态: 未选决策
  if (selected === null) {
    return (
      <aside
        className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white p-6 text-center"
        data-testid="right-assistant-empty"
      >
        <span className="text-2xl">🤖</span>
        <p className="mt-2 text-sm font-medium text-slate-700">AI 决策助手</p>
        <p className="mt-1 text-xs text-slate-500">
          从左侧选择一条决策项, 这里会显示 4 层 AI 分析
        </p>
        <p className="mt-3 text-[10px] text-slate-400">
          fact / inference / suggestion / unknown
        </p>
      </aside>
    );
  }

  // 加载中
  if (response === null) {
    return (
      <aside className="flex h-full flex-col rounded-lg border border-slate-200 bg-white p-4">
        <p className="text-xs text-slate-500">加载 AI 建议中...</p>
      </aside>
    );
  }

  return (
    <aside
      className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4"
      data-testid="right-assistant"
    >
      <header>
        <p className="text-[10px] font-medium text-slate-500">AI 决策助手</p>
        <h2 className="mt-0.5 text-sm font-semibold text-slate-950">
          {selected.title}
        </h2>
        {isMock ? (
          <p
            className="mt-1 inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
            title="后端 ai-suggestion 接口尚未实装, 当前显示前端 mock 数据"
          >
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
            mock 模式
          </p>
        ) : null}
      </header>

      {error !== null ? (
        <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700">
          {error}
        </p>
      ) : null}

      {/* 4 层: 仅渲染 count > 0 的 */}
      <AssistantLayer kind="fact" count={response.fact.length}>
        {response.fact.map((item, idx) => (
          <div
            key={`fact-${idx}`}
            className="rounded border border-blue-100 bg-white px-2 py-1.5"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] font-medium text-slate-700">
                {item.label}
              </span>
              <span className="text-xs font-bold tabular-nums text-slate-950">
                {item.value === null
                  ? "数据暂不可用"
                  : typeof item.value === "number"
                    ? item.value.toLocaleString("zh-CN")
                    : String(item.value)}
                {item.unit ? (
                  <span className="ml-0.5 text-[10px] font-normal text-slate-500">
                    {item.unit}
                  </span>
                ) : null}
              </span>
            </div>
            <p
              className="mt-0.5 truncate font-mono text-[9px] text-slate-400"
              title={item.source}
            >
              {item.source}
            </p>
          </div>
        ))}
      </AssistantLayer>

      <AssistantLayer kind="inference" count={response.inference.length}>
        {response.inference.map((item, idx) => (
          <div
            key={`inf-${idx}`}
            className="rounded border border-purple-100 bg-white px-2 py-1.5"
          >
            <p className="text-[11px] leading-relaxed text-slate-700">
              {item.text}
            </p>
            <div className="mt-1 flex items-center gap-1.5">
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-purple-100">
                <div
                  className="h-full bg-purple-500"
                  style={{ width: `${Math.round(item.confidence * 100)}%` }}
                />
              </div>
              <span className="text-[10px] font-medium tabular-nums text-purple-700">
                {Math.round(item.confidence * 100)}%
              </span>
            </div>
          </div>
        ))}
      </AssistantLayer>

      <AssistantLayer
        kind="suggestion"
        count={response.suggestion.length}
        onRefresh={() => void handleRefresh()}
        refreshing={refreshing}
      >
        {response.suggestion.map((item, idx) => (
          <div
            key={`sug-${idx}`}
            className="rounded border border-emerald-100 bg-white px-2 py-1.5"
          >
            <p className="text-[11px] leading-relaxed text-slate-700">
              {item.text}
            </p>
            <p className="mt-0.5 text-[10px] text-emerald-700">
              责任人 · {item.owner}
            </p>
          </div>
        ))}
      </AssistantLayer>

      <AssistantLayer kind="unknown" count={response.unknown.length}>
        {response.unknown.map((item, idx) => (
          <div
            key={`unk-${idx}`}
            className="rounded border border-amber-100 bg-white px-2 py-1.5"
          >
            <p className="text-[11px] leading-relaxed text-slate-700">
              {item.text}
            </p>
            {item.need ? (
              <p className="mt-0.5 text-[10px] text-amber-700">
                需补充 · {item.need}
              </p>
            ) : null}
          </div>
        ))}
      </AssistantLayer>

      <footer className="mt-auto border-t border-slate-100 pt-2 text-[10px] text-slate-400">
        suggestion 层由 LLM 生成, 不缓存, 点击刷新重新生成
      </footer>
    </aside>
  );
}
