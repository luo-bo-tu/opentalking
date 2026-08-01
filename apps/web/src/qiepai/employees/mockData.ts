// qiepai · 数字员工 mock 数据 (Phase ❷-6 前端先行)
//
// 后端 /qiepai/employees 还在 ❷-1 stub, 前端先用这份 mock 渲染真实 UI 结构.
// 数据语义合理 (4 个不同 lifecycle 状态 + 1 个含完整 revision 历史),
// 后端就绪后所有 fetch 自动切真, 这份文件作废.
//
// 数据来源全部标 source=mock://..., UI 顶部显式标 "mock 模式".

import type { Employee, EmployeeRevision, PersonaRef } from "./types";

/** Mock persona 列表 (供 PersonaLink 显示名字, 也供 unlink 用) */
export const MOCK_PERSONAS: PersonaRef[] = [
  { id: "persona-cfo-001", display_name: "财务人格 - 沉稳大叔" },
  { id: "persona-sales-002", display_name: "销售人格 - 干练女性" },
  { id: "persona-legal-003", display_name: "法务人格 - 严谨律师" },
  { id: "persona-hr-004", display_name: "HR 人格 - 暖心姐姐" },
  { id: "persona-cs-005", display_name: "客服人格 - 活泼妹妹" },
];

/** Mock revision 列表 (4 个 revision 集中在 emp-cfo-001, 展示完整历史) */
export const MOCK_REVISIONS: EmployeeRevision[] = [
  // ===== emp-cfo-001: 4 个 revision (rev 1/2/3/4, 各 readiness 不同) =====
  {
    id: "rev-cfo-001-1",
    employee_id: "emp-cfo-001",
    revision_number: 1,
    workspace_file_hash: "sha256:0001c1...d4e5",
    config_snapshot: {
      persona_template: "persona-cfo-template-v1",
      voice_id: "voice-cfo-male-deep",
      knowledge_bases: [],
    },
    publish_state: "draft",
    readiness_p0: false,
    readiness_p1: false,
    sync_state: "pending",
    readiness_reason: "persona 未绑定 / knowledge_bases 未配置",
    created_at: "2026-07-10T09:00:00+08:00",
  },
  {
    id: "rev-cfo-001-2",
    employee_id: "emp-cfo-001",
    revision_number: 2,
    workspace_file_hash: "sha256:0001c2...a8b1",
    config_snapshot: {
      persona_template: "persona-cfo-template-v1",
      voice_id: "voice-cfo-male-deep",
      knowledge_bases: ["kb-financial-report"],
    },
    publish_state: "configuring",
    readiness_p0: true,
    readiness_p1: false,
    sync_state: "in_sync",
    readiness_reason: null,
    created_at: "2026-07-15T14:30:00+08:00",
  },
  {
    id: "rev-cfo-001-3",
    employee_id: "emp-cfo-001",
    revision_number: 3,
    workspace_file_hash: "sha256:0001c3...f9c2",
    config_snapshot: {
      persona_template: "persona-cfo-template-v2",
      voice_id: "voice-cfo-male-deep",
      knowledge_bases: ["kb-financial-report", "kb-ar-aging"],
      skills: ["compute_ar_aging", "generate_dunning_letter"],
    },
    publish_state: "ready",
    readiness_p0: true,
    readiness_p1: false,
    sync_state: "in_sync",
    readiness_reason: "P1 验收测试未通过 (4/8 场景)",
    created_at: "2026-07-20T11:00:00+08:00",
  },
  {
    id: "rev-cfo-001-4",
    employee_id: "emp-cfo-001",
    revision_number: 4,
    workspace_file_hash: "sha256:0001c4...7e8d",
    config_snapshot: {
      persona_template: "persona-cfo-template-v2",
      voice_id: "voice-cfo-male-deep",
      knowledge_bases: ["kb-financial-report", "kb-ar-aging", "kb-cashflow"],
      skills: ["compute_ar_aging", "generate_dunning_letter", "forecast_cashflow"],
    },
    publish_state: "published",
    readiness_p0: true,
    readiness_p1: true,
    sync_state: "in_sync",
    readiness_reason: null,
    created_at: "2026-07-28T16:20:00+08:00",
  },

  // ===== emp-sales-002: 1 个 revision (published, 已配 persona) =====
  {
    id: "rev-sales-002-1",
    employee_id: "emp-sales-002",
    revision_number: 1,
    workspace_file_hash: "sha256:0002c1...b3c4",
    config_snapshot: {
      persona_template: "persona-sales-template-v1",
      voice_id: "voice-sales-female",
      knowledge_bases: ["kb-customer-list", "kb-product-pricing"],
    },
    publish_state: "published",
    readiness_p0: true,
    readiness_p1: true,
    sync_state: "in_sync",
    readiness_reason: null,
    created_at: "2026-07-05T10:00:00+08:00",
  },

  // ===== emp-legal-003: 1 个 revision (configuring, readiness_p0 通过) =====
  {
    id: "rev-legal-003-1",
    employee_id: "emp-legal-003",
    revision_number: 1,
    workspace_file_hash: "sha256:0003c1...a1b2",
    config_snapshot: {
      persona_template: "persona-legal-template-v1",
      voice_id: "voice-legal-neutral",
      knowledge_bases: ["kb-legal-template"],
    },
    publish_state: "configuring",
    readiness_p0: true,
    readiness_p1: false,
    sync_state: "in_sync",
    readiness_reason: null,
    created_at: "2026-07-22T13:00:00+08:00",
  },

  // ===== emp-cs-005: 1 个 revision (draft, 刚起步) =====
  {
    id: "rev-cs-005-1",
    employee_id: "emp-cs-005",
    revision_number: 1,
    workspace_file_hash: "sha256:0005c1...c5d6",
    config_snapshot: {
      persona_template: "persona-cs-template-v1",
      voice_id: null,
      knowledge_bases: [],
    },
    publish_state: "draft",
    readiness_p0: false,
    readiness_p1: false,
    sync_state: "pending",
    readiness_reason: "voice_id 未选 / knowledge_bases 空",
    created_at: "2026-07-29T17:00:00+08:00",
  },

  // ===== emp-hr-004: 1 个 revision (suspended, 暂停运营) =====
  {
    id: "rev-hr-004-1",
    employee_id: "emp-hr-004",
    revision_number: 1,
    workspace_file_hash: "sha256:0004c1...e7f8",
    config_snapshot: {
      persona_template: "persona-hr-template-v1",
      voice_id: "voice-hr-warm",
      knowledge_bases: ["kb-hr-policy"],
    },
    publish_state: "suspended",
    readiness_p0: true,
    readiness_p1: true,
    sync_state: "drifted",
    readiness_reason: null,
    created_at: "2026-06-15T09:00:00+08:00",
  },
];

