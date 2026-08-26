import type { CSSProperties } from "react";
import type { CutpointOut, DocumentOut, QueryOut } from "../api/types";
import { DocThumb } from "./DocThumb";

/** Full rendering of one test case (query): scenario, test direction/
 * background, the exact images sent to the tested product, expected answer
 * points, and every persona's multi-turn script. Used both in the case
 * wizard's 裂点用例 step (interactive — accept/reject, pick a variant) and
 * in the board's 用例库 detail view (read-only — just look at the thing).
 * One card, two contexts, so they never drift into showing different
 * subsets of the same data. */
export function QueryCard({
  caseId,
  documents,
  cutpoint,
  query,
  stageLabel,
  onOpenImage,
  readOnly,
  isBusy,
  onDecideQuery,
  onSelectVariant,
}: {
  caseId: string;
  documents: DocumentOut[];
  cutpoint: Pick<CutpointOut, "stage_code" | "type_code" | "provenance">;
  query: QueryOut;
  stageLabel?: string;
  onOpenImage: (seq: number) => void;
  readOnly?: boolean;
  isBusy?: boolean;
  onDecideQuery?: (queryId: string, decision: "accept" | "reject") => void;
  onSelectVariant?: (variantId: string, selected: boolean) => void;
}) {
  // test_direction 是这条用例引入多轮画像脚本之后才有的字段——早期
  // Agent F（2026-08 中旬之前）产出的是单句 query，没有方向/背景/图片
  // 引用/画像脚本这几个字段，只有 query.text 这一句话本身。用有没有
  // test_direction 判断是不是这种老格式，两种格式分开渲染，不能因为新
  // 字段是空的就把 query.text 也一起漏掉不显示——那是这条用例当时唯一
  // 生成出来的实际内容，不是可有可无的摘要。
  const isLegacyFormat = !query.test_direction;

  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 7, padding: "10px 13px", marginBottom: 8, background: "var(--card)" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, padding: "1px 8px", borderRadius: 8, background: "var(--surface)", color: "var(--sub)", fontWeight: 600 }}>
          {cutpoint.stage_code}
          {stageLabel ? ` · ${stageLabel}` : ""}
        </span>
        <span style={{ fontSize: 10, padding: "1px 8px", borderRadius: 8, background: cutpoint.provenance === "mock" ? "var(--mock-l)" : "var(--ex-l)", color: cutpoint.provenance === "mock" ? "var(--mock)" : "var(--ex)" }}>
          {cutpoint.provenance === "real" ? "真实证据" : "推测数据"}
        </span>
        <span style={{ fontSize: 10, padding: "1px 8px", borderRadius: 8, background: "var(--navy-l)", color: "var(--navy)", fontWeight: 600 }}>{query.scenario_type}</span>
        {query.has_standard_card && (
          <span style={{ fontSize: 10, padding: "1px 8px", borderRadius: 8, background: "var(--green-l, var(--surface))", color: "var(--green)", fontWeight: 600 }}>有标准卡</span>
        )}
        {isLegacyFormat && (
          <span style={{ fontSize: 10, padding: "1px 8px", borderRadius: 8, background: "var(--mock-l)", color: "var(--mock)", fontWeight: 600 }} title="这条用例由更早版本的 Agent F 生成，没有测试方向/背景/图片引用/多轮画像脚本">
            旧版格式
          </span>
        )}
      </div>

      {isLegacyFormat ? (
        <div style={{ fontSize: 12.5, fontStyle: "italic", borderLeft: "3px solid var(--mock)", paddingLeft: 10, marginBottom: 9 }}>
          {query.text}
          <div style={{ fontSize: 10.5, fontStyle: "normal", color: "var(--muted)", marginTop: 4 }}>
            这条用例生成于多轮画像脚本功能上线之前，只有这一句 query 原文，没有测试方向/背景/要发的图/画像脚本——不是缺内容，是当时的
            Agent F 就只产出这些。要补全，需要在病例工坊里对这个病例重新运行 Agent F（会替换掉这个病例现有的全部裂点用例，请谨慎操作）。
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 5 }}>{query.test_direction}</div>
      )}

      {query.test_background && (
        <div style={inlineNote}>
          <b style={{ color: "var(--muted)" }}>背景（仅供评分参考，不出现在发给产品的 query 原文里）：</b>
          {query.test_background}
        </div>
      )}

      {query.test_image_seqs.length > 0 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 9, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10.5, color: "var(--sub)" }}>随 query 发送：</span>
          {query.test_image_seqs.map((seq) => {
            const doc = documents.find((d) => d.seq === seq);
            return doc ? (
              <DocThumb key={seq} caseId={caseId} documentId={doc.id} contentType={doc.content_type} size={34} onClick={() => onOpenImage(seq)} />
            ) : (
              <span key={seq} style={{ fontSize: 10, color: "var(--muted)" }}>DOC-{String(seq).padStart(2, "0")}</span>
            );
          })}
          {query.test_image_note && <span style={{ fontSize: 10.5, color: "var(--muted)" }}>（{query.test_image_note}）</span>}
        </div>
      )}

      <details style={{ fontSize: 11.5, color: "var(--sub)", marginBottom: 9 }}>
        <summary style={{ cursor: "pointer" }}>预期答题要点（{query.expected_answer_points.length}）</summary>
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {query.expected_answer_points.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      </details>

      {query.red_line_watch.length > 0 && (
        <details style={{ fontSize: 11.5, color: "var(--sub)", marginBottom: 9 }}>
          <summary style={{ cursor: "pointer" }}>红线关注点（{query.red_line_watch.length}）</summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {query.red_line_watch.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </details>
      )}

      {query.variants.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 8, marginBottom: 10 }}>
          {query.variants.map((v) => (
            <div key={v.id} style={variantCard(v.selected)}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6, marginBottom: 3 }}>
                <span style={{ fontSize: 11, fontWeight: 700 }}>{v.persona_name ?? v.persona_code}</span>
                {!readOnly && onSelectVariant && (
                  <button onClick={() => onSelectVariant(v.id, !v.selected)} disabled={isBusy} style={btnStyle(v.selected, "var(--ex)")}>
                    {v.selected ? "已选用" : "选用"}
                  </button>
                )}
                {readOnly && v.selected && (
                  <span style={{ fontSize: 9.5, fontWeight: 700, color: "var(--ex)" }}>已选用</span>
                )}
              </div>
              {v.persona_note && <div style={{ fontSize: 10.5, color: "var(--sub)", marginBottom: 6 }}>{v.persona_note}</div>}
              {v.turns.map((t) => (
                <div key={t.round} style={{ marginBottom: 5 }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: "var(--muted)" }}>第 {t.round} 轮</div>
                  {t.messages.map((m, i) => (
                    <div key={i} style={{ fontSize: 11.5, borderLeft: "2px solid var(--ex)", paddingLeft: 7, marginTop: 2 }}>
                      {m}
                    </div>
                  ))}
                </div>
              ))}
              <div style={{ fontSize: 10.5, color: "var(--sub)", fontStyle: "italic", marginTop: 4 }}>行为逻辑：{v.behavior_logic}</div>
            </div>
          ))}
        </div>
      )}

      {!readOnly && onDecideQuery && (
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => onDecideQuery(query.id, "accept")} disabled={isBusy} style={btnStyle(query.decision === "accept", "var(--green)")}>
            纳入
          </button>
          <button onClick={() => onDecideQuery(query.id, "reject")} disabled={isBusy} style={btnStyle(query.decision === "reject", "var(--red)")}>
            不纳入
          </button>
        </div>
      )}
      {readOnly && (
        <span style={{ fontSize: 10.5, padding: "1px 8px", borderRadius: 8, background: query.decision === "accept" ? "var(--green-l)" : "var(--red-l)", color: query.decision === "accept" ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
          {query.decision === "accept" ? "已纳入" : "未纳入"}
        </span>
      )}
      {query.decision === "reject" && query.reject_reason && (
        <div style={{ fontSize: 10.5, color: "var(--muted)", marginTop: 4 }}>不纳入原因：{query.reject_reason}</div>
      )}
    </div>
  );
}

const inlineNote: CSSProperties = { fontSize: 11.5, color: "var(--sub)", background: "var(--surface)", padding: "6px 9px", borderRadius: 5, marginBottom: 8 };

function variantCard(selected: boolean): CSSProperties {
  return {
    border: `1px solid ${selected ? "var(--ex)" : "var(--line)"}`,
    background: selected ? "var(--ex-l)" : "var(--surface)",
    borderRadius: 7,
    padding: "8px 10px",
  };
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
