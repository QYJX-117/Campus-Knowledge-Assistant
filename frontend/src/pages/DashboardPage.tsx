import { useCallback, useEffect, useState } from "react";
import { Row, Col, Card, Statistic, Spin, Table, Tag, Button, Tooltip as AntTooltip } from "antd";
import { FileTextOutlined, MessageOutlined, UserOutlined, DatabaseOutlined, ReloadOutlined } from "@ant-design/icons";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import api from "../services/api";

const cards = [
  { key: "ready_documents", title: "已入库文档", icon: <FileTextOutlined />, suffix: "篇", cls: "blue", bg: "#E8F4FC", color: "#0B6FCC" },
  { key: "today_questions", title: "今日问答", icon: <MessageOutlined />, suffix: "次", cls: "green", bg: "#ECFDF5", color: "#10B981" },
  { key: "active_users", title: "活跃用户", icon: <UserOutlined />, suffix: "人", cls: "amber", bg: "#FFFBEB", color: "#F59E0B" },
  { key: "total_chunks", title: "向量块数", icon: <DatabaseOutlined />, suffix: "块", cls: "cyan", bg: "#E9F9FB", color: "#0891B2" },
];

const operationName = (method: string, endpoint: string) => {
  if (endpoint.includes("/chat/stream")) return "智能问答";
  if (endpoint.includes("/auth/login")) return "账号登录";
  if (endpoint.includes("/auth/guest")) return "访客登录";
  if (endpoint.includes("/documents") || endpoint.includes("/doc/")) return method === "GET" ? "查看知识文档" : "维护知识文档";
  if (endpoint.includes("/users")) return method === "GET" ? "查看用户" : "维护用户";
  if (endpoint.includes("/system/config")) return method === "GET" ? "查看系统配置" : "修改系统配置";
  if (endpoint.includes("/stats")) return "查看统计数据";
  if (endpoint.includes("/system/logs")) return "查看系统日志";
  return `${method} 请求`;
};

export default function DashboardPage() {
  const [stats, setStats] = useState<any>({});
  const [trends, setTrends] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [logPage, setLogPage] = useState(1);
  const [logPageSize, setLogPageSize] = useState(10);
  const [logTotal, setLogTotal] = useState(0);
  const [logLoading, setLogLoading] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadLogs = useCallback(async (page = 1, size = 10) => {
    setLogLoading(true);
    try {
      const data: any = await api.get("/system/logs", { params: { page, size } });
      setLogs(data.records);
      setLogTotal(data.total);
      setLogPage(data.page);
      setLogPageSize(data.size);
    } finally {
      setLogLoading(false);
    }
  }, []);

  useEffect(() => {
    Promise.all([
      api.get("/stats/dashboard").then(setStats).catch(() => {}),
      api.get("/stats/trends", { params: { days: 7 } }).then(setTrends).catch(() => {}),
      loadLogs(1, 10).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [loadLogs]);

  if (loading) return <Spin size="large" style={{ display: "block", textAlign: "center", padding: 100 }} />;

  return (
    <div className="fade-up">
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>系统仪表盘</h2>
      <p style={{ color: "#94A3B8", marginBottom: 28, fontSize: 14 }}>校园问答助手运行数据概览</p>
      <Row gutter={[20, 20]} align="stretch">
        {cards.map((c) => (
          <Col xs={24} sm={12} lg={6} key={c.key}>
            <Card className={`stat-card ${c.cls}`} style={{ borderLeft: `3px solid ${c.color}`, height: "100%" }}>
              <Statistic title={c.title} value={stats[c.key] ?? 0} suffix={c.suffix}
                prefix={<span style={{ color: c.color, background: c.bg, padding: "6px 10px", borderRadius: 10, marginRight: 12, fontSize: 18 }}>{c.icon}</span>} />
              {c.key === "ready_documents" && (
                <div style={{ marginTop: 10, color: "#64748B", fontSize: 12 }}>
                  全部记录 {stats.total_documents ?? 0} · 待审核 {stats.pending_documents ?? 0} · 处理中 {stats.processing_documents ?? 0} · 异常 {stats.error_documents ?? 0}
                </div>
              )}
            </Card>
          </Col>
        ))}
      </Row>
      <Card title={<span style={{ fontWeight: 600 }}>近 7 天问答趋势</span>} style={{ marginTop: 24, borderRadius: 16 }} styles={{ body: { padding: "24px 8px 8px" } }}>
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={trends}>
            <defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0B6FCC" stopOpacity={0.25} /><stop offset="100%" stopColor="#0B6FCC" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
            <XAxis dataKey="date" tick={{ fontSize: 12, fill: "#94A3B8" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 12, fill: "#94A3B8" }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={{ borderRadius: 12, border: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }} />
            <Area type="monotone" dataKey="questions" stroke="#0B6FCC" strokeWidth={2.5} fill="url(#grad)" name="问答数" />
          </AreaChart>
        </ResponsiveContainer>
      </Card>
      <Card
        title={<span style={{ fontWeight: 600 }}>系统日志</span>}
        extra={<AntTooltip title="刷新日志"><Button type="text" icon={<ReloadOutlined />} onClick={() => loadLogs(logPage, logPageSize)} /></AntTooltip>}
        style={{ marginTop: 24, borderRadius: 8 }}
        styles={{ body: { padding: 0 } }}
      >
        <Table
          rowKey="id"
          dataSource={logs}
          loading={logLoading}
          pagination={{
            current: logPage,
            pageSize: logPageSize,
            total: logTotal,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (total) => `共 ${total} 条日志`,
            onChange: (page, size) => loadLogs(page, size),
          }}
          size="middle"
          scroll={{ x: 760 }}
          columns={[
            { title: "时间", dataIndex: "created_at", width: 190, render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }) },
            { title: "操作人", dataIndex: "actor", width: 140 },
            { title: "操作", key: "operation", width: 150, render: (_: unknown, record: any) => operationName(record.method, record.endpoint) },
            { title: "请求", dataIndex: "endpoint", ellipsis: true },
            { title: "方法", dataIndex: "method", width: 90, render: (value: string) => <Tag color={value === "GET" ? "blue" : value === "DELETE" ? "red" : "green"}>{value}</Tag> },
            { title: "状态", dataIndex: "status_code", width: 90, render: (value: number) => <Tag color={value < 400 ? "success" : value < 500 ? "warning" : "error"}>{value}</Tag> },
            { title: "耗时", dataIndex: "duration_ms", width: 100, render: (value: number) => `${value ?? 0} ms` },
          ]}
          locale={{ emptyText: "暂无系统日志" }}
        />
      </Card>
    </div>
  );
}
