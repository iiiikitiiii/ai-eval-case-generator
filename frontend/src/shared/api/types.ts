/** Mirrors backend/app/schemas/case.py — keep the two in sync by hand for
 * now; a generated client is worth it once the schema churns less. */

export type CaseStatus =
  | "queued"
  | "extracting"
  | "reviewing_flags"
  | "staging"
  | "mock_review"
  | "cutpoint_review"
  | "exported"
  | "blocked";

export type WorkshopStep = "up" | "a" | "b" | "d" | "f" | "out";

export interface CaseListItem {
  id: string;
  case_no: string;
  alias: string | null;
  patient_meta: Record<string, unknown>;
  status: CaseStatus;
  current_step: WorkshopStep;
  created_at: string;
  updated_at: string;
  document_count: number;
  pending_flag_count: number;
  todo_label: string;
  last_failed_step: string | null;
}

export interface DocumentOut {
  id: string;
  seq: number;
  content_type: string | null;
  document_type: string | null;
  exam_time: string | null;
  report_time: string | null;
  exam_items: string[];
  structured_info: Record<string, unknown>;
  core_abnormality: string | null;
  ocr_full_text: string | null;
  confidence: { ocr?: number; fields?: number };
}

export interface ReviewFlagOut {
  id: string;
  type: string;
  field: string;
  detail: string;
  why: string | null;
  involved_docs: number[];
  severity: "high" | "medium" | "low";
  decision: "confirm" | "ignore" | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface StageMapOut {
  id: string;
  stage_code: string;
  status: "covered" | "not_applicable" | "real_gap" | "uncovered";
  docs: number[];
  reason: string | null;
}

export interface BoundaryDecisionOut {
  id: string;
  doc_seq: number;
  assigned_stage: string;
  alternative_stage: string;
  rule_applied: string | null;
  rationale: string | null;
  needs_human: boolean;
  resolved_stage: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface PersonaFieldOut {
  id: string;
  field: string;
  value: string;
  source: number[];
  flag: string | null;
}

export interface MockEntryOut {
  id: string;
  stage_code: string;
  date_label: string | null;
  title: string;
  desc: string | null;
  clinical_basis: string;
  strength: "strong" | "medium" | "weak";
  disclaimer: string | null;
  decision: "pass" | "reject" | null;
  decided_by: string | null;
  decided_at: string | null;
}

export type PersonaCode = "patient_low" | "patient_high" | "family_low" | "family_high";

export interface TurnOut {
  round: number;
  messages: string[];
  note: string | null;
}

export interface QueryVariantOut {
  id: string;
  persona_id: string;
  persona_code: PersonaCode | null;
  persona_name: string | null;
  persona_note: string;
  turns: TurnOut[];
  behavior_logic: string;
  selected: boolean;
}

export interface QueryOut {
  id: string;
  scenario_type: string;
  text: string;
  test_direction: string | null;
  test_background: string | null;
  test_image_seqs: number[];
  test_image_note: string | null;
  expected_answer_points: string[];
  red_line_watch: string[];
  has_standard_card: boolean;
  decision: "accept" | "reject";
  reject_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  variants: QueryVariantOut[];
}

export interface CutpointOut {
  id: string;
  stage_code: string;
  type_code: string | null; // 已弃用字段（C1-C6 分类），新裂点不再有
  provenance: "real" | "mock";
  anchor: { after?: string; before?: string; time?: string };
  known_set: string[];
  unknown_set: string[];
  judgment: string | null;
  validity_check: { askable?: boolean; gradeable?: boolean; discriminating?: boolean };
  enabled: boolean;
  queries: QueryOut[];
}

export interface CaseDetail extends CaseListItem {
  documents: DocumentOut[];
  flags: ReviewFlagOut[];
  stage_map: StageMapOut[];
  boundary_decisions: BoundaryDecisionOut[];
  persona: PersonaFieldOut[];
  mocks: MockEntryOut[];
  cutpoints: CutpointOut[];
}

export type PipelineRunStatus = "queued" | "running" | "succeeded" | "failed";

export interface PipelineRunOut {
  id: string;
  agent_code: string;
  agent_version_label: string | null;
  status: PipelineRunStatus;
  error: string | null;
  output_ref: Record<string, unknown> | null;
  progress_note: string | null;
  token_usage: { provider: string; model: string; prompt_tokens: number | null; completion_tokens: number | null; total_tokens: number | null } | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  duration_seconds: number | null;
}

/** Mirrors backend/app/schemas/agent.py */

export type AgentCode = "S0" | "A" | "B" | "C" | "D" | "F";
export type AgentKind = "prereq" | "extract" | "fabricate" | "generate";
export type AgentVersionStatus = "draft" | "published" | "archived";

export interface AgentOut {
  id: string;
  code: AgentCode;
  name: string;
  kind: AgentKind;
  oneline: string | null;
  published_version_label: string | null;
}

export interface AgentVersionOut {
  id: string;
  version_label: string;
  prompt_text: string;
  out_schema: Record<string, unknown> | null;
  checks: string[];
  status: AgentVersionStatus;
  created_by: string | null;
  created_at: string;
  published_at: string | null;
}

export interface ScenarioTypeOut {
  id: string;
  code: string;
  scenario_number: number | null;
  name: string;
  axis: "peer" | "patient";
  journey_stages: string[];
  feature_scenario: string | null;
  description: string | null;
  source: string | null;
  consultation_volume: number | null;
  active: boolean;
  has_standard_card: boolean;
}

export interface UserPersonaOut {
  id: string;
  code: PersonaCode;
  role: "patient" | "family";
  cognition: "low" | "high";
  name: string;
  behavior_guideline: string;
  active: boolean;
}

/** Mirrors backend/app/schemas/board.py */

export interface BoardCaseItem {
  id: string;
  case_no: string;
  patient_meta: Record<string, unknown>;
  status: CaseStatus;
  current_step: WorkshopStep;
  pending_flag_count: number;
  accepted_query_count: number;
  updated_at: string;
}

export interface BoardTestCaseItem {
  case_id: string;
  case_no: string;
  cutpoint_id: string;
  query_id: string;
  journey_stage: string;
  cutpoint_type: string | null;
  provenance: "real" | "mock";
  scenario_type: string;
  scenario_name: string | null;
  query_text: string;
  decision: string;
  reject_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface CoverageCell {
  journey_stage: string;
  scenario_type: string;
  scenario_name: string;
  accepted_real: number;
  accepted_mock: number;
}

export interface QualitySummary {
  case_count: number;
  flags_total: number;
  flags_by_severity: Record<string, number>;
  flags_confirmed: number;
  flags_ignored: number;
  mocks_total: number;
  mocks_passed: number;
  mocks_rejected: number;
  pipeline_runs_total: number;
  pipeline_runs_failed: number;
  pipeline_failures_by_agent: Record<string, number>;
  accepted_test_case_count: number;
  token_usage_total: number;
  token_usage_run_count: number;
  token_usage_by_provider: Record<string, number>;
  token_usage_by_agent: Record<string, number>;
}
