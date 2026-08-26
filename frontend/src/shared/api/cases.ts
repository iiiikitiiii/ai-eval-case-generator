import { api, ApiError, downloadFile, getAuthToken } from "./client";
import type { CaseDetail, CaseListItem, PipelineRunOut, WorkshopStep } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function listCases(params: { status?: string; search?: string } = {}) {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status_filter", params.status);
  if (params.search) qs.set("search", params.search);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return api.get<CaseListItem[]>(`/cases${suffix}`);
}

export function createCase(patientMeta: Record<string, unknown>, alias?: string) {
  return api.post<CaseDetail>("/cases", { patient_meta: patientMeta, alias: alias || undefined });
}

export function deleteDocument(caseId: string, documentId: string) {
  return api.delete<CaseDetail>(`/cases/${caseId}/documents/${documentId}`);
}

export function getCase(caseId: string) {
  return api.get<CaseDetail>(`/cases/${caseId}`);
}

/** Multipart upload can't go through the JSON `api` client — no
 * Content-Type header here on purpose, the browser sets the multipart
 * boundary itself. */
export async function uploadDocuments(caseId: string, files: File[]): Promise<CaseDetail> {
  const form = new FormData();
  for (const f of files) form.append("files", f);

  const headers = new Headers();
  const token = getAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${BASE_URL}/cases/${caseId}/documents`, { method: "POST", body: form, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? `上传失败（${res.status}）`);
  }
  return res.json();
}

// 五个 run-X 现在都是"排队即返回"（202 + PipelineRunOut，status=queued），
// 真正的执行在 arq worker 里异步跑。调用方要自己 pollRun() 等到终态。
export function runAgentA(caseId: string) {
  return api.post<PipelineRunOut>(`/cases/${caseId}/pipeline/run-a`);
}

export function runAgentB(caseId: string) {
  return api.post<PipelineRunOut>(`/cases/${caseId}/pipeline/run-b`);
}

export function runAgentC(caseId: string) {
  return api.post<PipelineRunOut>(`/cases/${caseId}/pipeline/run-c`);
}

export function runAgentD(caseId: string) {
  return api.post<PipelineRunOut>(`/cases/${caseId}/pipeline/run-d`);
}

export function runAgentF(caseId: string, personaCodes?: string[], scenarioCodes?: string[]) {
  const body: Record<string, string[]> = {};
  if (personaCodes) body.persona_codes = personaCodes;
  if (scenarioCodes) body.scenario_codes = scenarioCodes;
  return api.post<PipelineRunOut>(`/cases/${caseId}/pipeline/run-f`, Object.keys(body).length > 0 ? body : undefined);
}

/** Polls the trace list until this run reaches a terminal state. Every
 * run-X trigger above returns the moment the job is queued, not when it's
 * done — this is what turns that into "wait until it's actually finished"
 * for callers that still want to work that way. */
export async function pollRun(
  caseId: string,
  runId: string,
  opts: { intervalMs?: number; timeoutMs?: number; onTick?: (run: PipelineRunOut) => void } = {},
): Promise<PipelineRunOut> {
  const intervalMs = opts.intervalMs ?? 2000;
  const timeoutMs = opts.timeoutMs ?? 10 * 60 * 1000; // F has run ~4min in practice; leave headroom
  const deadline = Date.now() + timeoutMs;
  while (true) {
    const runs = await getPipelineRuns(caseId);
    const run = runs.find((r) => r.id === runId);
    if (run) {
      opts.onTick?.(run);
      if (run.status === "succeeded" || run.status === "failed") return run;
    }
    if (Date.now() > deadline) throw new ApiError(408, "等待运行结果超时，请稍后在运行记录里查看");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function decideFlag(caseId: string, flagId: string, decision: "confirm" | "ignore") {
  return api.patch(`/cases/${caseId}/flags/${flagId}`, { decision });
}

export function resolveBoundary(caseId: string, decisionId: string, resolvedStage: string) {
  return api.patch(`/cases/${caseId}/boundary/${decisionId}`, { resolved_stage: resolvedStage });
}

export function decideMock(caseId: string, mockId: string, decision: "pass" | "reject") {
  return api.patch(`/cases/${caseId}/mocks/${mockId}`, { decision });
}

export function toggleCutpoint(caseId: string, cutpointId: string, enabled: boolean) {
  return api.patch(`/cases/${caseId}/cutpoints/${cutpointId}`, { enabled });
}

export function decideQuery(caseId: string, queryId: string, decision: "accept" | "reject", reason?: string) {
  return api.patch(`/cases/${caseId}/queries/${queryId}`, { decision, reason: reason || undefined });
}

export function selectVariant(caseId: string, variantId: string, selected: boolean) {
  return api.patch(`/cases/${caseId}/variants/${variantId}`, { selected });
}

/** MinIO never faces the browser directly (see backend/app/core/storage.py),
 * so a plain <img src="..."> can't carry the bearer token. Fetch the bytes
 * ourselves and hand back a blob: URL the caller can drop into <img> —
 * caller owns revoking it (URL.revokeObjectURL) when done. */
export async function fetchDocumentImageUrl(caseId: string, documentId: string): Promise<string> {
  const headers = new Headers();
  const token = getAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${BASE_URL}/cases/${caseId}/documents/${documentId}/image`, { headers });
  if (!res.ok) throw new ApiError(res.status, `图片加载失败（${res.status}）`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export function advanceStep(caseId: string, targetStep: WorkshopStep) {
  return api.post<CaseDetail>(`/cases/${caseId}/advance`, { target_step: targetStep });
}

export function getPipelineRuns(caseId: string) {
  return api.get<PipelineRunOut[]>(`/cases/${caseId}/pipeline/runs`);
}

export interface ExportResult {
  case_no: string;
  test_cases: Record<string, unknown>[];
}

export function exportCase(caseId: string) {
  return api.get<ExportResult>(`/cases/${caseId}/export`);
}

export function downloadCaseExport(caseId: string, caseNo: string, format: "xlsx" | "json" | "zip") {
  return downloadFile(`/cases/${caseId}/export?format=${format}`, `${caseNo}-测试用例.${format}`);
}
