/** @type {import('tailwindcss').Config} */

// qiepai v0.2: 品牌色重映射
// - slate 调色板：50↔950 对调（让现有 `bg-slate-100` 自动显示成深色，`text-slate-900` 显示成浅色）
// - cyan 调色板：替换为 sky 的色阶（呼应 logo 的"蓝色光晕"）
// 现有 41 个 .tsx/.ts 文件不用动，所有 `bg-cyan-*` / `text-cyan-*` / `bg-slate-*` 自动用新色板
const defaultColors = require("tailwindcss/colors");

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        fadeOut: {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(0.95)" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(0)" },
        },
        slideInUp: {
          "0%": { transform: "translateY(100%)" },
          "100%": { transform: "translateY(0)" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
        "fade-out": "fadeOut 0.5s ease-out forwards",
        "slide-up": "slideUp 0.3s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "slide-in-up": "slideInUp 0.3s ease-out",
        "pulse-dot": "pulse-dot 1.5s ease-in-out infinite",
      },
    },
    // qiepai v0.2: 用 theme.colors 完全替换，但保留所有默认色板（emerald/amber/red 等）
    colors: {
      ...defaultColors,
      transparent: "transparent",
      current: "currentColor",
      black: "#000",
      white: "#fff",
      // slate 反转：原 50 是最浅（#f8fafc），现在 50 = 原 950（#020617 最深）
      // 这样现有 bg-slate-100 自动变成深色背景
      slate: {
        50: "#020617",
        100: "#0f172a",
        200: "#1e293b",
        300: "#334155",
        400: "#475569",
        500: "#64748b",
        600: "#94a3b8",
        700: "#cbd5e1",
        800: "#e2e8f0",
        900: "#f1f5f9",
        950: "#f8fafc",
      },
      // cyan → sky 色板（呼应 logo 蓝色光晕）
      cyan: {
        50: "#f0f9ff",
        100: "#e0f2fe",
        200: "#bae6fd",
        300: "#7dd3fc",
        400: "#38bdf8",
        500: "#0ea5e9",
        600: "#0284c7",
        700: "#0369a1",
        800: "#075985",
        900: "#0c4a6e",
        950: "#082f49",
      },
    },
  },
  plugins: [],
};