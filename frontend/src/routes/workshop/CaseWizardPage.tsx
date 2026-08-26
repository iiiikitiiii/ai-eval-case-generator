import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { listPersonas, listScenarioTypes } from "../../shared/api/agents";
import {
  advanceStep,
  decideFlag,
  decideMock,
  decideQuery,
  deleteDocument,
  downloadCaseExport,
  exportCase,
  getCase,
  getPipelineRuns,
  pollRun,
  resolveBoundary,
  runAgentA,
  runAgentB,
  runAgentC,
  runAgentD,
  runAgentF,
  selectVariant,
  toggleCutpoint,
  uploadDocuments,
  type ExportResult,
} from "../../shared/api/cases";
import { ApiError } from "../../shared/api/client";
import type { CaseDetail, PipelineRunOut, ScenarioTypeOut, UserPersonaOut, WorkshopStep } from "../../shared/api/types";
import { DocRefLink } from "../../shared/ui/DocRefLink";
import { DocThumb } from "../../shared/ui/DocThumb";
import { Lightbox } from "../../shared/ui/Lightbox";
import { QueryCard } from "../../shared/ui/QueryCard";
import { RunningProgress } from "../../shared/ui/RunningProgress";

const STEPS: { key: WorkshopStep; label: string }[] = [
  { key: "up", label: "导入" },
  { key: "a", label: "核对" },
  { key: "b", label: "阶段裁定" },
  { key: "d", label: "推测抽查" },
  { key: "f", label: "裂点用例" },
  { key: "out", label: "产出" },
];

// 业务方场景库真实使用的六阶段旅程（doc/专病管家测评标准-场景清单+标准.xlsx
// 「整合场景清单 (六阶段)」），不是早期版本发明的 J01-J08。
const STAGE_LABEL: Record<string, string> = {
  J01: "疑诊 / 初筛期", J02: "确诊后治疗方案决策期", J03: "初诊治疗实施期",
  J04: "复发 / 进展 / 耐药后治疗方案调整", J05: "康复随访期", J06: "姑息照护期",
};

const STAGE_STATUS_LABEL: Record<string, { label: string; fg: string; bg: string }> = {
  covered: { label: "已覆盖", fg: "var(--navy)", bg: "var(--navy-l)" },
  not_applicable: { label: "不适用", fg: "var(--muted)", bg: "var(--card)" },
  real_gap: { label: "真实缺口", fg: "var(--mock)", bg: "var(--mock-l)" },
  uncovered: { label: "尚未发生", fg: "var(--muted)", bg: "var(--card)" },
};

const RUN_STATUS_LABEL: Record<string, { label: string; fg: string; bg: string }> = {
  succeeded: { label: "成功", fg: "var(--green)", bg: "var(--green-l)" },
  failed: { label: "失败", fg: "var(--red)", bg: "var(--red-l)" },
  running: { label: "运行中", fg: "var(--navy)", bg: "var(--navy-l)" },
  queued: { label: "排队中", fg: "var(--muted)", bg: "var(--card)" },
};

/** P0-2《交互体验优化需求》：阶段裁定页拆分展示 B 与 C 的运行状态和最近结果，
 * 并提供独立的重试入口——不能因为 C 失败就非得陪着已经成功的 B 一起重跑。 */
function AgentRetryRow({
  title, run, isBusy, retryLabel, onRetry, traceHref,
}: {
  title: string; run: PipelineRunOut | undefined; isBusy: boolean;
  retryLabel: string; onRetry: () => void; traceHref: string;
}) {
  const st = run ? RUN_STATUS_LABEL[run.status] : null;
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "10px 13px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, flex: 1 }}>{title}</span>
        {st && (
          <span style={{ padding: "1px 8px", borderRadius: 8, fontSize: 10.5, fontWeight: 600, color: st.fg, background: st.bg }}>
            {st.label}
          </span>
        )}
        {run?.finished_at && (
          <span style={{ fontSize: 10.5, color: "var(--muted)" }}>{new Date(run.finished_at).toLocaleString("zh-CN")}</span>
        )}
        <Link to={traceHref} style={{ fontSize: 11, color: "var(--ex)" }}>
          查看运行详情
        </Link>
        <button onClick={onRetry} disabled={isBusy || run?.status === "running" || run?.status === "queued"} style={btnStyle(false)}>
          {retryLabel}
        </button>
      </div>
      {run?.status === "failed" && run.error && (
        <div style={{ ...inlineNote, color: "var(--red)", marginTop: 6 }}>{run.error}</div>
      )}
    </div>
  );
}

