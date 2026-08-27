import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { AuditLogOut, getAuditLog } from "../api/audit";
import { getLlmProvider, setLlmProvider } from "../api/settings";
import { PAGE_ROLES, useAuth } from "../auth/AuthContext";

const NAV = [
  { to: "/workshop", label: "病例工坊", page: "workshop" as const },
  { to: "/prompts", label: "Prompt 维护后台", page: "prompts" as const },
  { to: "/board", label: "用例看板", page: "board" as const },
  // Stage 2-1 only exposes the dedicated module entry; workflow controls are
  // added inside this route in later stages without changing the global nav.
  { to: "/dynamic", label: "动态生成", page: "dynamic" as const },
];

const ROLE_LABEL: Record<string, string> = {
  reviewer: "审核员",
  engineer: "工程师",
  manager: "测试经理",
  admin: "管理员",
};

const PROVIDER_LABEL: Record<string, string> = { minimax: "MiniMax", kimi: "Kimi" };

/** 全局单选，不是每页各配一个——所有 Agent 运行（病例工坊触发的、Prompt
 * 后台沙盒试跑的）都读同一个数据库设置，所以入口也放在所有页面共享的顶栏，
 * 不是塞进某一个页面里。审核员/测试经理能看到当前用的是哪个模型，但只有
 * 工程师/管理员能切换——跟后端 PUT /settings/llm-provider 的权限一致。
 *
 * P2-2《交互体验优化需求》：切换前二次确认 + 切换后提示 + 可查历史。一次
 * 点击会影响之后所有病例流水线和沙盒试跑用哪个模型，不该是无感的单击切换。 */
