import { useCallback, useEffect, useState } from "react";
import { apiGet, buildApiUrl } from "../lib/api";
import type { MemoryLibrary, PersonaSummary } from "../types";

// qiepai v0.2: 运行监控页面
// - 6 张状态卡片，每 5 秒自动刷新
// - 数据来源：/health, /runtime-config, /memory/libraries, /personas, /queue/status

type HealthSnapshot = {
  ok: boolean;
  version?: string;
};

type RuntimeSnapshot = {
  llm: { base_url?: string; model?: string; api_key_set?: boolean };
  stt: { provider?: string; model?: string; model_dir?: string };
  tts: { provider?: string; voice?: string; api_key_set?: boolean };
  mem0?: { llm: { api_key_set?: boolean }; embedder: { api_key_set?: boolean } };
};

type QueueSnapshot = {
  slot_occupied?: boolean;
  queue_size?: number;
};

type AvatarSnapshot = {
  id: string;
  name?: string;
  model_type?: string;
  width?: number;
  height?: number;
};

type Tone = "ok" | "warn" | "err";

const REFRESH_MS = 5000;

function toneFor(ok: boolean, warning = false): Tone {
  if (!ok) return "err";
  return warning ? "warn" : "ok";
}

const TONE_CLASSES: Record<Tone, string> = {
  ok: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  err: "border-red-500/40 bg-red-500/10 text-red-300",
};

const TONE_LABEL: Record<Tone, string> = {
  ok: "正常",
  warn: "警告",
  err: "异常",
};

function formatNumber(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  return String(n);
}

