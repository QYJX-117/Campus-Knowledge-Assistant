import { useEffect, useState } from "react";
import { App as AntdApp, Card, Form, Input, InputNumber, Select, Button, Spin, Divider, Alert } from "antd";
import { SaveOutlined, ReloadOutlined } from "@ant-design/icons";
import api from "../services/api";

const CONFIG_KEYS = [
  { key: "system_prompt", label: "系统 Prompt", type: "textarea",
    desc: "定义 AI 助手的角色和回答风格，{context} 替换为检索结果，{question} 替换为用户问题",
    default: "你是校园问答助手，只依据参考资料回答。" },
  { key: "temperature", label: "LLM 温度", type: "number",
    desc: "控制回答创造性：0=确定性，1=创造性。问答建议 0.0-0.3",
    default: 0.1 },
  { key: "max_tokens", label: "最大 Token 数", type: "number",
    desc: "单次回答最大长度，建议 512-2048",
    default: 1024 },
  { key: "top_k", label: "检索 TopK", type: "number",
    desc: "每次检索返回的最相关文档块数量，建议 3-10",
    default: 5 },
  { key: "chunk_size", label: "文档切分大小", type: "number",
    desc: "每块最大字符数。修改后需重建知识库索引",
    default: 500 },
  { key: "rate_limit", label: "API 限流 (次/分钟)", type: "number",
    desc: "每分钟最大请求数，0 表示不限流",
    default: 100 },
];

export default function SystemConfigPage() {
  const { message } = AntdApp.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [kbVersions, setKbVersions] = useState<any[]>([]);

  const load = async () => {
    setLoading(true);
    try {
      const configs: any[] = await api.get("/system/config");
      const values: Record<string, any> = {};
      configs.forEach((c: any) => { values[c.key] = c.value; });
      CONFIG_KEYS.forEach((k) => { if (values[k.key] === undefined) values[k.key] = k.default; });
      form.setFieldsValue(values);
    } catch { message.error("加载配置失败"); }
    try { setKbVersions(await api.get("/kb/versions")); } catch {}
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const values = form.getFieldsValue();
      for (const [key, value] of Object.entries(values)) {
        await api.put("/system/config", { key, value });
      }
      message.success("配置已保存");
    } catch { message.error("保存失败"); }
    setSaving(false);
  };

  const rebuildKB = async () => {
    try {
      message.loading({ content: "正在重建知识库索引...", key: "rebuild", duration: 0 });
      await api.post("/kb/rebuild");
      message.success({ content: "知识库重建完成", key: "rebuild" });
      load();
    } catch { message.error({ content: "重建失败", key: "rebuild" }); }
  };

  return (
    <div>
      <div className="page-header"><h2>系统配置</h2><p>调整 Prompt 模板、LLM 参数和检索策略</p></div>
      <Spin spinning={loading} size="large">
        <Alert message="修改文档切分大小后需重建知识库索引才能生效" type="info" showIcon style={{ marginBottom: 16, borderRadius: 8 }} />
        <Card style={{ borderRadius: 12, marginBottom: 16 }}>
          <Form form={form} layout="vertical">
            {CONFIG_KEYS.map((item) => (
              <Form.Item key={item.key} name={item.key} label={<><strong>{item.label}</strong><span style={{ color: "#999", marginLeft: 8, fontWeight: 400, fontSize: 13 }}>{item.desc}</span></>}>
                {item.type === "textarea"
                  ? <Input.TextArea rows={4} />
                  : <InputNumber style={{ width: 200 }} min={item.key === "temperature" ? 0 : 1}
                      max={item.key === "temperature" ? 1 : 4096}
                      step={item.key === "temperature" ? 0.1 : 1} />}
              </Form.Item>
            ))}
          </Form>
          <Button type="primary" icon={<SaveOutlined />} onClick={save} loading={saving} size="large">保存配置</Button>
        </Card>
        <Card title="知识库版本" style={{ borderRadius: 12 }}>
          <Button icon={<ReloadOutlined />} onClick={rebuildKB} style={{ marginBottom: 16 }}>重建知识库索引</Button>
          {kbVersions.length === 0 && <div style={{ color: "#999" }}>暂无版本记录</div>}
          {kbVersions.map((v: any, i: number) => (
            <div key={i} style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0", display: "flex", justifyContent: "space-between" }}>
              <span>{v.version_tag}</span>
              <span style={{ color: "#999", fontSize: 13 }}>{v.created_at?.slice(0, 19)} — {v.document_count} 篇文档, {v.chunk_count} chunks</span>
            </div>
          ))}
        </Card>
      </Spin>
    </div>
  );
}
