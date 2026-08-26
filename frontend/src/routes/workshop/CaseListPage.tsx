import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createCase, listCases } from "../../shared/api/cases";
import { ApiError } from "../../shared/api/client";
import type { CaseListItem, CaseStatus } from "../../shared/api/types";

const STATUS_LABEL: Record<string, { label: string; fg: string; bg: string }> = {
  queued: { label: "待处理", fg: "var(--sub)", bg: "var(--card)" },
  extracting: { label: "抽取中", fg: "var(--ex)", bg: "var(--ex-l)" },
  reviewing_flags: { label: "核对冲突", fg: "var(--mock)", bg: "var(--mock-l)" },
  staging: { label: "阶段裁定", fg: "var(--navy)", bg: "var(--navy-l)" },
  mock_review: { label: "推测抽查", fg: "var(--mock)", bg: "var(--mock-l)" },
  cutpoint_review: { label: "裂点用例", fg: "var(--navy)", bg: "var(--navy-l)" },
  exported: { label: "已产出", fg: "var(--green)", bg: "var(--green-l)" },
  blocked: { label: "已阻塞", fg: "var(--red)", bg: "var(--red-l)" },
};

// P1「病例队列支持日常检索与优先级处理」：状态筛选下拉的选项——不是照抄
// CaseStatus 枚举全部值，是需求文档里点名的那几档业务口径（待导入/待人工
// 裁定/运行中/运行失败/已产出），跟 STATUS_LABEL 共用同一套中文，但這里
// 只挑体验人员真的会拿来筛选的几个。
const STATUS_FILTER_OPTIONS: { value: CaseStatus | ""; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "queued", label: "待导入" },
  { value: "reviewing_flags", label: "待人工裁定 · 核对冲突" },
  { value: "staging", label: "待人工裁定 · 阶段裁定" },
  { value: "mock_review", label: "待人工裁定 · 推测抽查" },
  { value: "cutpoint_review", label: "待人工裁定 · 裂点用例" },
  { value: "blocked", label: "运行失败" },
  { value: "exported", label: "已产出" },
];

export function CaseListPage() {
  const [cases, setCases] = useState<CaseListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<CaseStatus | "">("");
  const navigate = useNavigate();

  function reload() {
    listCases({ status: statusFilter || undefined, search: search.trim() || undefined })
      .then(setCases)
      .catch((err) => setError(err instanceof ApiError ? err.message : "加载病例列表失败"));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, [statusFilter]);

  useEffect(() => {
    const t = setTimeout(reload, 300); // 搜索框防抖，不用每敲一个字就打一次接口
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function handleCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const meta = {
      name: data.get("name") || undefined,
      gender: data.get("gender") || undefined,
      age: data.get("age") || undefined,
      dx: data.get("dx") || undefined,
      hospital: data.get("hospital") || undefined,
    };
    const alias = (data.get("alias") as string) || undefined;
    try {
      const created = await createCase(meta, alias);
      navigate(`/workshop/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "新建病例失败");
    }
  }

  return (
    <div style={{ padding: "32px 32px 60px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>病例工坊</h1>
          <div style={{ fontSize: 12.5, color: "var(--sub)", marginTop: 3 }}>待处理 / 复核中 / 已产出病例队列</div>
        </div>
        <button onClick={() => setShowForm((v) => !v)} style={primaryBtn}>
          {showForm ? "取消" : "+ 新建病例"}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleCreate}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(6, 1fr)",
            gap: 10,
            padding: 16,
            marginBottom: 18,
            border: "1px solid var(--line)",
            borderRadius: 10,
            background: "var(--card)",
          }}
        >
          <input name="name" placeholder="姓名" style={inputStyle} />
          <input name="gender" placeholder="性别" style={inputStyle} />
          <input name="age" placeholder="年龄" style={inputStyle} />
          <input name="dx" placeholder="初步诊断" style={inputStyle} />
          <input name="hospital" placeholder="医院" style={inputStyle} />
          <input name="alias" placeholder="病例别名（可选，便于检索）" style={inputStyle} />
          <div style={{ gridColumn: "span 6", fontSize: 11, color: "var(--muted)", marginTop: -4 }}>
            病例别名是团队内部检索用的非敏感标签（如「糖尿病-张阿姨」），不填的话之后只能用病例编号找到这条记录。
          </div>
          <button type="submit" style={{ ...primaryBtn, gridColumn: "span 6" }}>
            创建并进入导入
          </button>
        </form>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center" }}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索病例编号 / 别名 / 诊断"
          style={{ ...inputStyle, width: 240 }}
        />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as CaseStatus | "")} style={inputStyle}>
          {STATUS_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {cases && <span style={{ fontSize: 11.5, color: "var(--muted)" }}>共 {cases.length} 条</span>}
      </div>

      {error && <div style={{ color: "var(--red)", fontSize: 12.5, marginBottom: 14 }}>{error}</div>}

      <div style={{ border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ background: "var(--card)", textAlign: "left" }}>
              {["病例编号 / 别名", "患者", "状态", "当前待办", "单据", "更新时间"].map((h) => (
                <th key={h} style={thStyle}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cases === null && (
              <tr>
                <td colSpan={6} style={{ padding: 20, textAlign: "center", color: "var(--muted)" }}>
                  加载中…
                </td>
              </tr>
            )}
            {cases?.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: 20, textAlign: "center", color: "var(--muted)" }}>
                  {search || statusFilter ? "没有匹配的病例，换个关键词或清空筛选试试" : '还没有病例，点右上角"新建病例"开始'}
                </td>
              </tr>
            )}
            {cases?.map((c) => {
              const s = STATUS_LABEL[c.status] ?? { label: c.status, fg: "var(--sub)", bg: "var(--card)" };
              const name = (c.patient_meta.name as string) || "—";
              const dx = (c.patient_meta.dx as string) || "";
              return (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/workshop/${c.id}`)}
                  style={{ borderTop: "1px solid var(--line-soft, var(--line))", cursor: "pointer" }}
                >
                  <td style={tdStyle}>
                    {c.case_no}
                    {c.alias && <span style={{ color: "var(--muted)" }}> · {c.alias}</span>}
                  </td>
                  <td style={tdStyle}>
                    {name}
                    {dx && <span style={{ color: "var(--muted)" }}> · {dx}</span>}
                  </td>
                  <td style={tdStyle}>
                    <span style={{ padding: "2px 9px", borderRadius: 9, fontSize: 11, fontWeight: 600, color: s.fg, background: s.bg }}>
                      {s.label}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, color: c.last_failed_step ? "var(--red)" : "var(--sub)", fontWeight: c.last_failed_step ? 600 : 400 }}>
                    {c.todo_label}
                  </td>
                  <td style={tdStyle}>{c.document_count}</td>
                  <td style={{ ...tdStyle, color: "var(--muted)" }}>{new Date(c.updated_at).toLocaleString("zh-CN")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const thStyle: CSSProperties = { padding: "9px 14px", fontSize: 11, color: "var(--muted)", fontWeight: 700 };
const tdStyle: CSSProperties = { padding: "10px 14px" };
const inputStyle: CSSProperties = {
  padding: "7px 9px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--surface)",
  fontSize: 12.5,
  fontFamily: "inherit",
};
const primaryBtn: CSSProperties = {
  padding: "7px 14px",
  borderRadius: 7,
  border: "1px solid var(--navy)",
  background: "var(--navy)",
  color: "#fff",
  fontWeight: 600,
  fontSize: 12.5,
  cursor: "pointer",
};
