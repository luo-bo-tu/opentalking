// qiepai · 数字员工顶层组件 (Phase ❷-6)
//
// 布局:
//   - header + 左 50% EmployeeList + 右 50% EmployeeDetailPanel
//   - 右栏: PersonaLink + LifecycleStateMachine + RevisionList + PublishButton
// 数据:
//   - /qiepai/employees 返回 {items, total}, 失败 fallback MOCK_EMPLOYEES
//   - /qiepai/employees/{id}/revisions 按需懒加载 (selectedId 变化时拉), 失败 fallback MOCK_REVISIONS
// 状态转换: 乐观更新 + POST /qiepai/employees/{id}/publish, 失败 rollback (同 DecisionsTab / TasksTab 模式)

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { apiGet, buildApiUrl } from "../../lib/api";

import { EmployeeList } from "./EmployeeList";
import type { EmployeeStatusFilter } from "./EmployeeList";
import { LifecycleStateMachine } from "./LifecycleStateMachine";
import { PersonaLink } from "./PersonaLink";
import { PublishButton } from "./PublishButton";
import { RevisionList } from "./RevisionList";
import {
  LIFECYCLE_LABEL,
  LIFECYCLE_TONE,
} from "./types";
import type {
  Employee,
  EmployeeRevision,
  EmployeeStatus,
} from "./types";
import { MOCK_EMPLOYEES, MOCK_REVISIONS } from "./mockData";

const AUTO_REFRESH_MS: number | null = null;

