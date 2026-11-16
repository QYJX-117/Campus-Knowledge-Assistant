import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { App as AntdApp, Layout, Menu, Button, Dropdown, Form, Input, Modal, Tooltip } from "antd";
import {
  DashboardOutlined, MessageOutlined, FileTextOutlined,
  UserOutlined, SettingOutlined, LogoutOutlined, EditOutlined, MoreOutlined, BulbOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined,
} from "@ant-design/icons";
import { useState } from "react";
import { useAuthStore } from "../store/authStore";
import { useThemeStore } from "../store/themeStore";
import api from "../services/api";

const { Sider, Content } = Layout;

/* ── HHU Logo SVG ────────────────────────────────────────────── */
function HHULogo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* outer ring */}
      <circle cx="50" cy="50" r="48" stroke="rgba(255,255,255,0.55)" strokeWidth="2.5" fill="none" />
      {/* wave motif */}
      <path d="M18 58 Q34 38 50 58 Q66 78 82 58" stroke="rgba(255,255,255,0.9)" strokeWidth="2.8" fill="none" strokeLinecap="round" />
      <path d="M14 68 Q30 48 46 68 Q62 88 78 68 Q86 58 86 58" stroke="rgba(255,255,255,0.55)" strokeWidth="2" fill="none" strokeLinecap="round" />
      {/* 河 (simplified) */}
      <text x="50" y="36" textAnchor="middle" fill="white" fontSize="26" fontWeight="800" fontFamily="serif">河</text>
      {/* 海 */}
      <text x="50" y="84" textAnchor="middle" fill="white" fontSize="11" fontWeight="600" letterSpacing="3" fontFamily="sans-serif">HHU</text>
    </svg>
  );
}

