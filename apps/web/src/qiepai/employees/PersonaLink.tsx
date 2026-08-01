// qiepai · persona 1:1 关联 UI (Phase ❷-6)
//
// 显示当前关联的 persona 名字 + unlink 按钮
// 数据来源: 优先 /api/personas 拉真 persona 列表, 失败 fallback MOCK_PERSONAS
// 1:1 关联: 架构 v1.1 § 2 明示 employeeId ≠ agentId ≠ persona_id, 共存

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiGet } from "../../lib/api";

import { MOCK_PERSONAS } from "./mockData";
import type { PersonaRef } from "./types";

export interface PersonaLinkProps {
  /** 当前关联的 persona_id (可为 null 表示未关联) */
  personaId: string | null;
  /** unlink 操作 (前端 display, 实际后端 wire 时再接真) */
  onUnlink?: () => void;
  /** 1:1 冲突提示 (e.g. persona 已被另一员工关联) */
  conflictWarning?: string | null;
}

export function PersonaLink({
  personaId,
  onUnlink,
  conflictWarning,
}: PersonaLinkProps): ReactNode {
  const [persona, setPersona] = useState<PersonaRef | null>(
    personaId === null
      ? null
      : (MOCK_PERSONAS.find((p) => p.id === personaId) ?? {
          id: personaId,
          display_name: personaId,
        }),
  );
  const [isMock, setIsMock] = useState(false);

  // 优先拉真 persona 列表
  useEffect(() => {
    if (personaId === null) {
      setPersona(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const data = await apiGet<{ personas?: Array<{ id: string; display_name?: string; name?: string }> }>(
          "/personas",
        );
        if (cancelled) return;
        if (data && Array.isArray(data.personas)) {
          const found = data.personas.find((p) => p.id === personaId);
          if (found) {
            setPersona({
              id: found.id,
              display_name: found.display_name ?? found.name ?? found.id,
            });
            setIsMock(false);
            return;
          }
        }
        throw new Error("Persona not found in /api/personas");
      } catch {
        if (cancelled) return;
        // Fallback mock
        setPersona(
          MOCK_PERSONAS.find((p) => p.id === personaId) ?? {
            id: personaId,
            display_name: personaId,
          },
        );
        setIsMock(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [personaId]);

  if (personaId === null || persona === null) {
    return (
      <div
        className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-500"
        data-testid="persona-link-empty"
      >
        <p className="font-medium text-slate-700">未关联 persona</p>
        <p className="mt-1 text-[11px] text-slate-400">
          数字员工与 persona 1:1 关联, 发布前需绑定 (架构 § 2)
        </p>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg border border-purple-100 bg-purple-50/60 p-3"
      data-testid="persona-link"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wide text-purple-700">
            关联 Persona (1:1)
          </p>
          <p className="mt-0.5 truncate text-sm font-semibold text-slate-950">
            {persona.display_name}
          </p>
          <p className="mt-0.5 truncate font-mono text-[10px] text-slate-500">
            {persona.id}
          </p>
        </div>
        <button
          type="button"
          onClick={onUnlink}
          disabled={onUnlink === undefined}
          className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-medium text-slate-600 transition hover:border-red-200 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="persona-unlink-button"
          title={
            onUnlink === undefined
              ? "unlink 待后端实装, 当前前端 display only"
              : "解除 persona 1:1 关联"
          }
        >
          解除关联
        </button>
      </div>
      {isMock ? (
        <p className="mt-1 text-[10px] text-amber-700">
          ⚠ mock 模式 (真 persona 列表未拉取到)
        </p>
      ) : null}
      {conflictWarning !== null && conflictWarning !== undefined && conflictWarning.length > 0 ? (
        <p
          className="mt-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-[10px] text-red-700"
          data-testid="persona-conflict-warning"
        >
          ⚠ {conflictWarning}
        </p>
      ) : null}
    </div>
  );
}
