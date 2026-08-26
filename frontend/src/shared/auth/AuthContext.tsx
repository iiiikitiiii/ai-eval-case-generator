import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getAuthToken, setAuthToken } from "../api/client";

export type Role = "reviewer" | "engineer" | "manager" | "admin";

export interface CurrentUser {
  id: string;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
}

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getAuthToken()) {
      setLoading(false);
      return;
    }
    api
      .get<CurrentUser>("/auth/me")
      .then(setUser)
      .catch(() => setAuthToken(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const { access_token } = await api.post<{ access_token: string }>("/auth/login", { email, password });
    setAuthToken(access_token);
    const me = await api.get<CurrentUser>("/auth/me");
    setUser(me);
  }

  function logout() {
    setAuthToken(null);
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 <AuthProvider> 内使用");
  return ctx;
}

/** 三个页面各自的最小可访问角色，供 AppShell 和路由守卫复用。 */
export const PAGE_ROLES: Record<"workshop" | "prompts" | "board", Role[]> = {
  workshop: ["reviewer", "admin"],
  prompts: ["engineer", "admin"],
  board: ["manager", "reviewer", "engineer", "admin"], // 看板对所有角色只读可见
};