function ConfirmDialog({
  title, body, confirmLabel, busy, onCancel, onConfirm,
}: { title: string; body: string; confirmLabel: string; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(10, 12, 16, 0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--card)", borderRadius: 10, padding: "20px 22px", width: 380, boxShadow: "0 12px 40px rgba(0,0,0,0.25)" }}
      >
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--navy)", marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 12.5, color: "var(--sub)", lineHeight: 1.6, marginBottom: 16 }}>{body}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            onClick={onCancel}
            disabled={busy}
            style={{ border: "1px solid var(--line)", background: "var(--surface)", borderRadius: 6, padding: "6px 14px", fontSize: 12, color: "var(--sub)", cursor: "pointer" }}
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            style={{ border: "none", background: "var(--red)", borderRadius: 6, padding: "6px 14px", fontSize: 12, color: "#fff", cursor: busy ? "default" : "pointer" }}
          >
            {busy ? "处理中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CaseWizardPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [runningLabel, setRunningLabel] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [progressNote, setProgressNote] = useState<string | null>(null);
  const [exportData, setExportData] = useState<ExportResult | null>(null);
  const [pendingPreviews, setPendingPreviews] = useState<{ name: string; url: string }[]>([]);
  const [personas, setPersonas] = useState<UserPersonaOut[]>([]);
  const [selectedPersonaCodes, setSelectedPersonaCodes] = useState<string[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioTypeOut[]>([]);
  const [selectedScenarioCodes, setSelectedScenarioCodes] = useState<string[]>([]);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [lightboxSeq, setLightboxSeq] = useState<number | null>(null);
  const [pipelineRuns, setPipelineRuns] = useState<PipelineRunOut[]>([]);
  const [confirmRetryB, setConfirmRetryB] = useState(false);
  const [confirmDeleteDoc, setConfirmDeleteDoc] = useState<{ id: string; label: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listPersonas().then((all) => {
      const active = all.filter((p) => p.active);
      setPersonas(active);
      setSelectedPersonaCodes(active.map((p) => p.code));
    }).catch(() => {});
  }, []);

  function togglePersonaCode(code: string) {
    setSelectedPersonaCodes((codes) => (codes.includes(code) ? codes.filter((c) => c !== code) : [...codes, code]));
  }

  useEffect(() => {
    listScenarioTypes().then((all) => setScenarios(all.filter((s) => s.active))).catch(() => {});
  }, []);

  function toggleScenarioCode(code: string) {
    setSelectedScenarioCodes((codes) => (codes.includes(code) ? codes.filter((c) => c !== code) : [...codes, code]));
  }

  // 用户提出的问题："agentF 裂点用例页面，理论上可以让用户选择要构建的
  // 场景吧？"——跟画像选择同一个模式：候选清单先按这个病例实际命中的
  // 阶段（covered/real_gap）过滤到"适用"的那几个，默认全选，人工可以
  // 缩小范围再触发运行，不用生成一整批之后再人工挑着看。只在还没生成过
  // 裂点、且尚未手动勾选过时做一次默认全选，避免每次 reload 都把已经
  // 调整过的勾选覆盖掉。
  //
  // 场景本来就是按 journey_stages 跟旅程阶段绑定的，候选集不能是一个
  // 摊平的名字列表——用户明确要求"也需要展示出来 Journey-场景，方便
  // 用户理解"，所以按这个病例实际命中的每个阶段分组展示；同一个场景如果
  // 适用多个阶段，会在每个相关分组里都出现（同一个 code，视觉上重复，
  // 换来的是"这个场景为什么会被推荐"一眼可见）。
  const relevantStageCodes = caseDetail
    ? caseDetail.stage_map.filter((s) => s.status === "covered" || s.status === "real_gap").map((s) => s.stage_code)
    : [];
  const scenariosByStage = relevantStageCodes
    .map((stageCode) => ({ stageCode, scenarios: scenarios.filter((s) => s.journey_stages.includes(stageCode)) }))
    .filter((g) => g.scenarios.length > 0);
  const applicableScenarios = Array.from(new Map(scenariosByStage.flatMap((g) => g.scenarios).map((s) => [s.code, s])).values());

  useEffect(() => {
    if (!caseDetail || caseDetail.cutpoints.length > 0 || selectedScenarioCodes.length > 0 || applicableScenarios.length === 0) return;
    setSelectedScenarioCodes(applicableScenarios.map((s) => s.code));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseDetail?.id, applicableScenarios.length]);

  useEffect(() => {
    if (!runningLabel) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [runningLabel]);

  const reload = useCallback(() => {
    if (!caseId) return;
    getCase(caseId)
      .then(setCaseDetail)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载病例失败"));
  }, [caseId]);

  useEffect(reload, [reload]);

  const reloadRuns = useCallback(() => {
    if (!caseId) return;
    getPipelineRuns(caseId).then(setPipelineRuns).catch(() => {});
  }, [caseId]);

  useEffect(reloadRuns, [reloadRuns]);

  /** list_pipeline_runs 按 created_at asc 排序，同一 agent_code 里最后一条就是最近一次。 */
  function latestRunFor(agentCode: string): PipelineRunOut | undefined {
    const runs = pipelineRuns.filter((r) => r.agent_code === agentCode);
    return runs[runs.length - 1];
  }

  useEffect(() => {
    if (caseId && caseDetail?.current_step === "out") {
      exportCase(caseId).then(setExportData).catch(() => {});
    }
  }, [caseId, caseDetail?.current_step]);

  async function withBusy<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败，请重试");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  /** run-X now just enqueues (returns in ~10ms with status=queued) — the
   * real work happens in the arq worker. This triggers it, shows a
   * "运行中" state with a live timer while polling the trace list for a
   * terminal status, then reloads the case. One helper for A/B/C/D/F
   * instead of repeating the trigger+poll+reload dance five times. */
  async function runStep(label: string, trigger: () => Promise<PipelineRunOut>): Promise<boolean> {
    setError(null);
    setNote(null);
    setRunningLabel(label);
    setProgressNote(null);
    try {
      const queued = await trigger();
      const finished = await pollRun(caseId!, queued.id, { onTick: (run) => setProgressNote(run.progress_note) });
      if (finished.status === "failed") {
        setError(finished.error ?? `${label}运行失败`);
        return false;
      }
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `${label}运行失败`);
      return false;
    } finally {
      setRunningLabel(null);
      setProgressNote(null);
      reload();
      reloadRuns();
    }
  }

  function handleFilePicked() {
    pendingPreviews.forEach((p) => URL.revokeObjectURL(p.url));
    const files = fileInput.current?.files;
    setPendingPreviews(files ? Array.from(files).map((f) => ({ name: f.name, url: URL.createObjectURL(f) })) : []);
  }

  async function handleUpload() {
    if (!caseId || !fileInput.current?.files?.length) return;
    const files = Array.from(fileInput.current.files);
    const updated = await withBusy(() => uploadDocuments(caseId, files));
    if (updated) setCaseDetail(updated);
    if (fileInput.current) fileInput.current.value = "";
    pendingPreviews.forEach((p) => URL.revokeObjectURL(p.url));
    setPendingPreviews([]);
  }

  async function handleRunAgentA() {
    if (!caseId) return;
    await runStep("Agent A 抽取", () => runAgentA(caseId));
  }

  /** P1「资料导入前支持整理与确认」——只在导入这一步能删，后端会在
   * Agent A 跑过之后拒绝（下游已经按 seq 引用这些单据了）。 */
  async function handleDeleteDocument() {
    if (!caseId || !confirmDeleteDoc) return;
    const target = confirmDeleteDoc.id;
    setConfirmDeleteDoc(null);
    const updated = await withBusy(() => deleteDocument(caseId, target));
    if (updated) setCaseDetail(updated);
  }

  async function handleDecideFlag(flagId: string, decision: "confirm" | "ignore") {
    if (!caseId) return;
    await withBusy(() => decideFlag(caseId, flagId, decision));
    reload();
  }

  /** 首次进入这一步、B/C 都还没跑过时的一键入口——省一次点击。跑过一次之后
   * 一律走下面的独立重试入口，不再提供"合并重跑"（重试语义必须是精确的：
   * 只重试失败的那一个，不连带重跑已经成功、且可能已经被人工裁定过的另一个）。 */
  async function handleRunStageAnalysis() {
    if (!caseId) return;
    const bOk = await runStep("Agent B 阶段映射", () => runAgentB(caseId));
    if (!bOk) return;
    await runStep("Agent C 组合抽取", () => runAgentC(caseId));
  }

  /** 重试 B：agent_b.py 每次重跑都会无条件清空 boundary_decisions 并重新生成
   * stage_map（阶段映射变了，旧的人工边界裁定不再有意义）——这是本项目
   * 确认保留的既有行为，前端要做的是在动手前把这句话明确说给人听，而不是
   * 悄悄清空。已有阶段结果时才需要这层确认；纯首次运行没什么可清空的。 */
  async function handleRetryAgentB() {
    if (!caseId) return;
    setConfirmRetryB(false);
    await runStep("Agent B 阶段映射", () => runAgentB(caseId));
  }

  function handleRetryAgentBClick() {
    if (caseDetail!.stage_map.length > 0 || caseDetail!.boundary_decisions.length > 0) {
      setConfirmRetryB(true);
    } else {
      handleRetryAgentB();
    }
  }

  /** 重试 C：与 B 相互独立，不会碰 stage_map / boundary_decisions，
   * 不需要任何确认。 */
  async function handleRetryAgentC() {
    if (!caseId) return;
    await runStep("Agent C 组合抽取", () => runAgentC(caseId));
  }

  async function handleResolveBoundary(decisionId: string, resolvedStage: string) {
    if (!caseId) return;
    await withBusy(() => resolveBoundary(caseId, decisionId, resolvedStage));
    reload();
  }

  async function handleRunAgentD() {
    if (!caseId) return;
    await runStep("Agent D 补丁", () => runAgentD(caseId));
  }

  async function handleDecideMock(mockId: string, decision: "pass" | "reject") {
    if (!caseId) return;
    await withBusy(() => decideMock(caseId, mockId, decision));
    reload();
  }

  async function handleRunAgentF() {
    if (!caseId) return;
    await runStep("Agent F 裂点生成", () =>
      runAgentF(
        caseId,
        selectedPersonaCodes.length > 0 ? selectedPersonaCodes : undefined,
        selectedScenarioCodes.length > 0 ? selectedScenarioCodes : undefined,
      ),
    );
  }

  async function handleDownloadExport(format: "xlsx" | "json" | "zip") {
    if (!caseId || !caseDetail) return;
    setDownloadError(null);
    try {
      await downloadCaseExport(caseId, caseDetail.case_no, format);
    } catch (err) {
      setDownloadError(err instanceof ApiError ? err.message : "下载失败，请重试");
    }
  }

  async function handleToggleCutpoint(cutpointId: string, enabled: boolean) {
    if (!caseId) return;
    await withBusy(() => toggleCutpoint(caseId, cutpointId, enabled));
    reload();
  }

  async function handleDecideQuery(queryId: string, decision: "accept" | "reject") {
    if (!caseId) return;
    await withBusy(() => decideQuery(caseId, queryId, decision));
    reload();
  }

  async function handleSelectVariant(variantId: string, selected: boolean) {
    if (!caseId) return;
    await withBusy(() => selectVariant(caseId, variantId, selected));
    reload();
  }

  async function handleAdvance(target: WorkshopStep) {
    if (!caseId) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const updated = await advanceStep(caseId, target);
      setCaseDetail(updated);
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : "暂时无法进入下一阶段");
    } finally {
      setBusy(false);
    }
  }

  if (!caseDetail) {
    return (
      <div style={{ padding: 32 }}>
        <Link to="/workshop" style={{ fontSize: 12.5, color: "var(--sub)" }}>
          ← 返回病例列表
        </Link>
        <div style={{ marginTop: 20, color: error ? "var(--red)" : "var(--muted)", fontSize: 13 }}>
          {error ?? "加载中…"}
        </div>
      </div>
    );
  }

  const isBusy = busy || runningLabel !== null;
  const currentIdx = STEPS.findIndex((s) => s.key === caseDetail.current_step);
  const undecidedFlags = caseDetail.flags.filter((f) => !f.decision).length;
  const undecidedBoundary = caseDetail.boundary_decisions.filter((b) => !b.resolved_stage).length;
  const hasRealGap = caseDetail.stage_map.some((s) => s.status === "real_gap");
  const undecidedMocks = caseDetail.mocks.filter((m) => !m.decision).length;
  const acceptedQueries = caseDetail.cutpoints
    .filter((c) => c.enabled)
    .reduce((n, c) => n + c.queries.filter((q) => q.decision === "accept").length, 0);

  return (
    <div style={{ padding: "24px 32px 60px", maxWidth: 920 }}>
      <Link to="/workshop" style={{ fontSize: 12.5, color: "var(--sub)" }}>
        ← 返回病例列表
      </Link>

      <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "10px 0 18px" }}>
        <h1 style={{ fontSize: 19, fontWeight: 700, margin: 0 }}>{caseDetail.case_no}</h1>
        <span style={{ fontSize: 12.5, color: "var(--sub)" }}>
          {(caseDetail.patient_meta.name as string) ?? "未命名患者"} · {(caseDetail.patient_meta.dx as string) ?? ""}
        </span>
        <span style={{ flex: 1 }} />
        {caseDetail.documents.length > 0 && (
          <button
            onClick={() => setLightboxSeq(caseDetail.documents[0].seq)}
            style={{ fontSize: 12, color: "var(--ex)", background: "none", border: "none", cursor: "pointer", padding: 0, font: "inherit" }}
          >
            查看病历图片（{caseDetail.documents.length}）
          </button>
        )}
        <Link to={`/workshop/${caseId}/trace`} style={{ fontSize: 12, color: "var(--ex)" }}>
          运行记录 →
        </Link>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 24, borderBottom: "1px solid var(--line)", paddingBottom: 10 }}>
        {STEPS.map((s, i) => (
          <div
            key={s.key}
            style={{
              flex: 1,
              textAlign: "center",
              fontSize: 11.5,
              fontWeight: i === currentIdx ? 700 : 500,
              color: i < currentIdx ? "var(--green)" : i === currentIdx ? "var(--navy)" : "var(--muted)",
            }}
          >
            {i < currentIdx ? "✓ " : `${i + 1}. `}
            {s.label}
          </div>
        ))}
      </div>

      {caseDetail.status === "blocked" && (
        <div style={noteBox("var(--red)", "var(--red-l)")}>
          <b>上一次运行失败了</b>——病例安全停在这一步，不是卡住、不丢数据。看
          <Link to={`/workshop/${caseId}/trace`} style={{ color: "var(--red)", textDecoration: "underline", margin: "0 3px" }}>
            运行记录
          </Link>
          里的具体报错，改完再点一次下面的运行按钮重试。
        </div>
      )}

      {runningLabel && <RunningProgress label={runningLabel} elapsed={elapsed} note={progressNote} />}
      {error && <div style={noteBox("var(--red)", "var(--red-l)")}>{error}</div>}
      {note && <div style={noteBox("var(--ex)", "var(--ex-l)")}>{note}</div>}

      {caseDetail.current_step === "up" && (
        <section>
          <h2 style={sectionTitle}>导入病例单据</h2>
          <p style={sectionLead}>上传该病例的原始病历图片，全部上传完成后运行 Agent A 一次性抽取结构化记录。</p>

          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
            <input ref={fileInput} type="file" multiple accept="image/*" disabled={isBusy} onChange={handleFilePicked} />
            <button onClick={handleUpload} disabled={isBusy || pendingPreviews.length === 0} style={btnStyle()}>
              上传
            </button>
          </div>

          {pendingPreviews.length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>
              {pendingPreviews.map((p) => (
                <div key={p.url} style={{ width: 76, textAlign: "center" }}>
                  <img src={p.url} alt={p.name} style={{ width: 76, height: 76, objectFit: "cover", borderRadius: 7, border: "1px solid var(--line)" }} />
                  <div style={{ fontSize: 9.5, color: "var(--muted)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</div>
                </div>
              ))}
            </div>
          )}

          {caseDetail.documents.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10, marginBottom: 18 }}>
              {caseDetail.documents.map((d) => (
                <div key={d.id} style={{ ...docCard, display: "flex", gap: 9, alignItems: "flex-start" }}>
                  <DocThumb caseId={caseId!} documentId={d.id} contentType={d.content_type} size={44} onClick={() => setLightboxSeq(d.seq)} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--navy)" }}>DOC-{String(d.seq).padStart(2, "0")}</div>
                    <div style={{ fontSize: 12.5, fontWeight: 600, margin: "3px 0" }}>{d.document_type ?? "待抽取"}</div>
                    {d.confidence.fields !== undefined && (
                      <div style={{ fontSize: 10.5, color: "var(--muted)" }}>字段置信度 {d.confidence.fields?.toFixed(2)}</div>
                    )}
                  </div>
                  <button
                    onClick={() => setConfirmDeleteDoc({ id: d.id, label: `DOC-${String(d.seq).padStart(2, "0")}` })}
                    disabled={isBusy}
                    title="删除误传的这份单据"
                    style={{ border: "none", background: "none", color: "var(--red)", fontSize: 11, cursor: "pointer", padding: 2, flexShrink: 0 }}
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
          )}

          {confirmDeleteDoc && (
            <ConfirmDialog
              title={`删除 ${confirmDeleteDoc.label}？`}
              body="这份单据会从病例里彻底移除，剩余单据的编号会自动重新连续排列。删除后不可恢复，如果是误操作需要重新上传。"
              confirmLabel="确认删除"
              busy={isBusy}
              onCancel={() => setConfirmDeleteDoc(null)}
              onConfirm={handleDeleteDocument}
            />
          )}

          <button onClick={handleRunAgentA} disabled={busy || caseDetail.documents.length === 0} style={btnStyle(true)}>
            {isBusy ? "运行中…" : `运行 Agent A 抽取（${caseDetail.documents.length} 份单据）`}
          </button>
        </section>
      )}

      {caseDetail.current_step === "a" && (
        <section>
          <h2 style={sectionTitle}>核对冲突</h2>
          <p style={sectionLead}>
            {undecidedFlags > 0 ? `还有 ${undecidedFlags} 项待裁定` : "全部已裁定，可以进入下一步"}
          </p>

          {caseDetail.flags.length === 0 && (
            <div style={{ fontSize: 12.5, color: "var(--sub)", marginBottom: 16 }}>本次抽取没有发现跨病历冲突。</div>
          )}

          {caseDetail.flags.map((f) => (
            <div key={f.id} style={flagCard(f.severity)}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {f.field} · {f.type}
                <span style={{ fontSize: 10.5, color: "var(--muted)", fontWeight: 400, marginLeft: 8 }}>
                  涉及{" "}
                  {f.involved_docs.map((n, i) => (
                    <span key={n}>
                      {i > 0 && " / "}
                      <DocRefLink seq={n} onOpen={setLightboxSeq} />
                    </span>
                  ))}
                </span>
              </div>
              <div style={{ fontSize: 12.5, margin: "5px 0" }}>{f.detail}</div>
              {f.why && <div style={inlineNote}>{f.why}</div>}
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <button onClick={() => handleDecideFlag(f.id, "confirm")} disabled={isBusy} style={btnStyle(f.decision === "confirm", "var(--red)")}>
                  确认为问题
                </button>
                <button onClick={() => handleDecideFlag(f.id, "ignore")} disabled={isBusy} style={btnStyle(f.decision === "ignore", "var(--green)")}>
                  标记为无害
                </button>
              </div>
            </div>
          ))}

          <button onClick={() => handleAdvance("b")} disabled={busy || undecidedFlags > 0} style={{ ...btnStyle(true), marginTop: 10 }}>
            下一步：阶段裁定
          </button>
        </section>
      )}

      {caseDetail.current_step === "b" && (
        <section>
          <h2 style={sectionTitle}>阶段裁定</h2>
          <p style={sectionLead}>Agent B 把病历映射到 J01–J06 旅程阶段，Agent C 同步组合出患者画像。边界判断需要人工二选一裁定。</p>

          {confirmRetryB && (
            <ConfirmDialog
              title="重新运行阶段映射？"
              body="将清空当前边界裁定并重新生成——Agent B 每次运行都会重新判定所有旅程阶段，已经人工裁定过的边界归属会一并被清空，需要重新裁定一次。Agent C 的患者画像不受影响。"
              confirmLabel="确认重跑"
              busy={isBusy}
              onCancel={() => setConfirmRetryB(false)}
              onConfirm={handleRetryAgentB}
            />
          )}

          {caseDetail.stage_map.length === 0 && !latestRunFor("B") && !latestRunFor("C") ? (
            <button onClick={handleRunStageAnalysis} disabled={isBusy} style={btnStyle(true)}>
              {isBusy ? "运行中…" : "运行阶段映射 + 组合抽取（Agent B + C）"}
            </button>
          ) : (
            <>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}>
                <AgentRetryRow
                  title="Agent B · 阶段映射"
                  run={latestRunFor("B")}
                  isBusy={isBusy}
                  retryLabel={caseDetail.stage_map.length > 0 ? "重试阶段映射" : "运行阶段映射"}
                  onRetry={handleRetryAgentBClick}
                  traceHref={`/workshop/${caseId}/trace`}
                />
                <AgentRetryRow
                  title="Agent C · 组合抽取"
                  run={latestRunFor("C")}
                  isBusy={isBusy}
                  retryLabel={caseDetail.persona.length > 0 ? "重试组合抽取" : "运行组合抽取"}
                  onRetry={handleRetryAgentC}
                  traceHref={`/workshop/${caseId}/trace`}
                />
              </div>

              {caseDetail.stage_map.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 18 }}>
                  {caseDetail.stage_map.map((s) => {
                    const st = STAGE_STATUS_LABEL[s.status];
                    return (
                      <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 12px", border: "1px solid var(--line)", borderRadius: 7 }}>
                        <span style={{ fontSize: 11, fontWeight: 700, width: 32 }}>{s.stage_code}</span>
                        <span style={{ fontSize: 12.5, fontWeight: 600, width: 140 }}>{STAGE_LABEL[s.stage_code]}</span>
                        <span style={{ padding: "1px 8px", borderRadius: 8, fontSize: 10.5, fontWeight: 600, color: st.fg, background: st.bg }}>{st.label}</span>
                        <span style={{ fontSize: 11.5, color: "var(--sub)", flex: 1 }}>
                          {s.docs.length > 0
                            ? s.docs.map((n, i) => (
                                <span key={n}>
                                  {i > 0 && " · "}
                                  <DocRefLink seq={n} onOpen={setLightboxSeq} />
                                </span>
                              ))
                            : s.reason}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}

              {caseDetail.boundary_decisions.length > 0 && (
                <div style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8 }}>边界判断（需要人工裁定归属）</div>
                  {caseDetail.boundary_decisions.map((bd) => (
                    <div key={bd.id} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "10px 13px", marginBottom: 8 }}>
                      <div style={{ fontSize: 12.5 }}>
                        <DocRefLink seq={bd.doc_seq} onOpen={setLightboxSeq} />：{bd.rule_applied}
                      </div>
                      {bd.rationale && <div style={inlineNote}>{bd.rationale}</div>}
                      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                        <button
                          onClick={() => handleResolveBoundary(bd.id, bd.assigned_stage)}
                          disabled={isBusy}
                          style={btnStyle(bd.resolved_stage === bd.assigned_stage, "var(--navy)")}
                        >
                          归入 {bd.assigned_stage}（默认）
                        </button>
                        <button
                          onClick={() => handleResolveBoundary(bd.id, bd.alternative_stage)}
                          disabled={isBusy}
                          style={btnStyle(bd.resolved_stage === bd.alternative_stage, "var(--navy)")}
                        >
                          改判 {bd.alternative_stage}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {caseDetail.persona.length > 0 && (
                <div style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8 }}>患者画像（Agent C，只读）</div>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <tbody>
                      {caseDetail.persona.map((p) => (
                        <tr key={p.id} style={{ borderTop: "1px solid var(--line)" }}>
                          <td style={{ padding: "6px 10px", color: "var(--sub)", width: 110 }}>{p.field}</td>
                          <td style={{ padding: "6px 10px" }}>
                            {p.value}
                            {p.flag && <span style={{ marginLeft: 6, fontSize: 10, color: "var(--mock)", background: "var(--mock-l)", padding: "1px 6px", borderRadius: 7 }}>{p.flag}</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <button
                onClick={() => handleAdvance("d")}
                disabled={busy || undecidedBoundary > 0 || caseDetail.stage_map.length === 0}
                style={btnStyle(true)}
              >
                下一步：推测抽查
                {caseDetail.stage_map.length === 0
                  ? "（阶段映射还没有成功结果）"
                  : undecidedBoundary > 0
                    ? `（还有 ${undecidedBoundary} 项边界未裁定）`
                    : ""}
              </button>
            </>
          )}
        </section>
      )}

      {caseDetail.current_step === "d" && (
        <section>
          <h2 style={sectionTitle}>推测抽查</h2>
          <p style={sectionLead}>
            Agent D 只为「真实缺口」（real_gap）阶段补一条推测记录，不会替这位患者猜测还没发生的未来。
            每一条都带 provenance=mock 标识，需要人工逐条抽查。这一步不是必经步骤——不想要推测数据，可以直接跳过。
          </p>

          {caseDetail.mocks.length === 0 && !hasRealGap && (
            <div style={{ fontSize: 12.5, color: "var(--sub)", marginBottom: 16 }}>这个病例没有真实缺口阶段，不需要推测补丁，可以直接进入下一步。</div>
          )}

          {caseDetail.mocks.length === 0 && hasRealGap && (
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16 }}>
              <button onClick={handleRunAgentD} disabled={isBusy} style={btnStyle(true)}>
                {isBusy ? "运行中…" : "运行补丁 Agent D"}
              </button>
              <span style={{ fontSize: 11.5, color: "var(--sub)" }}>存在真实缺口阶段，建议跑一次；不需要的话可以跳过</span>
            </div>
          )}

          {caseDetail.mocks.map((m) => (
            <div key={m.id} style={mockCard}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--mock)" }}>{m.stage_code}</span>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{m.title}</span>
                <span style={strengthBadge(m.strength)}>{m.strength}</span>
                {m.date_label && <span style={{ fontSize: 11, color: "var(--mock)" }}>{m.date_label}</span>}
              </div>
              <div style={{ background: "var(--surface)", borderRadius: 5, padding: "7px 10px", fontSize: 11.5, marginBottom: 8 }}>
                <b style={{ fontSize: 10, color: "var(--mock)", display: "block" }}>推测依据</b>
                {m.clinical_basis}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => handleDecideMock(m.id, "pass")} disabled={isBusy} style={btnStyle(m.decision === "pass", "var(--green)")}>
                  通过
                </button>
                <button onClick={() => handleDecideMock(m.id, "reject")} disabled={isBusy} style={btnStyle(m.decision === "reject", "var(--red)")}>
                  退回不采用
                </button>
              </div>
            </div>
          ))}

          <button
            onClick={() => handleAdvance("f")}
            disabled={busy || undecidedMocks > 0}
            style={{ ...btnStyle(true), marginTop: 10 }}
          >
            {caseDetail.mocks.length === 0 ? "下一步：裂点用例（跳过推测抽查）" : "下一步：裂点用例"}
          </button>
        </section>
      )}

      {caseDetail.current_step === "f" && (
        <section>
          <h2 style={sectionTitle}>裂点用例</h2>
          <p style={sectionLead}>Agent F 识别信息状态断点并生成分场景测试 query。逐条纳入/不纳入，产出前至少需要一条被纳入的用例。</p>

          {caseDetail.cutpoints.length === 0 && (
            <div style={{ marginBottom: 14 }}>
              {applicableScenarios.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 5 }}>
                    要构建哪些场景（按这个病例已覆盖 / 真实缺口的旅程阶段分组，默认全选）
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {scenariosByStage.map((g) => (
                      <div key={g.stageCode}>
                        <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--navy)", marginBottom: 3 }}>
                          {g.stageCode} · {STAGE_LABEL[g.stageCode] ?? g.stageCode}
                        </div>
                        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                          {g.scenarios.map((s) => (
                            <label key={s.code} style={{ fontSize: 12, display: "flex", gap: 5, alignItems: "center", cursor: "pointer" }}>
                              <input type="checkbox" checked={selectedScenarioCodes.includes(s.code)} onChange={() => toggleScenarioCode(s.code)} disabled={isBusy} />
                              {s.name}
                            </label>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                    <button
                      onClick={() => setSelectedScenarioCodes(applicableScenarios.map((s) => s.code))}
                      disabled={isBusy}
                      style={{ border: "none", background: "none", color: "var(--ex)", fontSize: 11, cursor: "pointer", padding: 0 }}
                    >
                      全选
                    </button>
                    <button
                      onClick={() => setSelectedScenarioCodes([])}
                      disabled={isBusy}
                      style={{ border: "none", background: "none", color: "var(--ex)", fontSize: 11, cursor: "pointer", padding: 0 }}
                    >
                      全不选
                    </button>
                  </div>
                </div>
              )}
              {personas.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 5 }}>
                    为哪些画像生成多轮对话脚本（每条用例都会按选中的画像各出一套）
                  </div>
                  <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                    {personas.map((p) => (
                      <label key={p.code} style={{ fontSize: 12, display: "flex", gap: 5, alignItems: "center", cursor: "pointer" }}>
                        <input type="checkbox" checked={selectedPersonaCodes.includes(p.code)} onChange={() => togglePersonaCode(p.code)} disabled={isBusy} />
                        {p.name}
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <button
                onClick={handleRunAgentF}
                disabled={isBusy || selectedPersonaCodes.length === 0 || (applicableScenarios.length > 0 && selectedScenarioCodes.length === 0)}
                style={btnStyle(true)}
              >
                {isBusy
                  ? "运行中（可能需要几分钟）…"
                  : `运行裂点生成 Agent F（${selectedPersonaCodes.length} 个画像 × ${selectedScenarioCodes.length > 0 ? selectedScenarioCodes.length : "全部"}个场景）`}
              </button>
              {selectedPersonaCodes.length === 0 && (
                <div style={{ fontSize: 11, color: "var(--red)", marginTop: 5 }}>至少选一个画像才能生成对话脚本</div>
              )}
              {applicableScenarios.length > 0 && selectedScenarioCodes.length === 0 && selectedPersonaCodes.length > 0 && (
                <div style={{ fontSize: 11, color: "var(--red)", marginTop: 5 }}>至少选一个场景才能生成用例</div>
              )}
            </div>
          )}

          {caseDetail.cutpoints.map((cp) => (
            <div key={cp.id} style={{ border: `1px solid ${cp.enabled ? "var(--line)" : "var(--line)"}`, borderRadius: 9, marginBottom: 14, opacity: cp.enabled ? 1 : 0.5 }}>
              <div style={{ padding: "10px 14px", background: cp.provenance === "mock" ? "var(--mock-l)" : "var(--ex-l)", borderRadius: "9px 9px 0 0", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 11, fontWeight: 700 }}>{cp.stage_code}</span>
                <span style={{ fontSize: 12.5, fontWeight: 700 }}>{STAGE_LABEL[cp.stage_code] ?? cp.stage_code}</span>
                {cp.type_code && (
                  <span style={{ fontSize: 10, color: "var(--muted)" }} title="历史分类字段，新生成的裂点不再有这个标签">
                    {cp.type_code}
                  </span>
                )}
                <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--surface)", color: cp.provenance === "mock" ? "var(--mock)" : "var(--ex)" }}>
                  {cp.provenance === "real" ? "真实证据" : "推测数据"}
                </span>
                <span style={{ flex: 1 }} />
                <button onClick={() => handleToggleCutpoint(cp.id, !cp.enabled)} disabled={isBusy} style={btnStyle(false)}>
                  {cp.enabled ? "弃用整个裂点" : "恢复"}
                </button>
              </div>
              <div style={{ padding: "10px 14px", fontSize: 11.5, color: "var(--sub)" }}>未知：{cp.unknown_set.join("；")}</div>
              <div style={{ padding: "0 14px 12px" }}>
                {cp.queries.map((q) => (
                  <QueryCard
                    key={q.id}
                    caseId={caseId!}
                    documents={caseDetail.documents}
                    cutpoint={cp}
                    query={q}
                    stageLabel={STAGE_LABEL[cp.stage_code]}
                    onOpenImage={setLightboxSeq}
                    isBusy={isBusy}
                    onDecideQuery={handleDecideQuery}
                    onSelectVariant={handleSelectVariant}
                  />
                ))}
              </div>
            </div>
          ))}

          {caseDetail.cutpoints.length > 0 && (
            <button onClick={() => handleAdvance("out")} disabled={busy || acceptedQueries === 0} style={btnStyle(true)}>
              下一步：产出（已纳入 {acceptedQueries} 条）
            </button>
          )}
        </section>
      )}

      {caseDetail.current_step === "out" && (() => {
        const acceptedRows = caseDetail.cutpoints
          .filter((cp) => cp.enabled)
          .flatMap((cp) => cp.queries.filter((q) => q.decision === "accept").map((q) => ({ cp, q })));
        const byStage: Record<string, number> = {};
        const byProvenance: Record<string, number> = {};
        for (const { cp } of acceptedRows) {
          byStage[cp.stage_code] = (byStage[cp.stage_code] ?? 0) + 1;
          byProvenance[cp.provenance] = (byProvenance[cp.provenance] ?? 0) + 1;
        }

        return (
          <section>
            <h2 style={sectionTitle}>产出</h2>
            <p style={sectionLead}>已产出 {acceptedRows.length} 条测试用例，可导出到测试管理平台。下面是每条用例的完整内容——不用展开 JSON 就能确认测试目标、输入和预期结果。</p>

            {acceptedRows.length > 0 && (
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 16, padding: "10px 14px", background: "var(--card)", border: "1px solid var(--line)", borderRadius: 8 }}>
                <div>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", marginBottom: 4 }}>按旅程阶段</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {Object.entries(byStage).map(([stage, n]) => (
                      <span key={stage} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 8, background: "var(--navy-l)", color: "var(--navy)" }}>
                        {STAGE_LABEL[stage] ?? stage} × {n}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", marginBottom: 4 }}>按来源</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {Object.entries(byProvenance).map(([prov, n]) => (
                      <span key={prov} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 8, background: prov === "mock" ? "var(--mock-l)" : "var(--ex-l)", color: prov === "mock" ? "var(--mock)" : "var(--ex)" }}>
                        {prov === "mock" ? "推测数据" : "真实证据"} × {n}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
              <button onClick={() => handleDownloadExport("xlsx")} style={btnStyle(true, "var(--green)")}>
                下载 Excel（.xlsx）
              </button>
              <button onClick={() => handleDownloadExport("zip")} style={btnStyle(true, "var(--ex)")} title="每条用例一个文件夹：query 原文/多轮画像脚本、真实图片文件、标准卡（如果有）；根目录另附一份汇总 Excel">
                下载压缩包（.zip）
              </button>
              <button onClick={() => handleDownloadExport("json")} style={btnStyle(false)}>
                下载 JSON
              </button>
            </div>
            {downloadError && <div style={noteBox("var(--red)", "var(--red-l)")}>{downloadError}</div>}

            {acceptedRows.map(({ cp, q }) => (
              <QueryCard key={q.id} caseId={caseId!} documents={caseDetail.documents} cutpoint={cp} query={q} stageLabel={STAGE_LABEL[cp.stage_code]} onOpenImage={setLightboxSeq} readOnly />
            ))}

            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--sub)" }}>技术详情（原始导出 JSON，供工程排查用）</summary>
              {exportData && (
                <pre style={{ marginTop: 8, background: "#F7F7F5", border: "1px solid var(--line)", borderRadius: 7, padding: 14, fontSize: 11, maxHeight: 400, overflow: "auto" }}>
                  {JSON.stringify(exportData.test_cases, null, 2)}
                </pre>
              )}
            </details>
          </section>
        );
      })()}

      {lightboxSeq !== null && (
        <Lightbox
          caseId={caseId!}
          docs={caseDetail.documents.map((d) => ({ id: d.id, seq: d.seq, contentType: d.content_type, label: d.document_type }))}
          initialSeq={lightboxSeq}
          onClose={() => setLightboxSeq(null)}
        />
      )}
    </div>
  );
}

