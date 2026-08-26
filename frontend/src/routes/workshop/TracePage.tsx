import { useEffect, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { getPipelineRuns } from "../../shared/api/cases";
import { ApiError } from "../../shared/api/client";
import type { PipelineRunOut } from "../../shared/api/types";
import { RunningProgress } from "../../shared/ui/RunningProgress";

const STATUS_STYLE: Record<string, { label: string; fg: string; bg: string }> = {
  queued: { label: "排队中", fg: "var(--muted)", bg: "var(--card)" },
  running: { label: "运行中", fg: "var(--ex)", bg: "var(--ex-l)" },
  succeeded: { label: "成功", fg: "var(--green)", bg: "var(--green-l)" },
  failed: { label: "失败", fg: "var(--red)", bg: "var(--red-l)" },
};

const AGENT_LABEL: Record<string, string> = {
  S0: "S0 · 场景库",
  A: "A · 病例解析",
  B: "B · 旅程坐标映射",
  C: "C · 组合抽取",
  D: "D · 补丁",
  F: "F · 裂点与场景匹配",
};

// RunningProgress 按这几个 label 查历史耗时区间——跟病例工坊触发运行时
// 用的是同一份 key，这里复用同一个组件，不是另外画一条进度条。
const AGENT_RUN_LABEL: Record<string, string> = {
  A: "Agent A 抽取",
  B: "Agent B 阶段映射",
  C: "Agent C 组合抽取",
  D: "Agent D 补丁",
  F: "Agent F 裂点生成",
};

export function TracePage() {
  const { caseId } = useParams<{ caseId: string }>();
  const [runs, setRuns] = useState<PipelineRunOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  function reload() {
    if (!caseId) return;
    setError(null);
    getPipelineRuns(caseId)
      .then(setRuns)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载运行记录失败"));
  }

  useEffect(reload, [caseId]);

  const hasActive = runs?.some((r) => r.status === "queued" || r.status === "running") ?? false;

  // 之前这个页面只在手动点「刷新」时更新——运行中的那一行会一直停在
  // "运行中"不动，看着就像卡住了，跟病例工坊那边已经修过的问题是同一个。
  // 只要还有排队/运行中的记录就自动轮询，没有的话就不空转。
  useEffect(() => {
    if (!hasActive) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasActive, caseId]);

  useEffect(() => {
    if (!hasActive) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [hasActive]);

  return (
    <div style={{ padding: "24px 32px 60px", maxWidth: 820 }}>
      <Link to={`/workshop/${caseId}`} style={{ fontSize: 12.5, color: "var(--sub)" }}>
        ← 返回病例
      </Link>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "10px 0 18px" }}>
        <div>
          <h1 style={{ fontSize: 19, fontWeight: 700, margin: 0 }}>运行记录</h1>
          <p style={{ fontSize: 12.5, color: "var(--sub)", margin: "3px 0 0" }}>
            每一次 Agent 调用的审计轨迹——哪个环节、用了哪个 prompt 版本、跑了多久、失败原因是什么。
          </p>
        </div>
        <button onClick={reload} style={refreshBtn}>
          刷新
        </button>
      </div>

      {error && <div style={{ color: "var(--red)", fontSize: 12.5, marginBottom: 14 }}>{error}</div>}
      {runs === null && !error && <div style={{ color: "var(--muted)", fontSize: 13 }}>加载中…</div>}
      {runs?.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>这个病例还没有任何 Agent 运行记录。</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {runs?.map((r) => {
          const s = STATUS_STYLE[r.status] ?? { label: r.status, fg: "var(--sub)", bg: "var(--card)" };
          return (
            <div
              key={r.id}
              style={{
                border: "1px solid var(--line)",
                borderLeft: `4px solid ${s.fg}`,
                borderRadius: 8,
                padding: "11px 14px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, fontWeight: 700 }}>{AGENT_LABEL[r.agent_code] ?? r.agent_code}</span>
                {r.agent_version_label && (
                  <span style={{ fontSize: 10.5, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>
                    {r.agent_version_label}
                  </span>
                )}
                <span style={{ padding: "1px 9px", borderRadius: 9, fontSize: 10.5, fontWeight: 600, color: s.fg, background: s.bg }}>
                  {s.label}
                </span>
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  {new Date(r.created_at).toLocaleString("zh-CN")}
                  {r.duration_seconds !== null && ` · 耗时 ${r.duration_seconds}s`}
                  {r.token_usage?.total_tokens != null && ` · ${r.token_usage.total_tokens.toLocaleString()} tokens（${r.token_usage.provider}）`}
                </span>
              </div>

              {r.status === "running" && r.started_at && (
                <div style={{ marginTop: 8 }}>
                  <RunningProgress
                    label={AGENT_RUN_LABEL[r.agent_code] ?? r.agent_code}
                    elapsed={Math.max(0, Math.round((now - new Date(r.started_at).getTime()) / 1000))}
                    note={r.progress_note}
                  />
                </div>
              )}

              {r.status === "failed" && r.error && (
                <div style={{ marginTop: 8, padding: "8px 11px", borderRadius: 6, background: "var(--red-l)", color: "var(--red)", fontSize: 12 }}>
                  {r.error}
                </div>
              )}

              {r.status === "succeeded" && r.output_ref && (
                <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--sub)" }}>
                  {Object.entries(r.output_ref)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const refreshBtn: CSSProperties = {
  padding: "6px 13px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--surface)",
  color: "var(--sub)",
  fontSize: 12,
  cursor: "pointer",
};
