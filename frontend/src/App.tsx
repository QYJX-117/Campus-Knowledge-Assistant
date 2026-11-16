import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import { createElement } from "react";
import { useAuthStore } from "./store/authStore";
import { useThemeStore } from "./store/themeStore";
import "./widget";
import AdminLayout from "./layouts/AdminLayout";
import LoginPage from "./pages/LoginPage";
import ChatPage from "./pages/ChatPage";
import KnowledgePage from "./pages/KnowledgePage";
import UsersPage from "./pages/UsersPage";
import DashboardPage from "./pages/DashboardPage";
import SystemConfigPage from "./pages/SystemConfigPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminGuard() {
  const { token, user } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  if (user?.role !== "ADMIN") return <Navigate to="/chat" replace />;
  return <Outlet />;
}

function RootRedirect() {
  const { token, user } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  if (!user) return <Navigate to="/login" replace />;
  return user.role === "ADMIN"
    ? <Navigate to="/admin/chat" replace />
    : <Navigate to="/chat" replace />;
}

function FloatingAssistant() {
  const { token, user } = useAuthStore();
  const theme = useThemeStore((s) => s.theme);
  const isRegisteredAccount = Boolean(
    token && user && user.id > 0 && ["STUDENT", "ADMIN"].includes(user.role),
  );
  if (!isRegisteredAccount) return null;
  return createElement("hhu-chat-widget", {
    title: "河海智答",
    "access-token": token,
    "show-sources": "false",
    movable: "true",
    theme,
  });
}

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        {/* All authenticated routes share AdminLayout */}
        <Route element={<ProtectedRoute><AdminLayout /></ProtectedRoute>}>
          {/* Student-only chat */}
          <Route path="chat" element={<ChatPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />

          {/* Admin routes — AdminGuard uses Outlet for nested rendering */}
          <Route path="admin" element={<AdminGuard />}>
            <Route index element={<DashboardPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="settings" element={<SystemConfigPage />} />
          </Route>
        </Route>

        <Route path="/" element={<ProtectedRoute><RootRedirect /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
      <FloatingAssistant />
    </>
  );
}