function noteBox(fg: string, bg: string): CSSProperties {
  return { padding: "9px 12px", borderRadius: 7, background: bg, color: fg, fontSize: 12.5, marginBottom: 14 };
}

function flagCard(severity: string): CSSProperties {
  const accent = severity === "high" ? "var(--red)" : severity === "medium" ? "var(--mock)" : "var(--muted)";
  return { border: "1px solid var(--line)", borderLeft: `4px solid ${accent}`, borderRadius: 8, padding: "12px 14px", marginBottom: 10 };
}

function strengthBadge(strength: string): CSSProperties {
  const map: Record<string, string> = { strong: "var(--green)", medium: "var(--sub)", weak: "var(--red)" };
  return { fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--surface)", color: map[strength] ?? "var(--sub)", fontWeight: 600 };
}

const sectionTitle: CSSProperties = { fontSize: 15, fontWeight: 700, margin: "0 0 4px" };
const sectionLead: CSSProperties = { fontSize: 12.5, color: "var(--sub)", margin: "0 0 14px" };
const docCard: CSSProperties = { border: "1px solid var(--line)", borderRadius: 7, padding: "9px 11px", background: "var(--card)" };
const mockCard: CSSProperties = { border: "1px dashed var(--mock-b)", background: "var(--mock-l)", borderRadius: 8, padding: "11px 14px", marginBottom: 9 };
const inlineNote: CSSProperties = { fontSize: 11.5, color: "var(--sub)", background: "var(--card)", padding: "6px 9px", borderRadius: 5, marginBottom: 8 };

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