export default function EmployeesTab(): ReactNode {
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [revisions, setRevisions] = useState<EmployeeRevision[] | null>(null);
  const [filter, setFilter] = useState<EmployeeStatusFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);
  const [isMock, setIsMock] = useState(false);

  const refresh = useCallback(async () => {
    try {
      // 后端 list endpoint 返回 {items: Employee[], total: number}
      const response = await apiGet<{ items: Employee[]; total: number }>(
        "/qiepai/employees",
      );
      // 防御: 后端 stub 阶段返回 {status:"stub"},无 items 字段
      if (!Array.isArray(response.items)) {
        throw new Error("Expected {items: Employee[], total: number}");
      }
      const data = response.items;
      setEmployees(data);
      setIsMock(false);
      setErrorCount(0);
    } catch {
      setEmployees(MOCK_EMPLOYEES);
      setIsMock(true);
      setErrorCount(1);
    }
    // 注意: revisions 不再在 refresh 里全量拉, 改为按需懒加载
    // (避免调用不存在的 /qiepai/employees/revisions 永远 404)
    setLastRefresh(new Date());
  }, []);

  // 按需懒加载 revisions: selectedId 变化时拉该 employee 的 revisions
  useEffect(() => {
    if (selectedId === null) {
      setRevisions([]);
      return;
    }
    let cancelled = false;
    void apiGet<{ items: EmployeeRevision[]; total: number }>(
      `/qiepai/employees/${encodeURIComponent(selectedId)}/revisions`,
    )
      .then((response) => {
        if (cancelled) return;
        setRevisions(response.items);
      })
      .catch(() => {
        if (cancelled) return;
        // 后端 404 / 网络错 → fallback MOCK_REVISIONS (mock 全集, useMemo 在前端 filter)
        setRevisions(MOCK_REVISIONS);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  useEffect(() => {
    void refresh();
    if (AUTO_REFRESH_MS !== null) {
      const id = window.setInterval(() => void refresh(), AUTO_REFRESH_MS);
      return () => window.clearInterval(id);
    }
    return undefined;
  }, [refresh]);

  // 默认选中第一条
  useEffect(() => {
    if (employees === null || selectedId !== null) return;
    const filtered =
      filter === "all"
        ? employees
        : employees.filter((e) => e.status === filter);
    if (filtered.length > 0) {
      setSelectedId(filtered[0].id);
    } else if (employees.length > 0) {
      setSelectedId(employees[0].id);
    }
  }, [employees, filter, selectedId]);

  const handleCardClick = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  // 乐观更新 employee 状态 + 真正调后端 POST /publish, 失败 rollback
  const handleTransition = useCallback(
    async (next: EmployeeStatus): Promise<void> => {
      if (selectedId === null) return;
      const employeeId = selectedId;
      // 1) 乐观更新本地 (UI 立即响应)
      const originalStatus =
        employees?.find((e) => e.id === employeeId)?.status ?? null;
      setEmployees((prev) => {
        if (prev === null) return prev;
        return prev.map((e) =>
          e.id === employeeId ? { ...e, status: next } : e,
        );
      });
      // 2) 真正调后端 POST /qiepai/employees/{id}/publish
      try {
        const res = await fetch(
          buildApiUrl(
            `/qiepai/employees/${encodeURIComponent(employeeId)}/publish`,
          ),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // 后端目前不接受 target_status (按当前 status 推 1 步),
            // 但保留 body 以便未来后端扩展支持跳跃目标
            body: JSON.stringify({ target_status: next }),
          },
        );
        if (!res.ok) {
          throw new Error(
            `POST /qiepai/employees/${employeeId}/publish failed: HTTP ${res.status}`,
          );
        }
      } catch (err) {
        // 3) 失败 rollback (404 / 422 readiness / 409 跳跃 / 网络错都 rollback)
        setEmployees((prev) => {
          if (prev === null || originalStatus === null) return prev;
          return prev.map((e) =>
            e.id === employeeId ? { ...e, status: originalStatus } : e,
          );
        });
        console.error("[EmployeesTab] handleTransition failed:", err);
      }
    },
    [selectedId, employees],
  );

  const selectedEmployee = employees?.find((e) => e.id === selectedId) ?? null;

  // 该 employee 的 revisions
  const selectedRevisions = useMemo(() => {
    if (selectedEmployee === null || revisions === null) return [];
    return revisions.filter((r) => r.employee_id === selectedEmployee.id);
  }, [selectedEmployee, revisions]);

  const currentRevision = useMemo(() => {
    if (selectedEmployee === null || selectedEmployee.current_revision_id === null) {
      return null;
    }
    return (
      selectedRevisions.find((r) => r.id === selectedEmployee.current_revision_id) ??
      null
    );
  }, [selectedEmployee, selectedRevisions]);

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4">
      {/* header */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">qiepai · Employees</p>
          <h1 className="text-base font-semibold text-slate-950">数字员工</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          {isMock ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
              title="后端 /qiepai/employees 尚未实装, 当前显示前端 mock 数据"
              data-testid="employees-mock-badge"
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
        {employees === null ? (
          <div className="col-span-full rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs text-amber-700">
            数字员工数据加载中...
          </div>
        ) : (
          <>
            <EmployeeList
              items={employees}
              filter={filter}
              onFilterChange={setFilter}
              selectedId={selectedId}
              onSelect={handleCardClick}
            />
            <div
              className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto"
              data-testid="employee-detail"
            >
              {selectedEmployee === null ? (
                <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white text-xs text-slate-400">
                  从左侧选择一位数字员工查看详情
                </div>
              ) : (
                <>
                  {/* header */}
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[10px] font-medium text-slate-500">
                          数字员工 · {selectedEmployee.id}
                        </p>
                        <h2 className="mt-0.5 truncate text-base font-semibold text-slate-950">
                          {selectedEmployee.display_name}
                        </h2>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {selectedEmployee.role}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${LIFECYCLE_TONE[selectedEmployee.status]}`}
                      >
                        {LIFECYCLE_LABEL[selectedEmployee.status]}
                      </span>
                    </div>
                    <p className="mt-2 truncate font-mono text-[10px] text-slate-400" title={selectedEmployee.source}>
                      source · {selectedEmployee.source}
                    </p>
                  </div>

                  {/* PersonaLink */}
                  <PersonaLink personaId={selectedEmployee.persona_id} />

                  {/* LifecycleStateMachine */}
                  <LifecycleStateMachine
                    current={selectedEmployee.status}
                    onTransition={handleTransition}
                  />

                  {/* PublishButton (仅 ready/published/suspended 显示) */}
                  <PublishButton
                    currentStatus={selectedEmployee.status}
                    currentRevision={currentRevision}
                    onPublish={handleTransition}
                  />

                  {/* RevisionList */}
                  {revisions === null ? (
                    <p className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
                      Revision 数据加载中...
                    </p>
                  ) : (
                    <RevisionList
                      revisions={selectedRevisions}
                      currentRevisionId={selectedEmployee.current_revision_id}
                    />
                  )}
                </>
              )}
            </div>
          </>
        )}
      </section>
    </main>
  );
}
