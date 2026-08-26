import { useEffect, useState, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { listScenarioTypes } from "../../shared/api/agents";
import { batchDecideQueries, downloadBoardExport, getBoardCases, getBoardTestCases, getCoverageMatrix, getQualitySummary, type TestCaseFilters } from "../../shared/api/board";
import { getCase } from "../../shared/api/cases";
import { ApiError } from "../../shared/api/client";
import type { BoardCaseItem, BoardTestCaseItem, CaseDetail, CoverageCell, CutpointOut, QualitySummary, QueryOut, ScenarioTypeOut, WorkshopStep } from "../../shared/api/types";
import { Lightbox } from "../../shared/ui/Lightbox";
import { QueryCard } from "../../shared/ui/QueryCard";

const STEPS: { key: WorkshopStep; label: string }[] = [
  { key: "up", label: "导入" },
  { key: "a", label: "核对" },
  { key: "b", label: "阶段裁定" },
  { key: "d", label: "推测抽查" },
  { key: "f", label: "裂点用例" },
  { key: "out", label: "产出" },
];

// 已弃用——C1-C6 是早期版本发明的分类，业务方任何文档里都没有这个概念
// （2026-08 六阶段旅程落地时移除，见 backend/app/db/models/case.py 里
// Cutpoint.type_code 的说明）。只留着给 2026-08 之前生产的历史数据筛选
// 用，新生成的裂点不会再有这个字段。
const CUTPOINT_TYPES = ["C1", "C2", "C3", "C4", "C5", "C6"];
const CUTPOINT_TYPE_LABEL: Record<string, string> = {
  C1: "结果已出·定性未明",
  C2: "确诊已出·分期未定",
  C3: "方案待选",
  C4: "治疗中新症状",
  C5: "随访指标异常",
  C6: "信息本身有缺口",
};

// 业务方场景库真实使用的六阶段旅程，跟病例工坊的 STAGE_LABEL 是同一份数据
// （doc/专病管家测评标准-场景清单+标准.xlsx「整合场景清单 (六阶段)」）。
const JOURNEY_STAGE_CODES = ["J01", "J02", "J03", "J04", "J05", "J06"];
const JOURNEY_STAGE_LABEL: Record<string, string> = {
  J01: "疑诊 / 初筛期",
  J02: "确诊后治疗方案决策期",
  J03: "初诊治疗实施期",
  J04: "复发 / 进展 / 耐药后治疗方案调整",
  J05: "康复随访期",
  J06: "姑息照护期",
};

export function BoardPage() {
  const [tab, setTab] = useState<"cases" | "testcases" | "coverage" | "quality">("cases");
  return (
    <div style={{ padding: "24px 32px 60px" }}>
      <h1 style={{ fontSize: 19, fontWeight: 700, margin: "0 0 4px" }}>用例总览看板</h1>
      <p style={{ fontSize: 12.5, color: "var(--sub)", margin: "0 0 18px" }}>跨病例聚合——所有病例合起来，用例资产够不够、缺在哪、质量稳不稳。</p>

      <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: "1px solid var(--line)" }}>
        {[
          { key: "cases" as const, label: "病例看板" },
          { key: "testcases" as const, label: "用例库" },
          { key: "coverage" as const, label: "覆盖矩阵" },
          { key: "quality" as const, label: "质量信号" },
        ].map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} style={tabBtn(tab === t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "cases" && <CaseKanban />}
      {tab === "testcases" && <TestCaseLibrary />}
      {tab === "coverage" && <CoverageMatrix />}
      {tab === "quality" && <QualitySignals />}
    </div>
  );
}