/** Mock 数字员工列表 (5 个, 覆盖不同 lifecycle 状态) */
export const MOCK_EMPLOYEES: Employee[] = [
  {
    id: "emp-cfo-001",
    display_name: "财务数字员工 - 招财",
    role: "财务数字员工",
    status: "published",
    current_revision_id: "rev-cfo-001-4",
    persona_id: "persona-cfo-001",
    source: "mock://employees/v1",
    created_at: "2026-07-10T09:00:00+08:00",
  },
  {
    id: "emp-sales-002",
    display_name: "销售数字员工 - 小销",
    role: "销售数字员工",
    status: "published",
    current_revision_id: "rev-sales-002-1",
    persona_id: "persona-sales-002",
    source: "mock://employees/v1",
    created_at: "2026-07-05T10:00:00+08:00",
  },
  {
    id: "emp-legal-003",
    display_name: "法务数字员工 - 律动",
    role: "法务数字员工",
    status: "configuring",
    current_revision_id: "rev-legal-003-1",
    persona_id: null,
    source: "mock://employees/v1",
    created_at: "2026-07-22T13:00:00+08:00",
  },
  {
    id: "emp-hr-004",
    display_name: "HR 数字员工 - 暖姐",
    role: "HR 数字员工",
    status: "suspended",
    current_revision_id: "rev-hr-004-1",
    persona_id: "persona-hr-004",
    source: "mock://employees/v1",
    created_at: "2026-06-15T09:00:00+08:00",
  },
  {
    id: "emp-cs-005",
    display_name: "客服数字员工 - 萌妹",
    role: "客服数字员工",
    status: "draft",
    current_revision_id: "rev-cs-005-1",
    persona_id: null,
    source: "mock://employees/v1",
    created_at: "2026-07-29T17:00:00+08:00",
  },
];
