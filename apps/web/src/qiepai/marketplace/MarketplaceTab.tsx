// qiepai · Marketplace 顶层 tab (Phase ❹)
//
// 布局:
//   - header (标题 + mock badge + 立即刷新 + last refresh + error count + "+ 上传模板" 按钮)
//   - 主体: TemplateGrid
//   - 详情 modal: 卡片点击打开
//   - 上传 modal: 顶部按钮打开
//
// 数据: GET /api/qiepai/marketplace/templates, 失败 fallback MOCK_TEMPLATES
// 详情 fetch: GET /api/qiepai/marketplace/templates/{id}, 失败 fallback MOCK_TEMPLATES + MOCK_RATINGS
// Copy: POST /api/qiepai/marketplace/templates/{id}/copy, 失败 mock fallback (生成 mock-emp + 跳转)
// Rate: POST /api/qiepai/marketplace/templates/{id}/ratings, 失败 mock fallback (本地添加)
// Upload: POST /api/qiepai/marketplace/templates, 失败 mock fallback (本地 prepend)
//
// 当前 user_id: 用 window.localStorage CLIENT_USER_ID (跟 App.tsx 的 clientUserId 一致),
// 拿不到 fallback "anonymous" (保持可评).

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiGet, apiPost } from "../../lib/api";

import { TemplateDetailModal } from "./TemplateDetailModal";
import { TemplateGrid } from "./TemplateGrid";
import { UploadTemplateModal } from "./UploadTemplateModal";
import { MOCK_RATINGS, MOCK_TEMPLATES } from "./mockData";
import type {
  MarketplaceTemplate,
  TemplateCopyResponse,
  TemplateCreatePayload,
  TemplateRating,
  TemplateRatePayload,
  TemplatesListResponse,
} from "./types";

export interface MarketplaceTabProps {
  /** Copy 成功后跳转 employees tab (新 employee id 用于高亮) */
  onSwitchToEmployees: (newEmployeeId: string) => void;
}

const AUTO_REFRESH_MS: number | null = null;

function readClientUserId(): string {
  try {
    // 跟 App.tsx 的 CLIENT_USER_ID_KEY = "opentalking-client-user-id" 对齐
    const raw = window.localStorage.getItem("opentalking-client-user-id");
    return raw ?? "anonymous";
  } catch {
    return "anonymous";
  }
}

