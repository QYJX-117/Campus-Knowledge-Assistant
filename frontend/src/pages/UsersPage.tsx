import { useCallback, useEffect, useState } from "react";
import {
  App as AntdApp, Avatar, Button, Card, Form, Input, Modal, Popconfirm, Select,
  Space, Table, Tag, Tooltip,
} from "antd";
import {
  EditOutlined, LockOutlined, MailOutlined, PlusOutlined,
  ReloadOutlined, SearchOutlined, SafetyCertificateOutlined,
  StopOutlined, UserOutlined,
} from "@ant-design/icons";
import api from "../services/api";

interface UserRecord {
  id: number;
  name: string;
  email: string;
  role: "ADMIN" | "STUDENT";
  is_active: boolean;
  created_at: string;
}

interface UserPageData {
  records: UserRecord[];
  total: number;
  page: number;
  size: number;
}

export default function UsersPage() {
  const { message } = AntdApp.useApp();
  const [form] = Form.useForm();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [role, setRole] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<UserRecord | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<UserPageData>("/users", {
        params: { page, size: pageSize, keyword: keyword || undefined, role },
      });
      setUsers(data.records);
      setTotal(data.total);
    } catch (error: any) {
      message.error(error.response?.data?.detail || "用户列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword, role]);

  useEffect(() => { load(); }, [load]);

  const search = (value: string) => {
    setKeyword(value.trim());
    setPage(1);
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ role: "STUDENT" });
    setModalOpen(true);
  };

  const openEdit = (user: UserRecord) => {
    setEditing(user);
    form.setFieldsValue({ name: user.name, email: user.email, role: user.role });
    setModalOpen(true);
  };

  const save = async (values: any) => {
    setSaving(true);
    try {
      if (editing) {
        const payload: Record<string, string> = {};
        const nextName = values.name.trim();
        const nextEmail = values.email.trim().toLowerCase();
        if (nextName !== editing.name) payload.name = nextName;
        if (nextEmail !== editing.email.toLowerCase()) payload.email = nextEmail;
        if (values.role !== editing.role) payload.role = values.role;

        if (Object.keys(payload).length === 0) {
          message.info("用户信息没有变化");
          setModalOpen(false);
          return;
        }

        const updated = await api.patch<UserRecord>(`/users/${editing.id}`, payload);
        setUsers((current) => current.map((user) => user.id === updated.id ? updated : user));
        message.success("用户信息已更新");
      } else {
        await api.post("/users", values);
        message.success("用户创建成功");
        if (page === 1) await load();
        else setPage(1);
      }
      setModalOpen(false);
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      const detailText = Array.isArray(detail)
        ? detail.map((item: any) => item?.msg).filter(Boolean).join("；")
        : detail;
      message.error(detailText || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      await save(values);
    } catch (error: any) {
      if (!error?.errorFields) {
        const detail = error?.response?.data?.detail;
        const detailText = Array.isArray(detail)
          ? detail.map((item: any) => item?.msg).filter(Boolean).join("；")
          : detail;
        message.error(detailText || "保存失败，请检查后端服务是否正常");
      }
    }
  };

  const toggleActive = async (user: UserRecord) => {
    try {
      await api.patch(`/users/${user.id}`, { is_active: !user.is_active });
      message.success(user.is_active ? "用户已停用" : "用户已恢复");
      load();
    } catch (error: any) {
      message.error(error.response?.data?.detail || "状态更新失败");
    }
  };

  const columns = [
    {
      title: "用户", dataIndex: "name", minWidth: 250,
      render: (_: string, user: UserRecord) => (
        <div className="user-cell">
          <Avatar className="user-cell-avatar" size={40}
            style={{ background: user.role === "ADMIN" ? "#FFF2D8" : "#E6F4FC", color: user.role === "ADMIN" ? "#A46B00" : "#0876B8" }}>
            {user.name.slice(0, 1).toUpperCase()}
          </Avatar>
          <div>
            <div className="user-cell-name">{user.name}</div>
            <div className="user-cell-email"><MailOutlined /> {user.email}</div>
          </div>
        </div>
      ),
    },
    {
      title: "角色", dataIndex: "role", width: 130,
      render: (value: UserRecord["role"]) => value === "ADMIN"
        ? <span className="role-badge admin"><SafetyCertificateOutlined /> 管理员</span>
        : <span className="role-badge student"><UserOutlined /> 学生</span>,
    },
    {
      title: "账号状态", dataIndex: "is_active", width: 120,
      render: (active: boolean) => (
        <span className={`status-text ${active ? "active" : "inactive"}`}>
          <span className={`status-dot ${active ? "active" : ""}`} />
          {active ? "正常" : "已停用"}
        </span>
      ),
    },
    {
      title: "创建时间", dataIndex: "created_at", width: 180,
      render: (value: string) => <span style={{ color: "#64748B" }}>{new Date(value).toLocaleString("zh-CN", { hour12: false })}</span>,
    },
    {
      title: "操作", width: 160, fixed: "right" as const,
      render: (_: unknown, user: UserRecord) => (
        <div className="user-actions">
          <Tooltip title="编辑用户">
            <Button type="text" icon={<EditOutlined />} onClick={() => openEdit(user)}>编辑</Button>
          </Tooltip>
          <Popconfirm
            title={user.is_active ? "确认停用该用户？" : "确认恢复该用户？"}
            description={user.is_active ? "停用后该账号将无法登录系统。" : "恢复后该账号可重新登录。"}
            okText={user.is_active ? "停用" : "恢复"}
            cancelText="取消"
            okButtonProps={{ danger: user.is_active }}
            onConfirm={() => toggleActive(user)}
          >
            <Button type="text" danger={user.is_active} icon={user.is_active ? <StopOutlined /> : <ReloadOutlined />}>
              {user.is_active ? "停用" : "恢复"}
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div className="users-page fade-up">
      <div className="page-header">
        <div>
          <h2>用户管理</h2>
          <p>维护校园用户账号、角色权限与启用状态</p>
        </div>
        <Button type="primary" size="large" icon={<PlusOutlined />} onClick={openCreate}>新增用户</Button>
      </div>

      <Card className="users-toolbar-card" style={{ marginBottom: 16 }}>
        <div className="users-toolbar">
          <div className="users-toolbar-left">
            <Input.Search
              prefix={<SearchOutlined />}
              placeholder="搜索姓名或邮箱"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              onSearch={search}
              allowClear
              style={{ width: 300 }}
            />
            <Select
              allowClear
              placeholder="全部角色"
              value={role}
              onChange={(value) => { setRole(value); setPage(1); }}
              style={{ width: 140 }}
              options={[{ value: "ADMIN", label: "管理员" }, { value: "STUDENT", label: "学生" }]}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          </div>
          <Tag color="blue" style={{ padding: "5px 12px", margin: 0 }}>共 {total} 个账号</Tag>
        </div>
      </Card>

      <Card className="users-table-card" styles={{ body: { padding: 0 } }}>
        <Table<UserRecord>
          rowKey="id"
          columns={columns}
          dataSource={users}
          loading={loading}
          scroll={{ x: 900 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (value) => `共 ${value} 个用户`,
            onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
          }}
          locale={{ emptyText: keyword || role ? "没有符合条件的用户" : "暂无用户" }}
        />
      </Card>

      <Modal
        title={editing ? "编辑用户" : "新增用户"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleModalOk}
        confirmLoading={saving}
        okText={editing ? "保存修改" : "创建用户"}
        cancelText="取消"
        forceRender
        afterClose={() => { form.resetFields(); setEditing(null); }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 20 }}
          onFinishFailed={() => message.warning("请先完善表单中的必填信息")}>
          <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请输入姓名" }, { min: 2, message: "姓名至少 2 个字符" }]}>
            <Input prefix={<UserOutlined />} placeholder="请输入用户姓名" />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, message: "请输入邮箱" }, { type: "email", message: "邮箱格式不正确" }]}>
            <Input prefix={<MailOutlined />} placeholder="name@example.com" />
          </Form.Item>
          {!editing && (
            <Form.Item name="password" label="初始密码" rules={[{ required: true, message: "请输入初始密码" }, { min: 6, message: "密码至少 6 位" }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" />
            </Form.Item>
          )}
          <Form.Item name="role" label="角色" rules={[{ required: true, message: "请选择角色" }]}>
            <Select options={[{ value: "STUDENT", label: "学生" }, { value: "ADMIN", label: "管理员" }]} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
