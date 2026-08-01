import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const backendPort = process.env.VITE_BACKEND_PORT ?? "8000";
const repoRoot = fileURLToPath(new URL("../../", import.meta.url));
const allowedHosts = [".pod.compshare.cn"];
const apiProxy = {
  target: `http://127.0.0.1:${backendPort}`,
  changeOrigin: true,
  ws: true,
  // Backend mounts qiepai/agent routers under /api/* (see apps/unified/main.py
  // line 340/351: include_router(..., prefix="/api")). The original upstream
  // strip-`/api` rewrite made /api/qiepai/* requests become /qiepai/* after
  // the proxy hop — backend only knows /api/qiepai/* and returns 404. Keep
  // the full path so the proxy is a transparent tunnel.
  rewrite: (p: string) => p,
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
