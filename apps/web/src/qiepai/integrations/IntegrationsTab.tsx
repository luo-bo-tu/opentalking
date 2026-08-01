// qiepai · 集成顶层组件 (Phase ❸-1)
//
// 本期只接入飞书机器人 (FeishuBotPanel).
// 后续阶段 (❸-2 飞书日历 / ❸-3 webhook / ❸-4 IM) 各自加 Panel, 在此顶层 tab 里并列.
//
// 当前顶层: 单 Panel 全宽渲染 (跟 CockpitTab / DecisionsTab 同布局)
// 未来扩展: 左侧 sidebar 切换不同集成 (飞书 / 钉钉 / Slack), 右侧 Panel

import type { ReactNode } from "react";

import { FeishuBotPanel } from "./FeishuBotPanel";

export default function IntegrationsTab(): ReactNode {
  return (
    <main className="flex min-h-0 flex-1 flex-col bg-slate-100">
      <FeishuBotPanel />
    </main>
  );
}