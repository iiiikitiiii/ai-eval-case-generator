import { useState, type CSSProperties } from "react";

/** LLM 调用没有真实的百分比可用，纯文字的"运行中，已等待 Ns"在长任务
 * （F 实测跑到 5 分钟）上焦虑感很重——像卡住了。这里按每个 Agent 历史
 * 观察到的真实耗时区间做一条"乐观进度条"：不撒谎说"已完成 X%"，但用条形
 * 的持续推进 + 预期区间给出"还在正常处理、大概多久"的手感。封顶在 92%，
 * 永远留出"最后一段在收尾"的空间，直到真正拿到终态。
 *
 * note（可选）是模型流式吐出来的 reasoning_content 滚动快照——不是伪造的
 * 进度百分比，是真的能看到模型这一刻在想什么，比进度条本身更能打消"卡住
 * 了吗"的疑虑。minimax/kimi 才有；没传就只显示进度条。
 *
 * 默认收起，只显示最新一行的尾部（用 direction:rtl 的技巧让省略号出现在
 * 左边，露出的是最近发生的内容，不是开头）——点一下展开成一个有自己滚动条
 * 的大块，不是强加一个固定 90px 的小滑窗逼着用户在里面滚。 */

export const AGENT_EXPECTED_SECONDS: Record<string, [number, number]> = {
  "Agent A 抽取": [20, 160],
  "Agent B 阶段映射": [30, 150],
  "Agent C 组合抽取": [20, 90],
  "Agent D 补丁": [10, 90],
  "Agent F 裂点生成": [40, 320],
};
const DEFAULT_RANGE: [number, number] = [20, 150];

export function RunningProgress({ label, elapsed, note }: { label: string; elapsed: number; note?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const [minS, maxS] = AGENT_EXPECTED_SECONDS[label] ?? DEFAULT_RANGE;
  const pct = Math.max(4, Math.min(92, (elapsed / maxS) * 100));
  const overtime = elapsed > maxS;

  return (
    <div style={{ padding: "10px 12px", borderRadius: 7, background: "var(--ex-l)", marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, fontSize: 12.5, color: "var(--ex)", marginBottom: 7 }}>
        <span style={{ fontWeight: 600 }}>{label} 运行中…</span>
        <span style={{ fontSize: 11, whiteSpace: "nowrap" }}>
          已等待 {elapsed}s
          {overtime ? "（比预期久一些，通常还在正常处理，可以再等等）" : ` · 预计 ${minS}–${maxS}s，可以离开页面`}
        </span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--ex-b)", overflow: "hidden" }}>
        <div style={barStyle(pct)} />
      </div>
      {note && (
        <div style={{ marginTop: 8, borderRadius: 5, background: "var(--surface)", border: "1px solid var(--ex-b)", overflow: "hidden" }}>
          <button
            onClick={() => setExpanded((v) => !v)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 9px",
              border: "none",
              background: "none",
              cursor: "pointer",
              textAlign: "left",
              font: "inherit",
            }}
          >
            <span style={{ fontSize: 9.5, fontWeight: 700, color: "var(--ex)", textTransform: "uppercase", flexShrink: 0 }}>
              模型正在想
            </span>
            {!expanded && (
              <span
                style={{
                  flex: 1,
                  minWidth: 0,
                  fontSize: 11,
                  color: "var(--muted)",
                  fontFamily: "var(--font-mono)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  direction: "rtl",
                  textAlign: "left",
                }}
              >
                {note}
              </span>
            )}
            <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--ex)", flexShrink: 0 }}>{expanded ? "收起 ▲" : "展开 ▼"}</span>
          </button>
          {expanded && (
            <div
              style={{
                padding: "0 9px 9px",
                fontSize: 11,
                color: "var(--sub)",
                lineHeight: 1.5,
                maxHeight: 360,
                overflow: "auto",
                fontFamily: "var(--font-mono)",
                whiteSpace: "pre-wrap",
              }}
            >
              {note}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function barStyle(pct: number): CSSProperties {
  return {
    height: "100%",
    width: `${pct}%`,
    borderRadius: 3,
    background: "var(--ex)",
    backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,0.35) 0 8px, transparent 8px 16px)",
    backgroundSize: "28px 28px",
    animation: "progress-stripe 0.9s linear infinite",
    transition: "width 0.6s ease",
  };
}
