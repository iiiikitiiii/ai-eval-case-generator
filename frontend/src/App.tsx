import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, PAGE_ROLES, useAuth } from "./shared/auth/AuthContext";
import { LoginPage } from "./shared/auth/LoginPage";
import { AppShell } from "./shared/layout/AppShell";
import { WorkshopPage } from "./routes/workshop/WorkshopPage";
import { PromptsPage } from "./routes/prompts/PromptsPage";
import { BoardPage } from "./routes/board/BoardPage";
import { DynamicGenerationPage } from "./routes/dynamic/DynamicGenerationPage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return null; // avoid a login flash while /auth/me resolves
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <>{children}</>;
}

function RequireRole({ page, children }: { page: keyof typeof PAGE_ROLES; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return null;
  if (!PAGE_ROLES[page].includes(user.role)) {
    return (
      <div style={{ padding: 40, fontSize: 13, color: "var(--sub)" }}>
        你的角色（{user.role}）没有访问这个页面的权限。
      </div>
    );
  }
  return <>{children}</>;
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="/board" replace />} />
            <Route
              path="/workshop/*"
              element={
                <RequireRole page="workshop">
                  <WorkshopPage />
                </RequireRole>
              }
            />
            <Route
              path="/prompts/*"
              element={
                <RequireRole page="prompts">
                  <PromptsPage />
                </RequireRole>
              }
            />
            <Route
              path="/board/*"
              element={
                <RequireRole page="board">
                  <BoardPage />
                </RequireRole>
              }
            />
            <Route
              path="/dynamic/*"
              element={
                <RequireRole page="dynamic">
                  <DynamicGenerationPage />
                </RequireRole>
              }
            />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
