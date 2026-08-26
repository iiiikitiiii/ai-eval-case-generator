import { api } from "./client";
import type { AgentOut, AgentVersionOut, ScenarioTypeOut, UserPersonaOut } from "./types";

export function listAgents() {
  return api.get<AgentOut[]>("/agents");
}

export function listVersions(code: string) {
  return api.get<AgentVersionOut[]>(`/agents/${code}/versions`);
}

export function createVersion(code: string, promptText: string, checks: string[], outSchema: Record<string, unknown> | null) {
  return api.post<AgentVersionOut>(`/agents/${code}/versions`, { prompt_text: promptText, checks, out_schema: outSchema });
}

export function publishVersion(code: string, versionId: string) {
  return api.post<AgentVersionOut>(`/agents/${code}/versions/${versionId}/publish`);
}

export function listScenarioTypes() {
  return api.get<ScenarioTypeOut[]>("/scenario-types");
}

export interface ScenarioTypeInput {
  code: string;
  name: string;
  axis: "peer" | "patient";
  journey_stages: string[];
  feature_scenario: string | null;
  description: string | null;
}

export function createScenarioType(data: ScenarioTypeInput) {
  return api.post<ScenarioTypeOut>("/scenario-types", data);
}

export function updateScenarioType(id: string, data: Partial<ScenarioTypeInput & { active: boolean }>) {
  return api.patch<ScenarioTypeOut>(`/scenario-types/${id}`, data);
}

export function listPersonas() {
  return api.get<UserPersonaOut[]>("/personas");
}

export interface UserPersonaInput {
  code: string;
  role: "patient" | "family";
  cognition: "low" | "high";
  name: string;
  behavior_guideline: string;
}

export function createPersona(data: UserPersonaInput) {
  return api.post<UserPersonaOut>("/personas", data);
}

export function updatePersona(id: string, data: Partial<Omit<UserPersonaInput, "code" | "role" | "cognition">> & { active?: boolean }) {
  return api.patch<UserPersonaOut>(`/personas/${id}`, data);
}

export interface SandboxResult {
  result: Record<string, unknown>;
}

/** 同步阻塞——F 类调用观察到跑过 4 分钟，这是工程师主动点了等结果的场景。 */
export function sandboxRun(code: string, caseId: string, promptText: string, outSchema: Record<string, unknown> | null) {
  return api.post<SandboxResult>(`/agents/${code}/sandbox`, { case_id: caseId, prompt_text: promptText, out_schema: outSchema });
}

export interface Assertion {
  description: string;
  check: "no_exception" | "count_gte" | "count_eq" | "field_eq" | "field_contains";
  path: (string | number)[];
  expected?: unknown;
}

export interface RegressionCaseOut {
  id: string;
  name: string;
  agent_code: string;
  golden_case_id: string | null;
  golden_case_no: string | null;
  assertions: Assertion[];
  active: boolean;
}

export function listRegressionCases(code: string) {
  return api.get<RegressionCaseOut[]>(`/agents/${code}/regression-cases`);
}

export function createRegressionCase(code: string, name: string, goldenCaseId: string, assertions: Assertion[]) {
  return api.post<RegressionCaseOut>(`/agents/${code}/regression-cases`, {
    name,
    agent_code: code,
    golden_case_id: goldenCaseId,
    assertions,
  });
}

export interface AssertionResult {
  description: string;
  passed: boolean;
  detail: string;
}

export interface RegressionRunOut {
  id: string;
  regression_case_id: string;
  regression_case_name: string | null;
  status: "pass" | "fail";
  details: { assertions?: AssertionResult[]; error?: string };
  run_at: string;
}

export function runRegression(code: string, versionId: string) {
  return api.post<RegressionRunOut[]>(`/agents/${code}/versions/${versionId}/regression-run`);
}

export function listRegressionRuns(code: string, versionId: string) {
  return api.get<RegressionRunOut[]>(`/agents/${code}/versions/${versionId}/regression-runs`);
}
