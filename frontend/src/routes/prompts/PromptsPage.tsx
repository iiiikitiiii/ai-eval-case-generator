import { useCallback, useEffect, useState, type CSSProperties, type FormEvent } from "react";
import {
  createPersona,
  createScenarioType,
  createVersion,
  listAgents,
  listPersonas,
  listRegressionCases,
  listScenarioTypes,
  listVersions,
  publishVersion,
  runRegression,
  sandboxRun,
  updatePersona,
  updateScenarioType,
  type RegressionCaseOut,
  type RegressionRunOut,
  type ScenarioTypeInput,
  type UserPersonaInput,
} from "../../shared/api/agents";
import { listCases } from "../../shared/api/cases";
import { ApiError } from "../../shared/api/client";
import type { AgentCode, AgentOut, AgentVersionOut, CaseListItem, ScenarioTypeOut, UserPersonaOut } from "../../shared/api/types";
import { RunningProgress } from "../../shared/ui/RunningProgress";

const KIND_LABEL: Record<string, string> = {
  prereq: "前置 · 人工维护",
  extract: "抽取 · 零编造",
  fabricate: "编造 · 唯一允许",
  generate: "生成 · 最终产物",
};

// 业务方场景库真实使用的六阶段旅程，不是早期版本发明的 J01-J08。
const STAGES = ["J01", "J02", "J03", "J04", "J05", "J06"];

export function PromptsPage() {
  const [tab, setTab] = useState<"prompt" | "scenario" | "persona">("prompt");
  return (
    <div style={{ padding: "24px 32px 60px" }}>
      <h1 style={{ fontSize: 19, fontWeight: 700, margin: "0 0 4px" }}>Prompt 维护后台</h1>
      <p style={{ fontSize: 12.5, color: "var(--sub)", margin: "0 0 18px" }}>
        保存即建新草稿，发布即时生效——没有审批流，安全网是版本历史随时可回滚。
      </p>

      <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: "1px solid var(--line)" }}>
        {[
          { key: "prompt" as const, label: "Prompt 编辑器" },
          { key: "scenario" as const, label: "场景库" },
          { key: "persona" as const, label: "用户画像库" },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: "8px 16px",
              border: "none",
              borderBottom: `2px solid ${tab === t.key ? "var(--navy)" : "transparent"}`,
              background: "none",
              color: tab === t.key ? "var(--navy)" : "var(--sub)",
              fontWeight: tab === t.key ? 700 : 500,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "prompt" && <PromptEditor />}
      {tab === "scenario" && <ScenarioLibrary />}
      {tab === "persona" && <PersonaLibrary />}
    </div>
  );
}