export default function AdminLayout() {
  const { message } = AntdApp.useApp();
  const nav = useNavigate();
  const loc = useLocation();
  const { user, logout, updateUser } = useAuthStore();
  const { theme, toggle } = useThemeStore();
  const isDark = theme === "dark";
  const isAdmin = user?.role === "ADMIN";
  const isGuest = user?.id === 0;
  const [collapsed, setCollapsed] = useState(!isAdmin);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileForm] = Form.useForm();

  const menuItems = [
    { key: "/admin",          icon: <DashboardOutlined />,  label: "仪表盘",      adminOnly: true },
    { key: "/admin/chat",     icon: <MessageOutlined />,     label: "问答工作台",   adminOnly: true },
    { key: "/chat",           icon: <MessageOutlined />,     label: "问答工作台",   adminOnly: false },
    { key: "/admin/knowledge",icon: <FileTextOutlined />,    label: "知识库管理",   adminOnly: true },
    { key: "/knowledge",      icon: <FileTextOutlined />,    label: "知识库管理",   adminOnly: false },
    { key: "/admin/users",    icon: <UserOutlined />,        label: "用户管理",     adminOnly: true },
    { key: "/admin/settings", icon: <SettingOutlined />,     label: "系统配置",     adminOnly: true },
  ];

  // Filter based on role: students see chat + knowledge, admins see all
  const visibleMenus = menuItems
    .filter(m => isAdmin || !m.adminOnly)
    // Deduplicate: if admin, prefer /admin/* over /*
    .filter((m, _, arr) => {
      if (m.key === "/chat" && isAdmin) return false;
      if (m.key === "/knowledge" && isAdmin) return false;
      return true;
    })
    .map((item) => ({ key: item.key, icon: item.icon, label: item.label }));

  const selectedKey = loc.pathname === "/admin" ? "/admin" : loc.pathname;

  // Also add /chat path handling for students
  const effectiveKey = (() => {
    if (selectedKey === "/admin" || selectedKey.startsWith("/admin/")) return selectedKey;
    if (selectedKey === "/chat" && !isAdmin) return "/chat";
    return selectedKey;
  })();
  const isChatRoute = loc.pathname === "/admin/chat" || loc.pathname === "/chat";
  const paddedRoute = (loc.pathname.startsWith("/admin") && !isChatRoute) || loc.pathname === "/knowledge";
  const shellBackground = isDark ? "#081018" : "#F8FAFC";
  const contentBackground = isChatRoute
    ? "transparent"
    : isDark
      ? "linear-gradient(180deg, rgba(8,16,24,0.97), rgba(10,18,26,0.99))"
      : paddedRoute
        ? "#F8FAFC"
        : "#FFFFFF";

  const handleMenuClick = ({ key }: { key: string }) => {
    nav(key);
  };

  const handleLogout = () => {
    logout();
    nav("/login");
  };

  const openProfile = () => {
    profileForm.setFieldsValue({ name: user?.name, email: user?.email });
    setProfileOpen(true);
  };

  const saveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      setProfileSaving(true);
      const updated: any = await api.patch("/users/me", {
        name: values.name,
        email: values.email,
        current_password: values.current_password,
        new_password: values.new_password || null,
      });
      updateUser(updated);
      message.success("个人信息已更新");
      setProfileOpen(false);
      profileForm.resetFields();
    } catch (error: any) {
      if (error?.errorFields) return;
      message.error(error?.response?.data?.detail || "个人信息更新失败");
    } finally {
      setProfileSaving(false);
    }
  };

  const accountPanel = (
    <div
      className="sidebar-user"
      onClick={isGuest ? handleLogout : undefined}
    >
      <div className="sidebar-user-avatar">
        <span>{(user?.name || "管").slice(0, 1)}</span>
        <i />
      </div>
      {!collapsed && (
        <div className="sidebar-user-meta">
          <strong>{user?.name || "管理员"}</strong>
          <span>{isAdmin ? "系统管理员" : isGuest ? "访客用户" : "学生用户"}</span>
        </div>
      )}
      {!collapsed && (
        <div className="sidebar-user-actions">
          <Tooltip title={theme === "dark" ? "切换浅色" : "切换深色"}>
            <Button
              type="text"
              icon={<BulbOutlined />}
              onClick={(e) => { e.stopPropagation(); toggle(); }}
              className="sidebar-theme-btn"
              aria-label={theme === "dark" ? "切换浅色" : "切换深色"}
            />
          </Tooltip>
          <Tooltip title={isGuest ? "退出登录" : "账号操作"}>
            {isGuest
              ? <LogoutOutlined className="sidebar-user-action" />
              : <MoreOutlined className="sidebar-user-action" />}
          </Tooltip>
        </div>
      )}
    </div>
  );

  return <>
    <Layout className="app-layout" style={{ minHeight: "100vh" }}>
      {/* ── Left Sidebar ── */}
      <Sider
        className="modern-sidebar"
        trigger={null}
        collapsible
        collapsed={collapsed}
        width={280}
        collapsedWidth={88}
      >
        <div className="modern-sidebar-shell">
          {/* Brand area */}
          <div className="sidebar-brand">
            <div className="sidebar-brand-main">
              <div className="sidebar-logo-shell">
                <HHULogo size={collapsed ? 34 : 40} />
              </div>
              {!collapsed && (
                <div className="sidebar-brand-text">
                  <strong>河海智答</strong>
                  <span>校园知识问答助手</span>
                </div>
              )}
            </div>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
              className="sidebar-collapse-btn"
              aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
            />
          </div>

          {/* Navigation menu */}
          <div className="sidebar-nav">
            <Menu
              className="modern-sidebar-menu"
              theme="light"
              mode="inline"
              selectedKeys={[effectiveKey]}
              items={visibleMenus}
              onClick={handleMenuClick}
            />
          </div>

          {/* Bottom: user info + logout */}
          {isGuest ? accountPanel : (
            <Dropdown
              trigger={["click"]}
              placement="topLeft"
              menu={{
                items: [
                  { key: "profile", icon: <EditOutlined />, label: "编辑个人信息" },
                  { type: "divider" },
                  { key: "logout", icon: <LogoutOutlined />, label: "退出登录", danger: true },
                ],
                onClick: ({ key }) => key === "profile" ? openProfile() : handleLogout(),
              }}
            >
              {accountPanel}
            </Dropdown>
          )}
        </div>
      </Sider>

      {/* ── Right Content (full height, no header) ── */}
      <Layout style={{ background: shellBackground }}>
        <Content
          style={{
            margin: 0,
            padding: paddedRoute ? "24px" : 0,
            height: "100vh",
            minHeight: 0,
            overflow: "auto",
            background: contentBackground,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
    <Modal
      title="编辑个人信息"
      open={profileOpen}
      onCancel={() => { setProfileOpen(false); profileForm.resetFields(); }}
      onOk={saveProfile}
      confirmLoading={profileSaving}
      okText="保存修改"
      cancelText="取消"
      forceRender
    >
      <Form form={profileForm} layout="vertical" style={{ marginTop: 20 }}>
        <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请输入姓名" }, { min: 2, message: "姓名至少 2 个字符" }]}>
          <Input prefix={<UserOutlined />} maxLength={50} />
        </Form.Item>
        <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}>
          <Input />
        </Form.Item>
        <Form.Item name="current_password" label="当前密码" rules={[{ required: true, min: 6, message: "请输入当前密码" }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item name="new_password" label="新密码" extra="不修改密码时留空" rules={[{ min: 6, message: "新密码至少 6 位" }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item name="confirm_password" label="确认新密码" dependencies={["new_password"]} rules={[({ getFieldValue }) => ({
          validator(_, value) {
            const password = getFieldValue("new_password");
            if (!password && !value) return Promise.resolve();
            return value === password ? Promise.resolve() : Promise.reject(new Error("两次输入的新密码不一致"));
          },
        })]}>
          <Input.Password />
        </Form.Item>
      </Form>
    </Modal>
  </>;
}