function CaseKanban() {
  const [cases, setCases] = useState<BoardCaseItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    getBoardCases()
      .then(setCases)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }, []);

  if (error) return <div style={{ color: "var(--red)", fontSize: 12.5 }}>{error}</div>;
  if (!cases) return <div style={{ color: "var(--muted)", fontSize: 13 }}>加载中…</div>;

  const exportable = cases.filter((c) => c.accepted_query_count > 0);

  function toggleCase(id: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleExport(format: "xlsx" | "json" | "zip") {
    setExportBusy(true);
    setExportError(null);
    try {
      // 病例看板这里没有 decision 筛选器给用户选——默认只要 accept，
      // 这是给"已经确认要跑"的用例出的文件，不是把所有草稿都倒出去。
      await downloadBoardExport(Array.from(selected), format, { decision: "accept" });
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : "导出失败，请重试");
    } finally {
      setExportBusy(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, padding: "8px 12px", background: "var(--card)", border: "1px solid var(--line)", borderRadius: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, color: "var(--sub)" }}>
          {selected.size > 0 ? `已选 ${selected.size} 个病例` : `勾选病例批量导出（不选则导出全部 ${exportable.length} 个已产出用例的病例）`}
        </span>
        {selected.size > 0 && (
          <button onClick={() => setSelected(new Set())} style={btnStyle(false)}>
            清空选择
          </button>
        )}
        <span style={{ flex: 1 }} />
        <button onClick={() => handleExport("xlsx")} disabled={exportBusy} style={btnStyle(true, "var(--green)")}>
          {exportBusy ? "导出中…" : "导出 Excel"}
        </button>
        <button onClick={() => handleExport("zip")} disabled={exportBusy} style={btnStyle(true, "var(--ex)")} title="每条用例一个文件夹：query 原文/多轮画像脚本、真实图片文件、标准卡（如果有）；根目录另附一份汇总 Excel">
          {exportBusy ? "导出中…" : "导出压缩包"}
        </button>
        <button onClick={() => handleExport("json")} disabled={exportBusy} style={btnStyle(false)}>
          导出 JSON
        </button>
      </div>
      {exportError && <div style={{ fontSize: 12, color: "var(--red)", marginBottom: 10 }}>{exportError}</div>}

      <div style={{ display: "grid", gridTemplateColumns: `repeat(${STEPS.length}, 1fr)`, gap: 10 }}>
        {STEPS.map((s) => {
          const inStep = cases.filter((c) => c.current_step === s.key);
          return (
            <div key={s.key} style={{ background: "var(--card)", border: "1px solid var(--line-soft, var(--line))", borderRadius: 8, padding: 8, minHeight: 200 }}>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", marginBottom: 8 }}>
                {s.label} ({inStep.length})
              </div>
              {inStep.map((c) => (
                <div
                  key={c.id}
                  onClick={() => navigate(`/workshop/${c.id}`)}
                  style={{
                    background: "var(--surface)",
                    border: `1px solid ${c.status === "blocked" ? "var(--red)" : "var(--line)"}`,
                    borderRadius: 6,
                    padding: "8px 10px",
                    marginBottom: 6,
                    cursor: "pointer",
                    fontSize: 11.5,
                    display: "flex",
                    gap: 7,
                  }}
                >
                  {c.accepted_query_count > 0 && (
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => toggleCase(c.id)}
                      style={{ marginTop: 2, flexShrink: 0, cursor: "pointer" }}
                    />
                  )}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontWeight: 700 }}>{c.case_no}</div>
                    <div style={{ color: "var(--muted)", marginTop: 2 }}>{(c.patient_meta.name as string) ?? "—"}</div>
                    <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
                      {c.status === "blocked" && <span style={pill("var(--red)", "var(--red-l)")}>阻塞</span>}
                      {c.pending_flag_count > 0 && <span style={pill("var(--mock)", "var(--mock-l)")}>待裁定 {c.pending_flag_count}</span>}
                      {c.accepted_query_count > 0 && <span style={pill("var(--green)", "var(--green-l)")}>用例 {c.accepted_query_count}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TestCaseLibrary() {
  const [items, setItems] = useState<BoardTestCaseItem[] | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioTypeOut[]>([]);
  const [filters, setFilters] = useState<TestCaseFilters>({});
  const [error, setError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ caseId: string; queryId: string } | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [rejectReasonDraft, setRejectReasonDraft] = useState<string | null>(null); // 非 null = 正在填批量不纳入的原因

  const scenarioName: Record<string, string> = {};
  for (const s of scenarios) scenarioName[s.code] = s.name;

  useEffect(() => {
    listScenarioTypes().then(setScenarios).catch(() => {});
  }, []);

  function reload() {
    getBoardTestCases(filters)
      .then((rows) => {
        setItems(rows);
        setSelected(new Set()); // 筛选变了，之前勾的行大概率已经不在当前结果里了
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, [filters]);

  function setFilter(key: keyof TestCaseFilters, value: string) {
    setFilters((f) => ({ ...f, [key]: value || undefined }));
  }

  async function handleExport(format: "xlsx" | "json" | "zip") {
    setExportBusy(true);
    setExportError(null);
    try {
      // 不传 case_ids——按当前这套筛选条件导出，跟表格显示的是同一批数据。
      await downloadBoardExport([], format, filters);
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : "导出失败，请重试");
    } finally {
      setExportBusy(false);
    }
  }

  function toggleOne(id: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (!items) return;
    setSelected((s) => (s.size === items.length ? new Set() : new Set(items.map((it) => it.query_id))));
  }

  async function handleBatchDecide(decision: "accept" | "reject", reason?: string) {
    if (selected.size === 0) return;
    setBatchBusy(true);
    setBatchError(null);
    try {
      await batchDecideQueries(Array.from(selected), decision, reason);
      setRejectReasonDraft(null);
      reload();
    } catch (err) {
      setBatchError(err instanceof ApiError ? err.message : "批量审核失败，请重试");
    } finally {
      setBatchBusy(false);
    }
  }

  const reviewedCount = items?.filter((it) => it.decided_by).length ?? 0;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
        <select onChange={(e) => setFilter("scenario_type", e.target.value)} style={selectStyle}>
          <option value="">全部场景类型</option>
          {scenarios.map((s) => (
            <option key={s.code} value={s.code}>{s.name}</option>
          ))}
        </select>
        <select onChange={(e) => setFilter("cutpoint_type", e.target.value)} style={selectStyle}>
          <option value="">全部裂点类型（历史字段）</option>
          {CUTPOINT_TYPES.map((c) => <option key={c} value={c}>{c} · {CUTPOINT_TYPE_LABEL[c]}</option>)}
        </select>
        <select onChange={(e) => setFilter("journey_stage", e.target.value)} style={selectStyle}>
          <option value="">全部阶段</option>
          {JOURNEY_STAGE_CODES.map((j) => <option key={j} value={j}>{j} · {JOURNEY_STAGE_LABEL[j]}</option>)}
        </select>
        <select onChange={(e) => setFilter("provenance", e.target.value)} style={selectStyle}>
          <option value="">真实 + 推测</option>
          <option value="real">仅真实</option>
          <option value="mock">仅推测</option>
        </select>
        <select onChange={(e) => setFilter("decision", e.target.value)} style={selectStyle}>
          <option value="">已纳入 + 未纳入</option>
          <option value="accept">仅已纳入</option>
          <option value="reject">仅未纳入</option>
        </select>
        <span style={{ flex: 1 }} />
        <button onClick={() => handleExport("xlsx")} disabled={exportBusy} style={btnStyle(true, "var(--green)")}>
          {exportBusy ? "导出中…" : "导出 Excel"}
        </button>
        <button onClick={() => handleExport("zip")} disabled={exportBusy} style={btnStyle(true, "var(--ex)")} title="每条用例一个文件夹：query 原文/多轮画像脚本、真实图片文件、标准卡（如果有）；根目录另附一份汇总 Excel">
          {exportBusy ? "导出中…" : "导出压缩包"}
        </button>
        <button onClick={() => handleExport("json")} disabled={exportBusy} style={btnStyle(false)}>
          导出 JSON
        </button>
      </div>

      {error && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{error}</div>}
      {exportError && <div style={{ color: "var(--red)", fontSize: 12.5, marginBottom: 8 }}>{exportError}</div>}
      {items && (
        <div style={{ fontSize: 11.5, color: "var(--muted)", marginBottom: 8, display: "flex", gap: 14, alignItems: "center" }}>
          <span>共 {items.length} 条（点一行看完整内容；导出会按当前筛选条件）</span>
          <span>已审核 {reviewedCount} / {items.length} 条</span>
        </div>
      )}

      {selected.size > 0 && (
        <div
          style={{
            display: "flex", alignItems: "center", gap: 10, marginBottom: 10, padding: "8px 12px",
            background: "var(--navy-l)", border: "1px solid var(--navy-b)", borderRadius: 8,
          }}
        >
          <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--navy)" }}>已选 {selected.size} 条</span>
          {batchError && <span style={{ fontSize: 11.5, color: "var(--red)" }}>{batchError}</span>}
          <span style={{ flex: 1 }} />
          {rejectReasonDraft === null ? (
            <>
              <button onClick={() => handleBatchDecide("accept")} disabled={batchBusy} style={btnStyle(true, "var(--green)")}>
                {batchBusy ? "处理中…" : "批量纳入"}
              </button>
              <button onClick={() => setRejectReasonDraft("")} disabled={batchBusy} style={btnStyle(true, "var(--red)")}>
                批量不纳入
              </button>
              <button onClick={() => setSelected(new Set())} disabled={batchBusy} style={btnStyle(false)}>
                取消选择
              </button>
            </>
          ) : (
            <>
              <input
                value={rejectReasonDraft}
                onChange={(e) => setRejectReasonDraft(e.target.value)}
                placeholder="不纳入原因（可选）"
                style={{ ...selectStyle, width: 220 }}
                autoFocus
              />
              <button onClick={() => handleBatchDecide("reject", rejectReasonDraft || undefined)} disabled={batchBusy} style={btnStyle(true, "var(--red)")}>
                {batchBusy ? "处理中…" : "确认不纳入"}
              </button>
              <button onClick={() => setRejectReasonDraft(null)} disabled={batchBusy} style={btnStyle(false)}>
                取消
              </button>
            </>
          )}
        </div>
      )}

      <div style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "var(--card)", textAlign: "left" }}>
              <th style={{ padding: "8px 10px", width: 30 }}>
                <input type="checkbox" checked={!!items && items.length > 0 && selected.size === items.length} onChange={toggleAll} />
              </th>
              {["病例", "阶段", "场景", "来源", "Query", "决策"].map((h) => (
                <th key={h} style={{ padding: "8px 10px", fontSize: 10.5, color: "var(--muted)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items?.map((it) => (
              <tr
                key={it.query_id}
                style={{ borderTop: "1px solid var(--line)", cursor: "pointer" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--card)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "")}
              >
                <td style={{ padding: "8px 10px" }} onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(it.query_id)} onChange={() => toggleOne(it.query_id)} />
                </td>
                <td style={tdStyle} onClick={() => setDetail({ caseId: it.case_id, queryId: it.query_id })}>{it.case_no}</td>
                <td style={tdStyle} onClick={() => setDetail({ caseId: it.case_id, queryId: it.query_id })} title={it.journey_stage}>
                  {JOURNEY_STAGE_LABEL[it.journey_stage] ? `${it.journey_stage} · ${JOURNEY_STAGE_LABEL[it.journey_stage]}` : it.journey_stage}
                </td>
                <td style={tdStyle} onClick={() => setDetail({ caseId: it.case_id, queryId: it.query_id })} title={it.scenario_type}>
                  {scenarioName[it.scenario_type] ? `${it.scenario_type} · ${scenarioName[it.scenario_type]}` : it.scenario_type}
                </td>
                <td style={tdStyle} onClick={() => setDetail({ caseId: it.case_id, queryId: it.query_id })}>
                  <span style={pill(it.provenance === "mock" ? "var(--mock)" : "var(--ex)", it.provenance === "mock" ? "var(--mock-l)" : "var(--ex-l)")}>
                    {it.provenance === "mock" ? "推测" : "真实"}
                  </span>
                </td>
                <td
                  style={{ ...tdStyle, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  onClick={() => setDetail({ caseId: it.case_id, queryId: it.query_id })}
                >
                  {it.query_text}
                </td>
                <td style={tdStyle} onClick={() => setDetail({ caseId: it.case_id, queryId: it.query_id })}>
                  <span style={pill(it.decision === "accept" ? "var(--green)" : "var(--red)", it.decision === "accept" ? "var(--green-l)" : "var(--red-l)")}>
                    {it.decision === "accept" ? "已纳入" : "未纳入"}
                  </span>
                  {!it.decided_by && <span style={{ marginLeft: 6, fontSize: 10, color: "var(--muted)" }}>（未审核）</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && <QueryDetailModal caseId={detail.caseId} queryId={detail.queryId} onClose={() => setDetail(null)} />}
    </div>
  );
}

/** 用例库 tab 点一行弹出来的详情——懒加载完整病例（拿到真实的
 * test_direction/test_background/图片/多轮画像脚本，不是表格那行摘要），
 * 跟病例工坊裂点用例步骤共用同一个 QueryCard，不是另外画一套更"好看"但
 * 数据对不上的卡片。 */
function QueryDetailModal({ caseId, queryId, onClose }: { caseId: string; queryId: string; onClose: () => void }) {
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightboxSeq, setLightboxSeq] = useState<number | null>(null);

  useEffect(() => {
    getCase(caseId)
      .then(setCaseDetail)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }, [caseId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && lightboxSeq === null) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, lightboxSeq]);

  let cutpoint: CutpointOut | undefined;
  let query: QueryOut | undefined;
  if (caseDetail) {
    for (const cp of caseDetail.cutpoints) {
      const q = cp.queries.find((x) => x.id === queryId);
      if (q) {
        cutpoint = cp;
        query = q;
        break;
      }
    }
  }

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(10, 12, 16, 0.55)", zIndex: 900, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--bg)", border: "1px solid var(--line)", borderRadius: 12, maxWidth: 640, width: "100%", maxHeight: "88vh", overflow: "auto", padding: 20, boxShadow: "0 24px 70px rgba(0,0,0,0.35)" }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 14, gap: 10 }}>
          <div style={{ fontSize: 14, fontWeight: 700 }}>{caseDetail?.case_no ?? "加载中…"}</div>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} style={{ ...btnStyle(false), padding: "4px 10px" }}>
            关闭
          </button>
        </div>

        {error && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{error}</div>}
        {!caseDetail && !error && <div style={{ color: "var(--muted)", fontSize: 13 }}>加载中…</div>}
        {caseDetail && !query && <div style={{ color: "var(--muted)", fontSize: 13 }}>没有找到这条用例（可能已被弃用或删除）。</div>}
        {caseDetail && cutpoint && query && (
          <QueryCard
            caseId={caseId}
            documents={caseDetail.documents}
            cutpoint={cutpoint}
            query={query}
            stageLabel={JOURNEY_STAGE_LABEL[cutpoint.stage_code]}
            onOpenImage={setLightboxSeq}
            readOnly
          />
        )}
      </div>

      {caseDetail && lightboxSeq !== null && (
        <Lightbox
          caseId={caseId}
          docs={caseDetail.documents.map((d) => ({ id: d.id, seq: d.seq, contentType: d.content_type, label: d.document_type }))}
          initialSeq={lightboxSeq}
          onClose={() => setLightboxSeq(null)}
        />
      )}
    </div>
  );
}

function CoverageMatrix() {
  const [cells, setCells] = useState<CoverageCell[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCoverageMatrix()
      .then(setCells)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }, []);

  if (error) return <div style={{ color: "var(--red)", fontSize: 12.5 }}>{error}</div>;
  if (!cells) return <div style={{ color: "var(--muted)", fontSize: 13 }}>加载中…</div>;

  const byStage = new Map<string, CoverageCell[]>();
  for (const c of cells) {
    if (!byStage.has(c.journey_stage)) byStage.set(c.journey_stage, []);
    byStage.get(c.journey_stage)!.push(c);
  }
  const maxTotal = Math.max(1, ...cells.map((c) => c.accepted_real + c.accepted_mock));

  return (
    <div>
      <p style={{ fontSize: 12.5, color: "var(--sub)", marginBottom: 18 }}>
        业务方 49 个真实场景，按它们各自所属的六阶段旅程分组——只统计已纳入（accept）且未弃用的用例。
        灰色「0 · 空白」是下一批病例该往哪个方向找的信号。
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {JOURNEY_STAGE_CODES.filter((stage) => byStage.has(stage)).map((stage) => (
          <div key={stage}>
            <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8, color: "var(--navy)" }}>
              {stage} · {JOURNEY_STAGE_LABEL[stage]}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 8 }}>
              {byStage.get(stage)!.map((c) => {
                const total = c.accepted_real + c.accepted_mock;
                return (
                  <div
                    key={c.scenario_type}
                    style={{
                      border: "1px solid var(--line)",
                      borderRadius: 7,
                      padding: "8px 10px",
                      background: total > 0 ? "var(--card)" : "var(--surface)",
                    }}
                  >
                    <div style={{ fontSize: 11.5, fontWeight: 600, marginBottom: 5 }}>{c.scenario_name}</div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <div style={{ flex: 1, background: "var(--line)", borderRadius: 4, height: 8, overflow: "hidden" }}>
                        <div style={{ display: "flex", height: "100%", width: `${Math.min(100, (total / maxTotal) * 100)}%` }}>
                          {c.accepted_real > 0 && <div style={{ flex: c.accepted_real, background: "var(--ex)" }} />}
                          {c.accepted_mock > 0 && <div style={{ flex: c.accepted_mock, background: "var(--mock)" }} />}
                        </div>
                      </div>
                      <span style={{ fontSize: 10.5, color: total > 0 ? "var(--muted)" : "var(--red)", whiteSpace: "nowrap" }}>
                        {total > 0 ? `${c.accepted_real} 真实 + ${c.accepted_mock} 推测` : "0 · 空白"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function QualitySignals() {
  const [q, setQ] = useState<QualitySummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getQualitySummary()
      .then(setQ)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载失败"));
  }, []);

  if (error) return <div style={{ color: "var(--red)", fontSize: 12.5 }}>{error}</div>;
  if (!q) return <div style={{ color: "var(--muted)", fontSize: 13 }}>加载中…</div>;

  const stats: { label: string; value: string | number; accent?: string }[] = [
    { label: "病例总数", value: q.case_count },
    { label: "已纳入测试用例", value: q.accepted_test_case_count, accent: "var(--green)" },
    { label: "核对冲突（确认/忽略/总数）", value: `${q.flags_confirmed} / ${q.flags_ignored} / ${q.flags_total}` },
    { label: "推测数据（通过/退回/总数）", value: `${q.mocks_passed} / ${q.mocks_rejected} / ${q.mocks_total}` },
    { label: "Pipeline 运行（失败/总数）", value: `${q.pipeline_runs_failed} / ${q.pipeline_runs_total}`, accent: q.pipeline_runs_failed > 0 ? "var(--red)" : undefined },
    {
      label: `Token 用量（${q.token_usage_run_count} 次运行有记录）`,
      value: formatTokens(q.token_usage_total),
      accent: "var(--ex)",
    },
  ];

  const maxByAgent = Math.max(1, ...Object.values(q.token_usage_by_agent));
  const maxByProvider = Math.max(1, ...Object.values(q.token_usage_by_provider));

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 22 }}>
        {stats.map((s) => (
          <div key={s.label} style={{ border: "1px solid var(--line)", borderRadius: 9, padding: "14px 16px", background: "var(--card)" }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: s.accent ?? "var(--navy)" }}>{s.value}</div>
            <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: 3 }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {Object.keys(q.pipeline_failures_by_agent).length > 0 && (
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8 }}>失败次数按 Agent 分布</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {Object.entries(q.pipeline_failures_by_agent).map(([code, n]) => (
                <div key={code} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 30, fontSize: 12, fontWeight: 700 }}>{code}</span>
                  <div style={{ flex: 1, background: "var(--card)", borderRadius: 4, height: 10 }}>
                    <div style={{ width: `${Math.min(100, n * 20)}%`, background: "var(--red)", height: 10, borderRadius: 4 }} />
                  </div>
                  <span style={{ fontSize: 11.5, color: "var(--muted)" }}>{n}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {Object.keys(q.token_usage_by_agent).length > 0 && (
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8 }}>Token 用量按 Agent 分布</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {Object.entries(q.token_usage_by_agent)
                .sort((a, b) => b[1] - a[1])
                .map(([code, n]) => (
                  <div key={code} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ width: 30, fontSize: 12, fontWeight: 700 }}>{code}</span>
                    <div style={{ flex: 1, background: "var(--card)", borderRadius: 4, height: 10 }}>
                      <div style={{ width: `${(n / maxByAgent) * 100}%`, background: "var(--ex)", height: 10, borderRadius: 4 }} />
                    </div>
                    <span style={{ fontSize: 11.5, color: "var(--muted)", whiteSpace: "nowrap" }}>{formatTokens(n)}</span>
                  </div>
                ))}
            </div>
          </div>
        )}

        {Object.keys(q.token_usage_by_provider).length > 0 && (
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8 }}>Token 用量按模型分布</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {Object.entries(q.token_usage_by_provider)
                .sort((a, b) => b[1] - a[1])
                .map(([provider, n]) => (
                  <div key={provider} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ width: 60, fontSize: 12, fontWeight: 700, textTransform: "capitalize" }}>{provider}</span>
                    <div style={{ flex: 1, background: "var(--card)", borderRadius: 4, height: 10 }}>
                      <div style={{ width: `${(n / maxByProvider) * 100}%`, background: "var(--navy)", height: 10, borderRadius: 4 }} />
                    </div>
                    <span style={{ fontSize: 11.5, color: "var(--muted)", whiteSpace: "nowrap" }}>{formatTokens(n)}</span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function tabBtn(active: boolean): CSSProperties {
  return {
    padding: "8px 16px",
    border: "none",
    borderBottom: `2px solid ${active ? "var(--navy)" : "transparent"}`,
    background: "none",
    color: active ? "var(--navy)" : "var(--sub)",
    fontWeight: active ? 700 : 500,
    fontSize: 13,
    cursor: "pointer",
  };
}

function pill(fg: string, bg: string): CSSProperties {
  return { fontSize: 10, padding: "1px 7px", borderRadius: 8, background: bg, color: fg, fontWeight: 600 };
}

function btnStyle(primary = false, accent = "var(--navy)"): CSSProperties {
  return {
    padding: "6px 13px",
    borderRadius: 6,
    border: `1px solid ${primary ? accent : "var(--line)"}`,
    background: primary ? accent : "var(--surface)",
    color: primary ? "#fff" : "var(--sub)",
    fontWeight: primary ? 600 : 500,
    fontSize: 12,
    cursor: "pointer",
  };
}

const tdStyle: CSSProperties = { padding: "8px 10px" };
const selectStyle: CSSProperties = {
  padding: "6px 9px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--surface)",
  fontSize: 12,
  fontFamily: "inherit",
};
