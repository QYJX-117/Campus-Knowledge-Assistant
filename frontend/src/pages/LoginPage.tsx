import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { App as AntdApp, Form, Input, Button, Checkbox, Tabs, Tooltip } from "antd";
import { CheckCircleFilled, LockOutlined, MailOutlined, ReloadOutlined, SafetyCertificateOutlined, UserOutlined } from "@ant-design/icons";
import { ArrowRight, BookOpenCheck, Building2, GraduationCap, ShieldCheck, Sparkles, X } from "lucide-react";
import { useAuthStore } from "../store/authStore";
import api from "../services/api";

function readableError(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item && typeof item === "object" && "msg" in item ? String(item.msg) : "")
      .filter(Boolean);
    if (messages.length) return messages.join("；");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

export default function LoginPage() {
  const { message } = AntdApp.useApp();
  const [loading, setLoading] = useState(false);
  const [guestLoading, setGuestLoading] = useState(false);
  const [captcha, setCaptcha] = useState({ captcha_token: "", question: "正在加载..." });
  const [authOpen, setAuthOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("login");
  const nav = useNavigate();
  const login = useAuthStore((s) => s.login);

  const openAuth = (tabKey = "login") => {
    setActiveTab(tabKey);
    setAuthOpen(true);
  };

  const refreshCaptcha = useCallback(async () => {
    try {
      setCaptcha(await api.get("/auth/captcha"));
    } catch {
      setCaptcha({ captcha_token: "", question: "加载失败" });
    }
  }, []);

  useEffect(() => { refreshCaptcha(); }, [refreshCaptcha]);

  const handle = async (isLogin: boolean, values: any) => {
    setLoading(true);
    try {
      const payload = { name: values.name, email: values.email, password: values.password };
      const res: any = isLogin
        ? await api.post("/auth/login", {
            email: values.email,
            password: values.password,
            captcha_token: captcha.captcha_token,
            captcha_answer: values.captcha,
          })
        : await api.post("/auth/register", payload);
      login(res.token, res.user);
      message.success(isLogin ? "登录成功" : "注册成功");
      nav(res.user.role === "ADMIN" ? "/admin" : "/chat");
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      if (isLogin && e.response?.status === 401) {
        message.error("账号或密码错误");
      } else {
        message.error(readableError(detail, e.request ? "无法连接后端服务，请确认 8000 端口已启动" : "登录失败，请检查账号和密码"));
      }
      if (isLogin) refreshCaptcha();
    }
    finally { setLoading(false); }
  };

  const handleGuestLogin = async () => {
    setGuestLoading(true);
    try {
      const res: any = await api.post("/auth/guest");
      login(res.token, res.user);
      message.success("已以访客身份进入");
      nav("/chat");
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      message.error(readableError(detail, "访客功能暂不可用，请稍后再试"));
    } finally {
      setGuestLoading(false);
    }
  };

  const tab = (isLogin: boolean) => (
    <Form onFinish={(v) => handle(isLogin, v)} size="large" layout="vertical" requiredMark={false} className="auth-form">
      {!isLogin && <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请输入姓名" }, { min: 2, message: "姓名至少 2 个字符" }]}><Input prefix={<UserOutlined />} placeholder="请输入姓名" /></Form.Item>}
      <Form.Item name="email" label="邮箱" rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}><Input prefix={<MailOutlined />} placeholder="name@example.com" /></Form.Item>
      <Form.Item name="password" label="密码" rules={[{ required: true, min: 6, message: "密码至少 6 位" }]}><Input.Password prefix={<LockOutlined />} placeholder="请输入密码" /></Form.Item>
      {isLogin && (
        <Form.Item name="captcha" label="安全验证" rules={[{ required: true, message: "请输入验证码" }]}>
          <Input
            prefix={<SafetyCertificateOutlined />}
            placeholder="请输入计算结果"
            suffix={<span className="captcha-challenge"><strong>{captcha.question}</strong><Tooltip title="换一题"><Button type="text" size="small" icon={<ReloadOutlined />} onClick={refreshCaptcha} /></Tooltip></span>}
          />
        </Form.Item>
      )}
      {!isLogin && <Form.Item name="confirmPassword" label="确认密码" dependencies={["password"]} rules={[{ required: true, message: "请再次输入密码" }, ({ getFieldValue }) => ({ validator(_, value) { return !value || getFieldValue("password") === value ? Promise.resolve() : Promise.reject(new Error("两次输入的密码不一致")); } })]}><Input.Password prefix={<SafetyCertificateOutlined />} placeholder="请再次输入密码" /></Form.Item>}
      {isLogin && <div className="login-form-options"><Form.Item name="remember" valuePropName="checked" noStyle><Checkbox>保持登录状态</Checkbox></Form.Item><span>安全登录 · JWT 鉴权</span></div>}
      <Button type="primary" htmlType="submit" block loading={loading} className="login-submit">{isLogin ? "登录系统" : "创建账号"}</Button>
      {isLogin && <div className="demo-account"><CheckCircleFilled /><div><strong>课程演示账号</strong><span>admin@campus.example · admin123</span></div></div>}
    </Form>
  );

  return (
    <div className="login-page">
      <div className="login-glow login-glow-a" />
      <div className="login-glow login-glow-b" />

      <main className="login-hero" id="home">
        <section className="login-hero-copy">
          <button className="login-brandline" type="button" onClick={() => openAuth("login")} aria-label="打开登录面板">
            <div className="login-brand-mark" aria-hidden="true">
              <span className="login-brand-mark-top" />
              <span className="login-brand-mark-letter">河</span>
            </div>
            <div className="login-brandword">
              <p>Campus Knowledge Assistant</p>
              <h1>河海智答</h1>
            </div>
          </button>

          <p className="login-hero-subtitle">
            面向河海大学师生的智能知识问答平台，汇聚制度、办事流程与常见问题，让检索更快、回答更准、体验更顺手。
          </p>

          <div className="login-hero-actions">
            <button className="login-primary-cta" type="button" onClick={() => openAuth("login")}>
              Get Started Now
              <span><ArrowRight size={19} strokeWidth={2.3} /></span>
            </button>
            <button className="login-secondary-cta" type="button" onClick={handleGuestLogin} disabled={guestLoading}>
              {guestLoading ? "进入中..." : "访客体验"}
            </button>
          </div>
        </section>

        <section className="login-hero-visual" aria-hidden="true">
          <div className="login-orb-stage">
            <video
              className="login-glassy-orb"
              autoPlay
              loop
              muted
              playsInline
              src="https://future.co/images/homepage/glassy-orb/orb-purple.webm"
            />
            <div className="login-orb-fallback" />
          </div>
        </section>

        <section className="login-feature-grid" id="features" aria-label="平台能力">
          <div className="feature"><BookOpenCheck size={18} /><span><strong>可信回答</strong><small>答案标注来源，便于核验</small></span></div>
          <div className="feature"><Sparkles size={18} /><span><strong>快速检索</strong><small>向量与关键词协同检索</small></span></div>
          <div className="feature"><ShieldCheck size={18} /><span><strong>权限隔离</strong><small>学生和管理员分级使用</small></span></div>
          <div className="feature"><Building2 size={18} /><span><strong>校园服务</strong><small>制度流程与办事指南汇总</small></span></div>
          <div className="feature"><GraduationCap size={18} /><span><strong>后台管理</strong><small>知识问答、文档审核统一维护</small></span></div>
        </section>
      </main>

      {authOpen && (
        <div className="auth-panel-backdrop" role="dialog" aria-modal="true" aria-labelledby="auth-panel-title">
          <button className="auth-panel-scrim" type="button" onClick={() => setAuthOpen(false)} aria-label="关闭登录面板" />
          <div className="auth-panel-shell">
            <button className="auth-panel-close" type="button" onClick={() => setAuthOpen(false)} aria-label="关闭登录面板">
              <X size={18} />
            </button>
            <div className="login-form">
              <div className="login-form-head">
                <span>HHU AI</span>
                <h2 id="auth-panel-title">欢迎使用河海智答</h2>
                <div className="sub">登录账号，开始校园知识探索</div>
              </div>
              <Tabs
                activeKey={activeTab}
                onChange={setActiveTab}
                className="login-tabs"
                size="large"
                items={[
                  { key: "login", label: "账号登录", children: tab(true) },
                  { key: "register", label: "新用户注册", children: tab(false) },
                ]}
              />
              <div className="guest-login-section">
                <div className="guest-divider"><span>或</span></div>
                <Button type="default" block size="large" loading={guestLoading} onClick={handleGuestLogin} className="guest-login-btn">访客登录</Button>
                <p className="guest-hint">无需注册，快速体验平台功能</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