function ModelSwitch({ canEdit }: { canEdit: boolean }) {
  const [provider, setProvider] = useState<string | null>(null);
  const [options, setOptions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<string | null>(null); // 待确认切换到的目标
  const [toast, setToast] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    getLlmProvider()
      .then((r) => {
        setProvider(r.provider);
        setOptions(r.options);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  async function confirmSwitch() {
    if (!pending || busy) return;
    const target = pending;
    const prevLabel = PROVIDER_LABEL[provider ?? ""] ?? provider;
    setBusy(true);
    try {
      await setLlmProvider(target);
      setProvider(target);
      setToast(`已切换为 ${PROVIDER_LABEL[target] ?? target}（原：${prevLabel}）`);
    } catch {
      setToast("切换失败，请重试");
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  if (!provider) return null;

  if (!canEdit) {
    return (
      <span style={{ fontSize: 11, color: "var(--muted)", padding: "3px 9px", border: "1px solid var(--line)", borderRadius: 6 }}>
        模型：{PROVIDER_LABEL[provider] ?? provider}
      </span>
    );
  }

  return (
    <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ display: "flex", border: "1px solid var(--line)", borderRadius: 6, overflow: "hidden" }}>
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => opt !== provider && !busy && setPending(opt)}
            disabled={busy}
            title="切换会影响下一次病例流水线运行和 Prompt 沙盒试跑使用的模型"
            style={{
              padding: "3px 10px",
              fontSize: 11,
              fontWeight: opt === provider ? 700 : 500,
              border: "none",
              background: opt === provider ? "var(--navy)" : "var(--surface)",
              color: opt === provider ? "#fff" : "var(--sub)",
              cursor: busy ? "default" : "pointer",
            }}
          >
            {PROVIDER_LABEL[opt] ?? opt}
          </button>
        ))}
      </div>
      <button
        onClick={() => setHistoryOpen((v) => !v)}
        title="查看模型切换记录"
        style={{
          border: "none", background: "transparent", color: "var(--muted)",
          fontSize: 11, cursor: "pointer", padding: "2px 4px", textDecoration: "underline",
        }}
      >
        切换记录
      </button>

      {pending && (
        <ConfirmSwitchDialog
          from={PROVIDER_LABEL[provider] ?? provider}
          to={PROVIDER_LABEL[pending] ?? pending}
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={confirmSwitch}
        />
      )}
      {historyOpen && <SwitchHistoryPopover onClose={() => setHistoryOpen(false)} />}
      {toast && (
        <div
          style={{
            position: "fixed", top: 58, right: 20, zIndex: 1000,
            background: "var(--navy)", color: "#fff", fontSize: 12,
            padding: "8px 14px", borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function ConfirmSwitchDialog({
  from, to, busy, onCancel, onConfirm,
}: { from: string; to: string; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(10, 12, 16, 0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--card)", borderRadius: 10, padding: "20px 22px", width: 360, boxShadow: "0 12px 40px rgba(0,0,0,0.25)" }}
      >
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--navy)", marginBottom: 8 }}>切换全局模型？</div>
        <div style={{ fontSize: 12.5, color: "var(--sub)", lineHeight: 1.6, marginBottom: 16 }}>
          将从 <b>{from}</b> 切换为 <b>{to}</b>。此设置全局生效——切换后，下一次病例流水线运行和 Prompt 沙盒试跑都会使用新模型，不影响正在进行中的运行。
        </div>
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
            style={{ border: "none", background: "var(--navy)", borderRadius: 6, padding: "6px 14px", fontSize: 12, color: "#fff", cursor: busy ? "default" : "pointer" }}
          >
            {busy ? "切换中…" : "确认切换"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SwitchHistoryPopover({ onClose }: { onClose: () => void }) {
  const [rows, setRows] = useState<AuditLogOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAuditLog({ action_prefix: "setting.llm_provider", limit: 20 })
      .then(setRows)
      .catch(() => setError("加载失败"));
  }, []);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 999 }} onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "absolute", top: 52, right: 20, width: 340, maxHeight: 360, overflow: "auto",
          background: "var(--card)", border: "1px solid var(--line)", borderRadius: 8,
          boxShadow: "0 12px 40px rgba(0,0,0,0.2)", padding: 12,
        }}
      >
        <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--navy)", marginBottom: 8 }}>模型切换记录</div>
        {error && <div style={{ fontSize: 12, color: "var(--danger, #c0392b)" }}>{error}</div>}
        {!error && rows === null && <div style={{ fontSize: 12, color: "var(--muted)" }}>加载中…</div>}
        {rows && rows.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>还没有切换记录</div>}
        {rows && rows.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {rows.map((r) => {
              const before = r.before?.provider as string | undefined;
              const after = r.after?.provider as string | undefined;
              return (
                <div key={r.id} style={{ fontSize: 11.5, color: "var(--sub)", borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
                  <div>
                    {before ? `${PROVIDER_LABEL[before] ?? before} → ` : ""}
                    <b>{PROVIDER_LABEL[after ?? ""] ?? after ?? "—"}</b>
                  </div>
                  <div style={{ color: "var(--muted)" }}>
                    {r.actor_name ?? "系统"} · {new Date(r.at).toLocaleString("zh-CN")}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  if (!user) return null;

  const visibleNav = NAV.filter((item) => PAGE_ROLES[item.page].includes(user.role));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 24,
          padding: "0 20px",
          height: 52,
          borderBottom: "1px solid var(--line)",
          background: "var(--surface)",
          flexShrink: 0,
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--navy)" }}>病例流水线中枢</div>

        <nav style={{ display: "flex", gap: 4, flex: 1 }}>
          {visibleNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) => ({
                padding: "6px 12px",
                borderRadius: 6,
                fontSize: 12.5,
                fontWeight: isActive ? 700 : 500,
                color: isActive ? "var(--navy)" : "var(--sub)",
                background: isActive ? "var(--navy-l)" : "transparent",
                textDecoration: "none",
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div style={{ fontSize: 12, color: "var(--sub)", display: "flex", alignItems: "center", gap: 10 }}>
          <ModelSwitch canEdit={user.role === "engineer" || user.role === "admin"} />
          <span>
            {user.name} · {ROLE_LABEL[user.role] ?? user.role}
          </span>
          <button
            onClick={logout}
            style={{
              border: "1px solid var(--line)",
              background: "var(--card)",
              borderRadius: 6,
              padding: "4px 10px",
              fontSize: 11.5,
              color: "var(--sub)",
              cursor: "pointer",
            }}
          >
            退出
          </button>
        </div>
      </header>

      <main style={{ flex: 1, overflow: "auto" }}>
        <Outlet />
      </main>
    </div>
  );
}
