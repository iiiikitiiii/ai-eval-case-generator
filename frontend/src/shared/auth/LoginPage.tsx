import { useState, type CSSProperties, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { user, login } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? "/board";
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
      <form
        onSubmit={handleSubmit}
        style={{
          width: 320,
          padding: 28,
          borderRadius: 12,
          border: "1px solid var(--line)",
          background: "var(--surface)",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 700 }}>病例流水线中枢</div>
          <div style={{ fontSize: 12, color: "var(--sub)", marginTop: 2 }}>登录后按角色进入对应页面</div>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12.5, color: "var(--sub)" }}>
          邮箱
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12.5, color: "var(--sub)" }}>
          密码
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
        </label>

        {error && <div style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</div>}

        <button
          type="submit"
          disabled={submitting}
          style={{
            padding: "9px 14px",
            borderRadius: 7,
            border: "1px solid var(--navy)",
            background: "var(--navy)",
            color: "#fff",
            fontWeight: 600,
            fontSize: 13,
            cursor: submitting ? "not-allowed" : "pointer",
            opacity: submitting ? 0.7 : 1,
          }}
        >
          {submitting ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}

const inputStyle: CSSProperties = {
  padding: "8px 10px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--card)",
  color: "var(--ink)",
  fontSize: 13,
  fontFamily: "inherit",
};