export default function MarketplaceTab({
  onSwitchToEmployees,
}: MarketplaceTabProps): ReactNode {
  const [templates, setTemplates] = useState<MarketplaceTemplate[] | null>(
    null,
  );
  const [templatesTotal, setTemplatesTotal] = useState<number>(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MarketplaceTemplate | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<boolean>(false);
  const [ratings, setRatings] = useState<TemplateRating[]>([]);
  const [detailOpen, setDetailOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [copying, setCopying] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);
  const [isMock, setIsMock] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<string>("anonymous");

  useEffect(() => {
    setCurrentUserId(readClientUserId());
  }, []);

  /** GET /api/qiepai/marketplace/templates, 失败 fallback MOCK_TEMPLATES
   *  后端真接口返 {items: Template[], total, limit, offset} (Phase ❹),
   *  列表条目**不**含 payload/data_source/as_of — 详情用 selectedId 单独 fetch */
  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<TemplatesListResponse>(
        "/qiepai/marketplace/templates",
      );
      if (!data || !Array.isArray(data.items)) {
        throw new Error("Expected {items: MarketplaceTemplate[], total: number}");
      }
      setTemplates(data.items);
      setTemplatesTotal(typeof data.total === "number" ? data.total : data.items.length);
      setIsMock(false);
      setErrorCount(0);
    } catch {
      setTemplates(MOCK_TEMPLATES);
      setTemplatesTotal(MOCK_TEMPLATES.length);
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

  /** 选中模板后 fetch ratings, 失败 fallback MOCK_RATINGS[id] */
  const loadRatings = useCallback(async (templateId: string) => {
    try {
      const response = await apiGet<{ items: TemplateRating[]; total: number }>(
        `/qiepai/marketplace/templates/${encodeURIComponent(templateId)}/ratings`,
      );
      if (!Array.isArray(response.items)) {
        throw new Error("Expected {items: TemplateRating[], total: number}");
      }
      setRatings(response.items);
    } catch {
      // 后端 stub → fallback mock
      setRatings(MOCK_RATINGS[templateId] ?? []);
    }
  }, []);

  // selectedId 变化时 fetch 详情 + ratings
  // 详情: GET /templates/{id} (含完整 payload);list 接口不返 payload
  // ratings: GET /templates/{id}/ratings (❹ v1 backend 仅上 POST,GET 触发 405 → fallback mock)
  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setDetailError(false);
      setRatings([]);
      return;
    }
    setDetailLoading(true);
    setDetailError(false);
    setDetail(null);
    apiGet<MarketplaceTemplate>(
      `/qiepai/marketplace/templates/${encodeURIComponent(selectedId)}`,
    )
      .then((d) => {
        setDetail(d);
        setDetailError(false);
      })
      .catch(() => {
        setDetail(null);
        setDetailError(true);
      })
      .finally(() => {
        setDetailLoading(false);
      });
    void loadRatings(selectedId);
  }, [selectedId, loadRatings]);

  /** 卡片点击: 打开 detail modal */
  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setDetailOpen(true);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setDetailOpen(false);
    setSelectedId(null);
  }, []);

  /**
   * Copy 流程:
   * 1) 乐观更新 templates (use_count +1)
   * 2) POST /copy, 失败 fallback mock (生成 mock-emp-{ts})
   * 3) success → 跳 employees tab
   */
  const handleCopy = useCallback(
    async (template: MarketplaceTemplate): Promise<boolean> => {
      if (copying) return false;
      setCopying(true);

      // 1) 乐观更新 use_count
      let previousTemplates: MarketplaceTemplate[] | null = null;
      setTemplates((prev) => {
        if (prev === null) return prev;
        previousTemplates = prev;
        return prev.map((t) =>
          t.id === template.id ? { ...t, use_count: t.use_count + 1 } : t,
        );
      });

      try {
        let copyResponse: TemplateCopyResponse;
        try {
          copyResponse = await apiPost<TemplateCopyResponse>(
            `/qiepai/marketplace/templates/${encodeURIComponent(template.id)}/copy`,
            {},
          );
        } catch {
          // 后端 stub → mock 返回 (生成 fake employee id, 走 employees tab 跳转)
          copyResponse = {
            copy_id: `mock-copy-${Date.now()}`,
            template_id: template.id,
            target_employee_id: `mock-emp-${Date.now().toString(36)}`,
            target_employee_display_name: `${template.name} (副本)`,
            status: "success",
          };
        }
        // 关闭 modal + 跳转 employees tab
        setDetailOpen(false);
        setSelectedId(null);
        onSwitchToEmployees(copyResponse.target_employee_id);
        return true;
      } catch (err) {
        // rollback 乐观更新
        if (previousTemplates !== null) {
          setTemplates(previousTemplates);
        }
        console.warn("[MarketplaceTab] copy failed:", err);
        return false;
      } finally {
        setCopying(false);
      }
    },
    [copying, onSwitchToEmployees],
  );

  /**
   * Rate 流程:
   * 1) 乐观更新本地 ratings (覆盖同 user_id)
   * 2) POST /ratings, 失败 mock fallback (保持本地更新)
   * 3) success → 刷新 templates 平均分 (本地)
   */
  const handleRate = useCallback(
    async (
      templateId: string,
      rating: number,
      comment: string,
    ): Promise<boolean> => {
      const trimmedComment = comment.trim().length > 0 ? comment.trim() : null;
      const optimisticId = `rt-mock-${Date.now()}`;
      const now = new Date().toISOString();

      // 1) 乐观更新 ratings: 过滤同 user_id, 添加新条目
      setRatings((prev) => {
        const filtered = prev.filter((r) => r.user_id !== currentUserId);
        return [
          ...filtered,
          {
            id: optimisticId,
            template_id: templateId,
            user_id: currentUserId,
            rating,
            comment: trimmedComment,
            created_at: now,
          },
        ];
      });

      // 2) 同步更新 templates 的 rating_avg / rating_count
      setTemplates((prev) => {
        if (prev === null) return prev;
        return prev.map((t) => {
          if (t.id !== templateId) return t;
          // 重新计算平均分 (排除之前 user 的评分, 加上新的)
          const currentRating = ratings.find(
            (r) => r.user_id === currentUserId && r.template_id === templateId,
          );
          const totalCount = currentRating
            ? t.rating_count
            : t.rating_count + 1;
          const totalSum = currentRating
            ? t.rating_avg * t.rating_count - currentRating.rating + rating
            : t.rating_avg * t.rating_count + rating;
          const newAvg = totalCount > 0 ? totalSum / totalCount : rating;
          return {
            ...t,
            rating_avg: Number(newAvg.toFixed(2)),
            rating_count: totalCount,
          };
        });
      });

      // 3) 尝试 POST, 失败 mock fallback (本地数据已更新, 不再 rollback)
      try {
        const payload: TemplateRatePayload = {
          rating,
          comment: trimmedComment,
        };
        try {
          await apiPost<TemplateRating>(
            `/qiepai/marketplace/templates/${encodeURIComponent(templateId)}/ratings`,
            payload,
          );
        } catch {
          // 后端 stub → 静默 (本地数据已保留)
          console.warn(
            "[MarketplaceTab] POST /ratings failed, keeping local optimistic update",
          );
        }
        return true;
      } catch (err) {
        console.warn("[MarketplaceTab] handleRate outer failed:", err);
        return false;
      }
    },
    [currentUserId, ratings],
  );

  /**
   * Upload 流程:
   * 1) POST /templates
   * 2) success: prepend 到 templates
   * 3) failure: mock fallback (生成 mock id, prepend 到 templates)
   */
  const handleUpload = useCallback(
    async (payload: TemplateCreatePayload): Promise<boolean> => {
      try {
        let created: MarketplaceTemplate | null = null;
        try {
          const response = await apiPost<{ item: MarketplaceTemplate }>(
            "/qiepai/marketplace/templates",
            payload,
          );
          if (response && response.item && typeof response.item.id === "string") {
            created = response.item;
          }
        } catch {
          // 后端 stub → mock 创建
          created = {
            id: `mock-tpl-${Date.now().toString(36)}`,
            name: payload.name,
            description: payload.description,
            category: payload.category,
            industry: payload.industry,
            tags: payload.tags,
            source: "user",
            use_count: 0,
            rating_avg: 0,
            rating_count: 0,
            payload: payload.payload,
            created_by: currentUserId,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            data_source: "mock://marketplace/templates/v1 (本地新建)",
            as_of: new Date().toISOString(),
          };
        }
        if (created === null) return false;
        setTemplates((prev) =>
          prev === null ? [created] : [created, ...prev],
        );
        setUploadOpen(false);
        return true;
      } catch (err) {
        console.warn("[MarketplaceTab] upload failed:", err);
        return false;
      }
    },
    [currentUserId],
  );

  // 详情 modal 用 GET /templates/{id} 拿到的完整 template (含 payload),
  // 不用 list 条目 (list 不含 payload,会渲染成空 JSON)
  const selectedTemplate = detail;

  return (
    <main
      className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4"
      data-testid="marketplace-tab"
    >
      {/* header */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">
            qiepai · Marketplace
          </p>
          <h1 className="text-base font-semibold text-slate-950">
            场景模板 Marketplace
          </h1>
          {templatesTotal > 0 ? (
            <p className="mt-0.5 text-[10px] text-slate-500">
              共 {templatesTotal} 个模板
              {templates !== null && templates.length !== templatesTotal
                ? ` · 当前显示 ${templates.length} 个`
                : ""}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
          {isMock ? (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700"
              title="后端 /qiepai/marketplace/* 尚未实装, 当前显示前端 mock 数据"
              data-testid="marketplace-mock-badge"
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
            {errorCount === 0 ? "数据源 OK" : `${errorCount} 个 endpoint 异常`}
          </span>
          <span>
            手动刷新 · 上次{" "}
            {lastRefresh.toLocaleTimeString("zh-CN", { hour12: false })}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700"
            data-testid="marketplace-refresh"
          >
            立即刷新
          </button>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="rounded-lg border border-cyan-600 bg-cyan-600 px-3 py-1.5 font-semibold text-white transition hover:bg-cyan-700"
            data-testid="marketplace-upload-button"
          >
            + 上传模板
          </button>
        </div>
      </section>

      {/* 主体: TemplateGrid */}
      <TemplateGrid templates={templates} onSelect={handleSelect} />

      {/* 详情 modal — 始终渲染 detailOpen 状态,内部按 loading/error/ok 三态展示 */}
      {detailOpen ? (
        <TemplateDetailModal
          template={selectedTemplate}
          loading={detailLoading}
          error={detailError}
          ratings={ratings}
          copying={copying}
          currentUserId={currentUserId}
          onClose={handleCloseDetail}
          onCopy={handleCopy}
          onRate={handleRate}
        />
      ) : null}

      {/* 上传 modal */}
      {uploadOpen ? (
        <UploadTemplateModal
          onClose={() => setUploadOpen(false)}
          onSubmit={handleUpload}
        />
      ) : null}
    </main>
  );
}