function truncate(s: string | undefined, max = 38): string {
  if (!s) return "—";
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

export function Monitoring() {
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [runtime, setRuntime] = useState<RuntimeSnapshot | null>(null);
  const [memories, setMemories] = useState<MemoryLibrary[]>([]);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [avatars, setAvatars] = useState<AvatarSnapshot[]>([]);
  const [queue, setQueue] = useState<QueueSnapshot | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [errorCount, setErrorCount] = useState(0);
  const [sttWarming, setSttWarming] = useState(false);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      apiGet<HealthSnapshot>(buildApiUrl("/health")),
      apiGet<RuntimeSnapshot>(buildApiUrl("/runtime-config")),
      apiGet<{ items: MemoryLibrary[] }>(buildApiUrl("/memory/libraries?profile_id=default&character_id=qiepai-penguin")),
      apiGet<{ personas: PersonaSummary[] }>(buildApiUrl("/personas")),
      apiGet<{ items: AvatarSnapshot[] }>(buildApiUrl("/avatars")),
      apiGet<QueueSnapshot>(buildApiUrl("/queue/status")),
    ]);
    let errs = 0;
    if (results[0].status === "fulfilled") setHealth({ ok: true, ...(results[0].value as any) });
    else { setHealth({ ok: false }); errs++; }
    if (results[1].status === "fulfilled") setRuntime(results[1].value as RuntimeSnapshot);
    else errs++;
    if (results[2].status === "fulfilled") setMemories(((results[2].value as any).items) ?? []);
    else { setMemories([]); errs++; }
    if (results[3].status === "fulfilled") setPersonas(((results[3].value as any).personas) ?? []);
    else { setPersonas([]); errs++; }
    if (results[4].status === "fulfilled") {
      const items = ((results[4].value as any).items) ?? [];
      setAvatars(items);
    } else { setAvatars([]); errs++; }
    if (results[5].status === "fulfilled") setQueue(results[5].value as QueueSnapshot);
    else { setQueue(null); errs++; }
    setErrorCount(errs);
    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const qiepaiAvatar = avatars.find((a) => a.id === "qiepai-penguin");
  const memoryTotal = memories.reduce((s, m) => s + (m.memory_count ?? 0), 0);
  const mem0Ready = Boolean(runtime?.mem0?.llm.api_key_set && runtime?.mem0?.embedder.api_key_set);
  const sttProvider = runtime?.stt?.provider ?? "";
  const localStt = ["sensevoice", "funasr", "sherpa_onnx"].includes(sttProvider);
  const sttReady = localStt || Boolean(runtime?.stt?.api_key_set);
  const ttsReady = runtime?.tts?.provider === "edge"
    || runtime?.tts?.provider === "local_cosyvoice"
    || runtime?.tts?.provider === "indextts"
    || runtime?.tts?.provider === "local_indextts"
    || runtime?.tts?.provider === "omnirt_indextts"
    || runtime?.tts?.provider === "local_f5_tts"
    || Boolean(runtime?.tts?.api_key_set);
  const llmReady = Boolean(runtime?.llm?.api_key_set);

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-slate-100 p-4">
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div>
          <p className="text-xs font-medium text-slate-500">Monitoring</p>
          <h1 className="text-base font-semibold text-slate-950">运行监控</h1>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${errorCount === 0 ? "bg-emerald-500" : "bg-amber-500"}`} />
            {errorCount === 0 ? "全部 endpoint 健康" : `${errorCount} 个 endpoint 异常`}
          </span>
          <span>每 5 秒自动刷新 · 上次 {lastRefresh.toLocaleTimeString("zh-CN", { hour12: false })}</span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-300 hover:text-cyan-700"
          >
            立即刷新
          </button>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {/* 后端健康 */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">后端健康</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(health?.ok ?? false)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${health?.ok ? "bg-emerald-500" : "bg-red-500"}`} />
              {health?.ok ? "运行中" : "不可达"}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">状态</dt><dd className="font-medium text-slate-900">{health?.ok ? "200 OK" : "无响应"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">错误数</dt><dd className="font-medium text-slate-900">{errorCount} / 6</dd></div>
          </dl>
        </article>

        {/* STT 状态 */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">语音识别 (STT)</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(sttReady, sttWarming)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${sttReady ? (sttWarming ? "bg-amber-500" : "bg-emerald-500") : "bg-red-500"}`} />
              {sttReady ? (sttWarming ? "预热中" : TONE_LABEL.ok) : TONE_LABEL.err}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">Provider</dt><dd className="font-medium text-slate-900">{sttProvider || "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Model</dt><dd className="truncate font-medium text-slate-900" title={runtime?.stt?.model}>{truncate(runtime?.stt?.model, 26)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Model Dir</dt><dd className="truncate font-medium text-slate-900" title={runtime?.stt?.model_dir}>{truncate(runtime?.stt?.model_dir, 26)}</dd></div>
          </dl>
        </article>

        {/* TTS 状态 */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">语音合成 (TTS)</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(ttsReady)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${ttsReady ? "bg-emerald-500" : "bg-red-500"}`} />
              {ttsReady ? "就绪" : "未配置"}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">Provider</dt><dd className="font-medium text-slate-900">{runtime?.tts?.provider ?? "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Voice</dt><dd className="truncate font-medium text-slate-900" title={runtime?.tts?.voice}>{truncate(runtime?.tts?.voice, 28)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">API Key</dt><dd className="font-medium text-slate-900">{runtime?.tts?.api_key_set ? "已设置" : "—"}</dd></div>
          </dl>
        </article>

        {/* LLM */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">大模型 (LLM)</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(llmReady)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${llmReady ? "bg-emerald-500" : "bg-red-500"}`} />
              {llmReady ? "已配置" : "未配置"}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">Base URL</dt><dd className="truncate font-medium text-slate-900" title={runtime?.llm?.base_url}>{truncate(runtime?.llm?.base_url, 26)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Model</dt><dd className="truncate font-medium text-slate-900" title={runtime?.llm?.model}>{truncate(runtime?.llm?.model, 26)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">API Key</dt><dd className="font-medium text-slate-900">{runtime?.llm?.api_key_set ? "已设置" : "—"}</dd></div>
          </dl>
        </article>

        {/* 记忆库 */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">记忆库 (Mem0)</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(mem0Ready, memories.length === 0)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${mem0Ready ? (memories.length === 0 ? "bg-amber-500" : "bg-emerald-500") : "bg-red-500"}`} />
              {mem0Ready ? (memories.length === 0 ? "无库" : "活跃") : "未配置"}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">库数</dt><dd className="font-medium text-slate-900">{formatNumber(memories.length)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">总条目</dt><dd className="font-medium text-slate-900">{formatNumber(memoryTotal)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">LLM / Embedder</dt><dd className="font-medium text-slate-900">{runtime?.mem0?.llm.api_key_set ? "✓" : "✗"} / {runtime?.mem0?.embedder.api_key_set ? "✓" : "✗"}</dd></div>
          </dl>
        </article>

        {/* Persona */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">Persona 人设</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(personas.length > 0)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${personas.length > 0 ? "bg-emerald-500" : "bg-amber-500"}`} />
              {personas.length} 个
            </span>
          </header>
          <ul className="space-y-1 text-xs">
            {personas.slice(0, 4).map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 rounded-md border border-slate-100 bg-slate-50 px-2 py-1">
                <span className="truncate font-medium text-slate-900" title={p.name}>{p.name ?? p.id}</span>
                <span className="truncate text-slate-500" title={p.id}>{p.id}</span>
              </li>
            ))}
            {personas.length > 4 ? <li className="text-center text-slate-400">…还有 {personas.length - 4} 个</li> : null}
            {personas.length === 0 ? <li className="text-center text-slate-400">暂无 persona</li> : null}
          </ul>
        </article>

        {/* 数字人形象 */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">数字人形象</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(avatars.length > 0 && !!qiepaiAvatar)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${qiepaiAvatar ? "bg-emerald-500" : "bg-amber-500"}`} />
              {qiepaiAvatar ? "qiepai-penguin 就绪" : "未加载"}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">总形象</dt><dd className="font-medium text-slate-900">{formatNumber(avatars.length)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">企鹅派</dt><dd className="truncate font-medium text-slate-900">{qiepaiAvatar?.name ?? "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">分辨率</dt><dd className="font-medium text-slate-900">{qiepaiAvatar ? `${qiepaiAvatar.width ?? "?"} × ${qiepaiAvatar.height ?? "?"}` : "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">驱动模型</dt><dd className="font-medium text-slate-900">{qiepaiAvatar?.model_type ?? "—"}</dd></div>
          </dl>
        </article>

        {/* 队列 */}
        <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-950">实时队列</h2>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[toneFor(queue?.slot_occupied !== undefined, (queue?.queue_size ?? 0) > 0)]}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${queue?.slot_occupied ? "bg-amber-500" : "bg-emerald-500"}`} />
              {queue?.slot_occupied ? "槽位占用" : "空闲"}
            </span>
          </header>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">队列长度</dt><dd className="font-medium text-slate-900">{formatNumber(queue?.queue_size)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">槽位状态</dt><dd className="font-medium text-slate-900">{queue?.slot_occupied ? "占用中" : "空闲"}</dd></div>
          </dl>
        </article>
      </section>
    </main>
  );
}