import { api, downloadFile } from "./client";
import type { BoardCaseItem, BoardTestCaseItem, CoverageCell, QualitySummary } from "./types";

export function getBoardCases() {
  return api.get<BoardCaseItem[]>("/board/cases");
}

export interface TestCaseFilters {
  scenario_type?: string;
  cutpoint_type?: string;
  journey_stage?: string;
  provenance?: string;
  decision?: string;
}

export function getBoardTestCases(filters: TestCaseFilters = {}) {
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]).toString();
  return api.get<BoardTestCaseItem[]>(`/board/testcases${qs ? `?${qs}` : ""}`);
}

export function batchDecideQueries(queryIds: string[], decision: "accept" | "reject", reason?: string) {
  return api.patch<{ decided_count: number }>("/board/queries/batch-decide", {
    query_ids: queryIds, decision, reason: reason || undefined,
  });
}

export function getCoverageMatrix() {
  return api.get<CoverageCell[]>("/board/coverage");
}

export function getQualitySummary() {
  return api.get<QualitySummary>("/board/quality");
}

/** caseIds 为空 = 不按病例限定；filters 为空 = 不额外筛选（decision 后端
 * 默认按 accept，除非这里显式传别的值）。病例看板批量导出只传 caseIds，
 * 用例库 tab「导出当前筛选结果」只传 filters，两边共用同一个函数。 */
export function downloadBoardExport(caseIds: string[], format: "xlsx" | "json" | "zip", filters: TestCaseFilters = {}) {
  const qs = new URLSearchParams({ format, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) });
  if (caseIds.length > 0) qs.set("case_ids", caseIds.join(","));
  return downloadFile(`/board/export?${qs.toString()}`, `批量导出-测试用例.${format}`);
}
