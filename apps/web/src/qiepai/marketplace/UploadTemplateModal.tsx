// qiepai · 上传新场景模板 Modal (Phase ❹ admin)
//
// 字段: name (required) + description + category (5 select) + industry + tags (逗号分隔) + payload (textarea, 校验 JSON)
// 校验: name 非空 + payload 是 valid JSON
// 提交: 父组件 onSubmit 实际调 POST, 失败返回 false (UI 显示 error 不关 modal)
// 单租户 demo: 不引入 role 系统, 默认所有用户都能上传 (跟 ❸/❹ 其他面板一致)

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  TEMPLATE_CATEGORY_LABEL,
  type TemplateCategory,
  type TemplateCreatePayload,
} from "./types";

export interface UploadTemplateModalProps {
  onClose: () => void;
  /** 父组件尝试 POST, 失败返回 false (UI 不关 modal + 显示 error) */
  onSubmit: (payload: TemplateCreatePayload) => Promise<boolean>;
}

interface FormState {
  name: string;
  description: string;
  category: TemplateCategory;
  industry: string;
  tagsText: string;
  payloadText: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  category: "customer_service",
  industry: "",
  tagsText: "",
  payloadText: "{\n  \n}",
};

const CATEGORY_OPTIONS: TemplateCategory[] = [
  "customer_service",
  "sales",
  "finance",
  "hr",
  "ops",
];

export function UploadTemplateModal({
  onClose,
  onSubmit,
}: UploadTemplateModalProps): ReactNode {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Esc 关闭 (submitting 中不响应)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  const handleSubmit = async () => {
    setError(null);

    // 校验 name
    if (form.name.trim().length === 0) {
      setError("模板名称不能为空");
      return;
    }

    // 校验 payload JSON
    let payload: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(form.payloadText);
      if (
        parsed === null ||
        typeof parsed !== "object" ||
        Array.isArray(parsed)
      ) {
        setError("payload 必须是 JSON 对象 (不能是数组或 null)");
        return;
      }
      payload = parsed as Record<string, unknown>;
    } catch (err) {
      setError(
        `payload 不是有效 JSON: ${err instanceof Error ? err.message : String(err)}`,
      );
      return;
    }

    // 校验 tags
    const tags = form.tagsText
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    setSubmitting(true);
    try {
      const createPayload: TemplateCreatePayload = {
        name: form.name.trim(),
        description: form.description.trim(),
        category: form.category,
        industry:
          form.industry.trim().length > 0 ? form.industry.trim() : null,
        tags,
        payload,
      };
      const ok = await onSubmit(createPayload);
      if (!ok) {
        setError("上传失败, 请稍后重试");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
      onClick={() => {
        if (!submitting) onClose();
      }}
      data-testid="upload-template-modal-backdrop"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="upload-template-modal"
      >
        {/* header */}
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div>
            <p className="text-[10px] font-medium text-slate-500">
              Marketplace · 上传模板
            </p>
            <h2 className="mt-0.5 text-base font-semibold text-slate-950">
              上传新场景模板
            </h2>
            <p className="mt-1 text-xs text-slate-600">
              填写模板元数据 + 完整 payload JSON (avatar / voice / LLM / prompts / 知识库 等)。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="shrink-0 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="关闭"
            title="关闭 (Esc)"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </header>

        {/* body */}
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          <div>
            <label
              htmlFor="upload-name"
              className="mb-1 block text-[10px] font-medium text-slate-600"
            >
              模板名称 <span className="text-red-500">*</span>
            </label>
            <input
              id="upload-name"
              type="text"
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              placeholder="例如: 客服智能坐席 v2"
              disabled={submitting}
              className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
              data-testid="upload-name-input"
            />
          </div>

          <div>
            <label
              htmlFor="upload-description"
              className="mb-1 block text-[10px] font-medium text-slate-600"
            >
              简介
            </label>
            <textarea
              id="upload-description"
              value={form.description}
              onChange={(e) =>
                setForm((p) => ({ ...p, description: e.target.value }))
              }
              rows={2}
              disabled={submitting}
              placeholder="一句话说明模板适用场景"
              className="w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs leading-relaxed text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
              data-testid="upload-description-input"
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="upload-category"
                className="mb-1 block text-[10px] font-medium text-slate-600"
              >
                分类 <span className="text-red-500">*</span>
              </label>
              <select
                id="upload-category"
                value={form.category}
                onChange={(e) =>
                  setForm((p) => ({
                    ...p,
                    category: e.target.value as TemplateCategory,
                  }))
                }
                disabled={submitting}
                className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                data-testid="upload-category-select"
              >
                {CATEGORY_OPTIONS.map((cat) => (
                  <option key={cat} value={cat}>
                    {TEMPLATE_CATEGORY_LABEL[cat]}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="upload-industry"
                className="mb-1 block text-[10px] font-medium text-slate-600"
              >
                行业 (可选)
              </label>
              <input
                id="upload-industry"
                type="text"
                value={form.industry}
                onChange={(e) =>
                  setForm((p) => ({ ...p, industry: e.target.value }))
                }
                placeholder="例如: 电商零售"
                disabled={submitting}
                className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
                data-testid="upload-industry-input"
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="upload-tags"
              className="mb-1 block text-[10px] font-medium text-slate-600"
            >
              标签 (英文逗号分隔)
            </label>
            <input
              id="upload-tags"
              type="text"
              value={form.tagsText}
              onChange={(e) =>
                setForm((p) => ({ ...p, tagsText: e.target.value }))
              }
              placeholder="例如: 客服, 工单, 自助"
              disabled={submitting}
              className="w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
              data-testid="upload-tags-input"
            />
          </div>

          <div>
            <label
              htmlFor="upload-payload"
              className="mb-1 block text-[10px] font-medium text-slate-600"
            >
              payload (JSON) <span className="text-red-500">*</span>
            </label>
            <textarea
              id="upload-payload"
              value={form.payloadText}
              onChange={(e) =>
                setForm((p) => ({ ...p, payloadText: e.target.value }))
              }
              rows={8}
              disabled={submitting}
              placeholder='{"avatar_id":"...", "voice_id":"...", "system_prompt":"..."}'
              className="w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1.5 font-mono text-[10px] leading-relaxed text-slate-700 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
              data-testid="upload-payload-input"
            />
            <p className="mt-1 text-[10px] text-slate-400">
              必须为合法 JSON 对象, 包含 avatar_id / voice_id / tts_provider / llm_provider / system_prompt 等。
            </p>
          </div>

          {error !== null ? (
            <p
              className="rounded border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700"
              data-testid="upload-error"
            >
              {error}
            </p>
          ) : null}
        </div>

        {/* footer */}
        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 p-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting}
            className="rounded-md border border-cyan-600 bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="upload-submit"
          >
            {submitting ? "上传中..." : "上传模板"}
          </button>
        </footer>
      </div>
    </div>
  );
}