function PromptEditor() {
  const [agents, setAgents] = useState<AgentOut[] | null>(null);
  const [selected, setSelected] = useState<AgentCode | null>(null);
  const [versions, setVersions] = useState<AgentVersionOut[] | null>(null);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [promptDraft, setPromptDraft] = useState("");
  const [checksDraft, setChecksDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [sandboxCaseId, setSandboxCaseId] = useState("");
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [sandboxElapsed, setSandboxElapsed] = useState(0);
  const [sandboxResult, setSandboxResult] = useState<string | null>(null);
  const [sandboxError, setSandboxError] = useState<string | null>(null);

  useEffect(() => {
    if (!sandboxBusy) return;
    setSandboxElapsed(0);
    const t = setInterval(() => setSandboxElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [sandboxBusy]);

  const [regressionCases, setRegressionCases] = useState<RegressionCaseOut[]>([]);
  const [regressionRuns, setRegressionRuns] = useState<RegressionRunOut[] | null>(null);
  const [regressionBusy, setRegressionBusy] = useState(false);

  useEffect(() => {
    listAgents()
      .then((a) => {
        setAgents(a);
        if (!selected && a.length) setSelected(a[0].code);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载 Agent 列表失败"));
    listCases().then(setCases).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    setRegressionRuns(null);
    listRegressionCases(selected).then(setRegressionCases).catch(() => setRegressionCases([]));
  }, [selected]);

  const loadVersions = useCallback(() => {
    if (!selected) return;
    listVersions(selected).then((vs) => {
      setVersions(vs);
      const active = vs.find((v) => v.status === "published") ?? vs[0];
      if (active) {
        setActiveVersionId(active.id);
        setPromptDraft(active.prompt_text);
        setChecksDraft(active.checks.join("\n"));
      } else {
        setActiveVersionId(null);
        setPromptDraft("");
        setChecksDraft("");
      }
    });
  }, [selected]);

  useEffect(loadVersions, [loadVersions]);

  function selectVersion(v: AgentVersionOut) {
    setActiveVersionId(v.id);
    setPromptDraft(v.prompt_text);
    setChecksDraft(v.checks.join("\n"));
    setInfo(null);
    setError(null);
  }

  async function handleSaveDraft() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const currentSchema = versions?.find((v) => v.id === activeVersionId)?.out_schema ?? null;
      const checks = checksDraft.split("\n").map((s) => s.trim()).filter(Boolean);
      const created = await createVersion(selected, promptDraft, checks, currentSchema);
      setInfo(`已保存为 ${created.version_label}（草稿，尚未发布）`);
      loadVersions();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function handlePublish(versionId: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const published = await publishVersion(selected, versionId);
      setInfo(`${published.version_label} 已发布，下一次运行这个 Agent 就会用它`);
      const a = await listAgents();
      setAgents(a);
      loadVersions();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSandboxRun() {
    if (!selected || !sandboxCaseId) return;
    setSandboxBusy(true);
    setSandboxError(null);
    setSandboxResult(null);
    try {
      const currentSchema = versions?.find((v) => v.id === activeVersionId)?.out_schema ?? null;
      const { result } = await sandboxRun(selected, sandboxCaseId, promptDraft, currentSchema);
      setSandboxResult(JSON.stringify(result, null, 2));
    } catch (err) {
      setSandboxError(err instanceof ApiError ? err.message : "沙盒试跑失败");
    } finally {
      setSandboxBusy(false);
    }
  }

  async function handleRunRegression() {
    if (!selected || !activeVersionId) return;
    setRegressionBusy(true);
    setError(null);
    try {
      const runs = await runRegression(selected, activeVersionId);
      setRegressionRuns(runs);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "回归测试运行失败");
    } finally {
      setRegressionBusy(false);
    }
  }

  const activeVersion = versions?.find((v) => v.id === activeVersionId);
  const isDirty = activeVersion ? activeVersion.prompt_text !== promptDraft || activeVersion.checks.join("\n") !== checksDraft : false;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 20 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {agents?.map((a) => (
          <button
            key={a.code}
            onClick={() => setSelected(a.code)}
            style={{
              textAlign: "left",
              padding: "9px 12px",
              borderRadius: 7,
              border: "1px solid var(--line)",
              background: selected === a.code ? "var(--navy-l)" : "var(--surface)",
              cursor: "pointer",
            }}
          >
            <div style={{ fontSize: 12.5, fontWeight: 700, color: selected === a.code ? "var(--navy)" : "var(--text)" }}>
              {a.code} · {a.name.replace(" Agent", "")}
            </div>
            <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>{KIND_LABEL[a.kind]}</div>
            <div style={{ fontSize: 10, color: "var(--green)", marginTop: 2 }}>
              {a.published_version_label ? `已发布 ${a.published_version_label}` : "尚未发布"}
            </div>
          </button>
        ))}
      </div>

      <div>
        {error && <div style={noteBox("var(--red)", "var(--red-l)")}>{error}</div>}
        {info && <div style={noteBox("var(--green)", "var(--green-l)")}>{info}</div>}

        {versions && versions.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
            {versions.map((v) => (
              <button
                key={v.id}
                onClick={() => selectVersion(v)}
                style={{
                  padding: "4px 11px",
                  borderRadius: 12,
                  border: `1px solid ${v.id === activeVersionId ? "var(--navy)" : "var(--line)"}`,
                  background: v.id === activeVersionId ? "var(--navy)" : v.status === "published" ? "var(--green-l)" : "var(--surface)",
                  color: v.id === activeVersionId ? "#fff" : v.status === "published" ? "var(--green)" : "var(--sub)",
                  fontSize: 11.5,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {v.version_label}
                {v.status === "published" && " ✓"}
              </button>
            ))}
          </div>
        )}

        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", marginBottom: 5 }}>
          Prompt{activeVersion?.status === "published" && "（当前发布版）"}
        </div>
        <textarea
          value={promptDraft}
          onChange={(e) => setPromptDraft(e.target.value)}
          rows={16}
          style={textareaStyle}
        />

        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", margin: "14px 0 5px" }}>
          自动校验规则（每行一条）
        </div>
        <textarea value={checksDraft} onChange={(e) => setChecksDraft(e.target.value)} rows={5} style={{ ...textareaStyle, fontFamily: "inherit" }} />

        <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
          <button onClick={handleSaveDraft} disabled={busy || !isDirty} style={btnStyle(true)}>
            {busy ? "处理中…" : "保存为新草稿"}
          </button>
          {activeVersion && activeVersion.status !== "published" && (
            <button onClick={() => handlePublish(activeVersion.id)} disabled={busy} style={btnStyle(true, "var(--green)")}>
              发布 {activeVersion.version_label}
            </button>
          )}
          {!isDirty && activeVersion?.status === "published" && (
            <span style={{ fontSize: 11.5, color: "var(--muted)" }}>这就是当前生产版本</span>
          )}
        </div>

        <div style={{ marginTop: 26, paddingTop: 18, borderTop: "1px solid var(--line)" }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 6 }}>沙盒试跑</div>
          <p style={{ fontSize: 11.5, color: "var(--sub)", margin: "0 0 10px" }}>
            拿上面文本框里的草稿内容（不用先保存），对一个真实病例的真实数据跑一次预览，不写入任何数据库。
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
            <select value={sandboxCaseId} onChange={(e) => setSandboxCaseId(e.target.value)} style={inputStyle}>
              <option value="">选择一个病例…</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.case_no} · {(c.patient_meta.name as string) ?? "未命名"}
                </option>
              ))}
            </select>
            <button onClick={handleSandboxRun} disabled={sandboxBusy || !sandboxCaseId} style={btnStyle(true, "var(--ex)")}>
              {sandboxBusy ? "运行中（可能需要几分钟）…" : "用当前草稿试跑"}
            </button>
          </div>
          {sandboxBusy && <RunningProgress label={`Agent ${selected} 沙盒试跑`} elapsed={sandboxElapsed} />}
          {sandboxError && <div style={noteBox("var(--red)", "var(--red-l)")}>{sandboxError}</div>}
          {sandboxResult && (
            <pre style={{ background: "#F7F7F5", border: "1px solid var(--line)", borderRadius: 7, padding: 12, fontSize: 11, maxHeight: 340, overflow: "auto" }}>
              {sandboxResult}
            </pre>
          )}
        </div>

        <div style={{ marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--line)" }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 6 }}>回归测试</div>
          <p style={{ fontSize: 11.5, color: "var(--sub)", margin: "0 0 10px" }}>
            金标准病例 + 机械可判定的断言，针对当前选中的版本（不是草稿文本框）跑一遍——发布前的门禁。
          </p>
          {regressionCases.length === 0 ? (
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>这个 Agent 还没有配置回归用例。</div>
          ) : (
            <>
              <div style={{ fontSize: 11.5, color: "var(--sub)", marginBottom: 8 }}>
                {regressionCases.length} 个回归用例，针对 {activeVersion?.version_label ?? "—"}
              </div>
              <button onClick={handleRunRegression} disabled={regressionBusy || !activeVersionId} style={btnStyle(true)}>
                {regressionBusy ? "运行中…" : `运行回归测试（${regressionCases.length} 条）`}
              </button>
              {regressionRuns && (
                <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                  {regressionRuns.map((r) => (
                    <div key={r.id} style={{ border: `1px solid ${r.status === "pass" ? "var(--green-b)" : "var(--red-b)"}`, borderRadius: 7, padding: "9px 12px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 8px", borderRadius: 8, color: r.status === "pass" ? "var(--green)" : "var(--red)", background: r.status === "pass" ? "var(--green-l)" : "var(--red-l)" }}>
                          {r.status === "pass" ? "PASS" : "FAIL"}
                        </span>
                        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{r.regression_case_name}</span>
                      </div>
                      {r.details.error && <div style={{ fontSize: 11.5, color: "var(--red)", marginTop: 5 }}>{r.details.error}</div>}
                      {r.details.assertions?.map((a, i) => (
                        <div key={i} style={{ fontSize: 11, color: a.passed ? "var(--sub)" : "var(--red)", marginTop: 4 }}>
                          {a.passed ? "✓" : "✗"} {a.description}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ScenarioLibrary() {
  const [items, setItems] = useState<ScenarioTypeOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  function reload() {
    listScenarioTypes()
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载场景库失败"));
  }
  useEffect(reload, []);

  async function handleToggleActive(id: string, active: boolean) {
    await updateScenarioType(id, { active });
    reload();
  }

  async function handleCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const stages = STAGES.filter((s) => fd.get(`stage_${s}`));
    const data: ScenarioTypeInput = {
      code: String(fd.get("code")),
      name: String(fd.get("name")),
      axis: fd.get("axis") === "peer" ? "peer" : "patient",
      journey_stages: stages,
      feature_scenario: String(fd.get("feature_scenario") || "") || null,
      description: String(fd.get("description") || "") || null,
    };
    try {
      await createScenarioType(data);
      setShowForm(false);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "新增失败");
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <p style={{ fontSize: 12.5, color: "var(--sub)", margin: 0, maxWidth: 600 }}>
          journey × 测试场景（患者视角需求）× 产品功能场景三维映射，Agent F 生成 query 时据此选用场景类型。
        </p>
        <button onClick={() => setShowForm((v) => !v)} style={btnStyle(true)}>
          {showForm ? "取消" : "+ 新增场景类型"}
        </button>
      </div>

      {error && <div style={noteBox("var(--red)", "var(--red-l)")}>{error}</div>}

      {showForm && (
        <form onSubmit={handleCreate} style={{ border: "1px solid var(--line)", borderRadius: 9, padding: 16, marginBottom: 16, display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 120px", gap: 10 }}>
            <input name="code" placeholder="code（英文，唯一）" required style={inputStyle} />
            <input name="name" placeholder="测试场景名称" required style={inputStyle} />
            <select name="axis" style={inputStyle}>
              <option value="patient">patient</option>
              <option value="peer">peer</option>
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>适用 journey 阶段</div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {STAGES.map((s) => (
                <label key={s} style={{ fontSize: 12, display: "flex", gap: 4, alignItems: "center" }}>
                  <input type="checkbox" name={`stage_${s}`} /> {s}
                </label>
              ))}
            </div>
          </div>
          <input name="feature_scenario" placeholder="对应产品功能场景" style={inputStyle} />
          <textarea name="description" placeholder="说明" rows={2} style={{ ...inputStyle, fontFamily: "inherit" }} />
          <button type="submit" style={{ ...btnStyle(true), justifySelf: "start" }}>
            创建
          </button>
        </form>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items?.map((it) => (
          <div key={it.id} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "10px 14px", opacity: it.active ? 1 : 0.5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--muted)" }}>
                {it.code}
                {it.scenario_number !== null && ` · #${it.scenario_number}`}
              </span>
              <span style={{ fontSize: 13, fontWeight: 700 }}>{it.name}</span>
              {it.source && <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--navy-l)", color: "var(--navy)" }}>{it.source}</span>}
              {it.consultation_volume !== null && (
                <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--green-l)", color: "var(--green)" }}>咨询量 {it.consultation_volume}</span>
              )}
              {it.has_standard_card && (
                <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--ex-l)", color: "var(--ex)" }}>有标准卡</span>
              )}
              {it.feature_scenario && <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--ex-l)", color: "var(--ex)" }}>{it.feature_scenario}</span>}
              <span style={{ flex: 1 }} />
              <button onClick={() => handleToggleActive(it.id, !it.active)} style={btnStyle(false)}>
                {it.active ? "停用" : "启用"}
              </button>
            </div>
            <div style={{ fontSize: 11, color: "var(--sub)", marginTop: 4 }}>{it.journey_stages.join(" · ")}</div>
            {it.description && <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: 4 }}>{it.description}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = { patient: "患者本人", family: "患者家属" };
const COGNITION_LABEL: Record<string, string> = { low: "低认知", high: "较高认知" };

function PersonaLibrary() {
  const [items, setItems] = useState<UserPersonaOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  function reload() {
    listPersonas()
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载画像库失败"));
  }
  useEffect(reload, []);

  async function handleToggleActive(id: string, active: boolean) {
    await updatePersona(id, { active });
    reload();
  }

  async function handleCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const data: UserPersonaInput = {
      code: String(fd.get("code")),
      role: fd.get("role") === "family" ? "family" : "patient",
      cognition: fd.get("cognition") === "high" ? "high" : "low",
      name: String(fd.get("name")),
      behavior_guideline: String(fd.get("behavior_guideline") || ""),
    };
    try {
      await createPersona(data);
      setShowForm(false);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "新增失败");
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <p style={{ fontSize: 12.5, color: "var(--sub)", margin: 0, maxWidth: 600 }}>
          Agent F 生成裂点用例时，从这里挑的画像（患者/家属 × 低/较高认知）写多轮对话脚本——「行为准则」是
          写给模型看的通用指引，具体到某条用例的表现由 F 自己在此基础上展开。触发 F 运行时可以只选其中几个。
        </p>
        <button onClick={() => setShowForm((v) => !v)} style={btnStyle(true)}>
          {showForm ? "取消" : "+ 新增画像"}
        </button>
      </div>

      {error && <div style={noteBox("var(--red)", "var(--red-l)")}>{error}</div>}

      {showForm && (
        <form onSubmit={handleCreate} style={{ border: "1px solid var(--line)", borderRadius: 9, padding: 16, marginBottom: 16, display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10 }}>
            <input name="code" placeholder="code（英文，唯一）" required style={inputStyle} />
            <input name="name" placeholder="展示名称" required style={inputStyle} />
            <select name="role" style={inputStyle}>
              <option value="patient">患者本人</option>
              <option value="family">患者家属</option>
            </select>
            <select name="cognition" style={inputStyle}>
              <option value="low">低认知</option>
              <option value="high">较高认知</option>
            </select>
          </div>
          <textarea name="behavior_guideline" placeholder="行为准则——这个画像会怎么提问、怎么理解信息、语气如何" rows={3} required style={{ ...inputStyle, fontFamily: "inherit" }} />
          <button type="submit" style={{ ...btnStyle(true), justifySelf: "start" }}>
            创建
          </button>
        </form>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items?.map((it) => (
          <div key={it.id} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: "10px 14px", opacity: it.active ? 1 : 0.5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--muted)" }}>{it.code}</span>
              <span style={{ fontSize: 13, fontWeight: 700 }}>{it.name}</span>
              <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--navy-l)", color: "var(--navy)" }}>
                {ROLE_LABEL[it.role] ?? it.role}
              </span>
              <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 8, background: "var(--ex-l)", color: "var(--ex)" }}>
                {COGNITION_LABEL[it.cognition] ?? it.cognition}
              </span>
              <span style={{ flex: 1 }} />
              <button onClick={() => handleToggleActive(it.id, !it.active)} style={btnStyle(false)}>
                {it.active ? "停用" : "启用"}
              </button>
            </div>
            <div style={{ fontSize: 11.5, color: "var(--sub)", marginTop: 5 }}>{it.behavior_guideline}</div>
          </div>
        ))}
        {items?.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>还没有配置任何画像。</div>}
      </div>
    </div>
  );
}

function noteBox(fg: string, bg: string): CSSProperties {
  return { padding: "9px 12px", borderRadius: 7, background: bg, color: fg, fontSize: 12.5, marginBottom: 14 };
}

const textareaStyle: CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: 7,
  border: "1px solid var(--line)",
  background: "var(--card)",
  color: "var(--text)",
  fontSize: 12.5,
  lineHeight: 1.6,
  fontFamily: "var(--font-mono)",
  resize: "vertical",
};

const inputStyle: CSSProperties = {
  padding: "7px 9px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--surface)",
  fontSize: 12.5,
  fontFamily: "inherit",
};

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
