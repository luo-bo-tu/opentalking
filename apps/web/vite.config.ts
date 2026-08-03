import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// qiepai v0.2.1 fix: 默认 proxy 后端端口从上游 OpenTalking 的 8000 改到 qiepai 默认 8001
// (scripts/quickstart/start_opentalking.sh 默认启 8001, 上游 fork 自 OpenTalking 时配的是 8000)。
// 仍允许 VITE_BACKEND_PORT env var 覆盖 (start_frontend.sh 会显式 export)。
const backendPort = process.env.VITE_BACKEND_PORT ?? "8001";
const repoRoot = fileURLToPath(new URL("../../", import.meta.url));
const allowedHosts = [".pod.compshare.cn"];
// qiepai v0.2.1 fix: 前端 lib/api.ts 用 API_BASE="api",所有请求都加 /api 前缀,
// 但后端多数路由是裸路径 (/personas /memory/* /runtime-config /avatars/* /sessions/* 等),
// 只有 /api/qiepai/* 和 /api/agent/* (agent.router 二次挂载) mount 在 /api 下。
// 上游默认 transparent tunnel 让 /api/personas 直接打到后端 /api/personas (404),
// 现在改成: /api/qiepai/* 和 /api/agent/* 保留 /api,其他 /api/* strip 前缀。
const stripApiRewrite = (p: string): string => {
  if (p.startsWith("/api/qiepai") || p.startsWith("/api/agent")) {
    return p;
  }
  return p.replace(/^\/api/, "");
};
const apiProxy = {
  target: `http://127.0.0.1:${backendPort}`,
  changeOrigin: true,
  ws: true,
  rewrite: stripApiRewrite,
  // SSE (EventSource) through proxy: avoid buffering / stale Content-Length
  configure(proxy) {
    proxy.on("proxyRes", (proxyRes, req) => {
      const url = req.url ?? "";
      if (url.includes("/events")) {
        delete proxyRes.headers["content-length"];
        proxyRes.headers["cache-control"] = "no-cache, no-transform";
        proxyRes.headers["x-accel-buffering"] = "no";
      }
    });
  },
};

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts,
    fs: {
      allow: [repoRoot],
    },
    proxy: {
      "/api": apiProxy,
    },
  },
  preview: {
    port: 5173,
    allowedHosts,
    proxy: {
      "/api": apiProxy,
    },
  },
});
