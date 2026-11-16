import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, App as AntdApp, Button, Card, Col, Descriptions, Empty, Input, Modal, Popconfirm,
  Progress, Row, Segmented, Select, Space, Spin, Statistic, Steps, Table, Tag, Tooltip, Upload,
} from "antd";
import {
  CloudDownloadOutlined, CloudUploadOutlined, DeleteOutlined, EditOutlined,
  EyeOutlined, FileDoneOutlined, FileSearchOutlined, FileTextOutlined,
  CheckOutlined, CloseOutlined, ReloadOutlined, SafetyCertificateOutlined,
} from "@ant-design/icons";
import type { UploadFile, UploadProps } from "antd";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api from "../services/api";
import { useAuthStore } from "../store/authStore";


type DocumentStatus = "PROCESSING" | "READY" | "ERROR";
type ReviewStatus = "PENDING" | "APPROVED" | "REJECTED";
interface KnowledgeDocument {
  id: number;
  title: string;
  filename: string;
  mime_type: string;
  size: number;
  chunk_count: number;
  status: DocumentStatus;
  review_status: ReviewStatus;
  review_note?: string;
  reviewed_at?: string;
  processing_step?: string;
  error?: string;
  category?: string;
  uploader_name?: string;
  created_at: string;
  updated_at: string;
}

interface PageResult {
  items: KnowledgeDocument[];
  total: number;
  page: number;
  page_size: number;
}

const MAX_BYTES = 50 * 1024 * 1024;
const ACCEPTED = [".pdf", ".doc", ".docx", ".txt", ".md"];
const statusMap: Record<DocumentStatus, { color: string; label: string }> = {
  READY: { color: "success", label: "已完成" },
  PROCESSING: { color: "processing", label: "处理中" },
  ERROR: { color: "error", label: "处理失败" },
};
const reviewMap: Record<ReviewStatus, { color: string; label: string }> = {
  PENDING: { color: "warning", label: "待管理员审核" },
  APPROVED: { color: "success", label: "审核通过" },
  REJECTED: { color: "error", label: "已驳回" },
};
const stepOrder = ["UPLOADED", "EXTRACTING", "CHUNKING", "EMBEDDING", "COMPLETED"];
const stepItems = ["上传完成", "文本提取", "文本切分", "向量化", "处理完成"].map((title) => ({ title }));

const suffixOf = (name: string) => name.slice(name.lastIndexOf(".")).toLowerCase();
const formatSize = (size: number) => size >= 1024 * 1024
  ? `${(size / 1024 / 1024).toFixed(1)} MB`
  : `${Math.max(1, Math.round(size / 1024))} KB`;
const errorText = (error: any, fallback: string) => error?.response?.data?.detail || fallback;

export default function KnowledgePage() {
  const { message } = AntdApp.useApp();
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.role === "ADMIN";
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("校园服务");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string>();
  const [reviewStatus, setReviewStatus] = useState<string>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [detail, setDetail] = useState<any>();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [previewMode, setPreviewMode] = useState<"rendered" | "source">("rendered");
  const [editDoc, setEditDoc] = useState<KnowledgeDocument>();
  const [editTitle, setEditTitle] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editContent, setEditContent] = useState("");
  const [originalEditContent, setOriginalEditContent] = useState("");
  const [editContentLoading, setEditContentLoading] = useState(false);
  const [replacement, setReplacement] = useState<UploadFile[]>([]);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number>();
  const [rejecting, setRejecting] = useState<KnowledgeDocument>();
  const [reviewNote, setReviewNote] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => { setSearch(query.trim()); setPage(1); }, 350);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const data = await api.get<PageResult>("/doc/list", {
        params: { q: search || undefined, status, review_status: reviewStatus, page, page_size: pageSize },
      });
      setDocs(data.items);
      setTotal(data.total);
    } catch (error) {
      if (!quiet) message.error(errorText(error, "文档列表加载失败"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [page, pageSize, reviewStatus, search, status]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!docs.some((doc) => doc.review_status === "PENDING" || (doc.review_status === "APPROVED" && doc.status === "PROCESSING"))) return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [docs, load]);

  const validateFile = (file: File) => {
    if (!ACCEPTED.includes(suffixOf(file.name))) {
      message.error("仅支持 PDF、Word、TXT 和 Markdown 文档");
      return false;
    }
    if (file.size > MAX_BYTES) {
      message.error("单个文件不能超过 50MB");
      return false;
    }
    if (!file.size) {
      message.error("不能上传空文件");
      return false;
    }
    return true;
  };

  const uploadProps: UploadProps = {
    name: "file",
    accept: ACCEPTED.join(","),
    multiple: false,
    showUploadList: false,
    disabled: uploading,
    beforeUpload: (file) => validateFile(file),
    customRequest: async ({ file, onError, onSuccess, onProgress }) => {
      const raw = file as File;
      if (!validateFile(raw)) return;
      const form = new FormData();
      form.append("file", raw);
      if (title.trim()) form.append("title", title.trim());
      form.append("category", category);
      setUploading(true);
      setUploadProgress(0);
      try {
        await api.post("/doc/upload", form, {
          headers: { "Content-Type": "multipart/form-data" },
          onUploadProgress: (event: any) => {
            const percent = event.total ? Math.round((event.loaded / event.total) * 100) : 0;
            setUploadProgress(percent);
            onProgress?.({ percent });
          },
        });
        onSuccess?.({});
        message.success(isAdmin
          ? `${raw.name} 已上传，正在后台解析与向量化`
          : `${raw.name} 已提交，管理员审核通过后将自动进入知识库`);
        setTitle("");
        setPage(1);
        await load(true);
      } catch (error: any) {
        onError?.(error);
        message.error(errorText(error, "上传失败，请稍后重试"));
      } finally {
        setUploading(false);
        setUploadProgress(0);
      }
    },
  };

  const reprocess = async (id: number) => {
    try {
      await api.post(`/doc/${id}/reprocess`);
      message.success("已提交重新处理，旧向量将被安全覆盖");
      await load(true);
    } catch (error) { message.error(errorText(error, "重新处理失败")); }
  };

  const remove = async (id: number) => {
    setDeletingId(id);
    try {
      await api.delete(`/doc/${id}`);
      message.success("文档、文本块、向量和原始文件已删除");
      setSelected((keys) => keys.filter((key) => key !== id));
      await load(true);
    } catch (error) { message.error(errorText(error, "删除失败")); }
    finally { setDeletingId(undefined); }
  };

  const showDetail = async (record: KnowledgeDocument) => {
    setDetail(record);
    setPreviewMode("rendered");
    setPreviewOpen(true);
    setDetailLoading(true);
    try {
      setDetail(await api.get(`/doc/${record.id}`));
    } catch (error) { message.error(errorText(error, "详情加载失败")); }
    finally { setDetailLoading(false); }
  };

  const download = async (record: KnowledgeDocument) => {
    try {
      const blob = await api.get<Blob>(`/doc/${record.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = record.filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { message.error(errorText(error, "下载失败")); }
  };

  const openEdit = async (record: KnowledgeDocument) => {
    setEditDoc(record);
    setEditTitle(record.title);
    setEditCategory(record.category || "其他");
    setEditContent("");
    setOriginalEditContent("");
    setReplacement([]);
    setEditContentLoading(true);
    try {
      const document: any = await api.get(`/doc/${record.id}`);
      const content = document.editable_content || "";
      setEditContent(content);
      setOriginalEditContent(content);
      if (document.editable_truncated) {
        message.warning("正文超过在线编辑上限，请通过替换原始文件更新完整内容");
      }
    } catch (error) {
      message.error(errorText(error, "知识正文加载失败"));
    } finally {
      setEditContentLoading(false);
    }
  };

  const saveEdit = async () => {
    if (!editDoc || editTitle.trim().length < 2) return message.warning("标题至少需要 2 个字符");
    setSaving(true);
    const form = new FormData();
    form.append("title", editTitle.trim());
    form.append("category", editCategory.trim() || "其他");
    if (replacement[0]?.originFileObj) form.append("file", replacement[0].originFileObj);
    else if (editContent !== originalEditContent) form.append("text_content", editContent);
    try {
      await api.put(`/doc/${editDoc.id}`, form, { headers: { "Content-Type": "multipart/form-data" } });
      message.success(replacement.length
        ? "原始文件已替换并开始重建索引"
        : editContent !== originalEditContent
          ? "知识正文已更新，正在覆盖旧向量"
          : "文档信息已更新并开始重建索引");
      setEditDoc(undefined);
      await load(true);
    } catch (error) { message.error(errorText(error, "保存失败")); }
    finally { setSaving(false); }
  };

  const batchAction = async (action: "delete" | "reprocess") => {
    if (!selected.length) return;
    try {
      const result = await api.post<any>("/doc/batch/action", { action, ids: selected });
      const failed = result.failed?.length || 0;
      failed ? message.warning(`已完成 ${result.succeeded.length} 项，${failed} 项失败`) : message.success("批量操作已提交");
      setSelected([]);
      await load(true);
    } catch (error) { message.error(errorText(error, "批量操作失败")); }
  };

  const review = async (record: KnowledgeDocument, action: "approve" | "reject", note = "") => {
    try {
      await api.post(`/doc/${record.id}/review`, { action, note });
      message.success(action === "approve" ? "审核已通过，文档开始构建索引" : "已驳回并通知上传者");
      setRejecting(undefined);
      setReviewNote("");
      await load(true);
    } catch (error) { message.error(errorText(error, "审核操作失败")); }
  };

  const pageStats = useMemo(() => ({
    ready: docs.filter((doc) => doc.status === "READY").length,
    processing: docs.filter((doc) => doc.status === "PROCESSING").length,
    pending: docs.filter((doc) => doc.review_status === "PENDING").length,
    chunks: docs.reduce((sum, doc) => sum + doc.chunk_count, 0),
  }), [docs]);

  const columns = [
    {
      title: "文档", dataIndex: "title", minWidth: 260,
      render: (text: string, record: KnowledgeDocument) => (
        <div className="kb-file-cell">
          <span className={`kb-file-icon ${suffixOf(record.filename).slice(1)}`}><FileTextOutlined /></span>
          <div><strong>{text}</strong><small>{record.filename}</small></div>
        </div>
      ),
    },
    { title: "分类", dataIndex: "category", width: 110, render: (value: string) => <Tag>{value || "其他"}</Tag> },
    { title: "大小", dataIndex: "size", width: 90, render: formatSize },
    { title: "文本块", dataIndex: "chunk_count", width: 90, render: (value: number) => value ? `${value} 块` : "—" },
    {
      title: "审核状态", dataIndex: "review_status", width: 140,
      render: (value: ReviewStatus, record: KnowledgeDocument) => (
        <Tooltip title={record.review_note || reviewMap[value]?.label}>
          <Tag color={reviewMap[value]?.color || "default"}>{reviewMap[value]?.label || value}</Tag>
        </Tooltip>
      ),
    },
    {
      title: "处理状态", dataIndex: "status", width: 150,
      render: (value: DocumentStatus, record: KnowledgeDocument) => {
        if (record.review_status === "PENDING") return <Tag>尚未处理</Tag>;
        if (record.review_status === "REJECTED") return <Tag>未进入知识库</Tag>;
        const mapped = statusMap[value] || { color: "default", label: value };
        const step = Math.max(0, stepOrder.indexOf(record.processing_step || "UPLOADED"));
        return <div className="kb-status-cell">
          <Tooltip title={value === "ERROR" ? record.error : `当前阶段：${stepItems[step]?.title || "处理中"}`}>
            <Tag color={mapped.color}>{mapped.label}</Tag>
          </Tooltip>
          {value === "PROCESSING" && <Progress percent={(step + 1) * 20} showInfo={false} size="small" />}
        </div>;
      },
    },
    {
      title: "上传信息", width: 150,
      render: (_: unknown, record: KnowledgeDocument) => <div className="kb-meta-cell">
        <span>{record.uploader_name || "管理员"}</span>
        <small>{new Date(record.created_at).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" })}</small>
      </div>,
    },
    {
      title: "操作", fixed: "right" as const, width: 245,
      render: (_: unknown, record: KnowledgeDocument) => <Space size={2}>
        <Tooltip title="查看详情与文本预览"><Button type="text" icon={<EyeOutlined />} onClick={() => showDetail(record)} /></Tooltip>
        <Tooltip title="下载原始文件"><Button type="text" icon={<CloudDownloadOutlined />} onClick={() => download(record)} /></Tooltip>
        {isAdmin && record.review_status === "PENDING" && <>
          <Tooltip title="审核通过并开始构建索引"><Button type="text" className="kb-approve-btn" icon={<CheckOutlined />} onClick={() => review(record, "approve", "内容符合知识库规范")} /></Tooltip>
          <Tooltip title="驳回提交"><Button type="text" danger icon={<CloseOutlined />} onClick={() => { setRejecting(record); setReviewNote(""); }} /></Tooltip>
        </>}
        {isAdmin && <Tooltip title="编辑信息或替换文件"><Button type="text" icon={<EditOutlined />} onClick={() => openEdit(record)} disabled={record.status === "PROCESSING" && record.review_status === "APPROVED"} /></Tooltip>}
        {isAdmin && record.review_status === "APPROVED" && <Tooltip title="重新提取、切分并覆盖旧向量"><Button type="text" icon={<ReloadOutlined />} onClick={() => reprocess(record.id)} disabled={record.status === "PROCESSING"} /></Tooltip>}
        <Popconfirm title="确认删除该文档？" description="原始文件、文本块和向量将一并删除，且无法恢复。" onConfirm={() => remove(record.id)} okText="确认删除" cancelText="取消" okButtonProps={{ danger: true, loading: deletingId === record.id }}>
          <Tooltip title={!isAdmin && record.review_status === "APPROVED" ? "已通过文档请联系管理员删除" : "删除"}><Button type="text" danger icon={<DeleteOutlined />} disabled={(!isAdmin && record.review_status === "APPROVED") || (record.review_status === "APPROVED" && record.status === "PROCESSING")} /></Tooltip>
        </Popconfirm>
      </Space>,
    },
  ];

  return <div className="knowledge-page fade-up">
    <div className="page-header kb-page-header">
      <div><h2>{isAdmin ? "知识库审核与管理" : "我的文档提交"}</h2><p>{isAdmin ? "审核资料来源，跟踪文本提取、语义切分、向量化与索引状态" : "上传校园资料并实时跟踪审核和入库进度"}</p></div>
      <Tag icon={<SafetyCertificateOutlined />} color="blue">{isAdmin ? "管理员审核工作台" : "提交内容仅本人和管理员可见"}</Tag>
    </div>

    <Row gutter={[14, 14]} className="kb-stats">
      <Col xs={12} lg={6}><Card><Statistic title="文档总数" value={total} prefix={<FileTextOutlined />} /></Card></Col>
      <Col xs={12} lg={6}><Card><Statistic title="本页已入库" value={pageStats.ready} prefix={<FileDoneOutlined />} /></Card></Col>
      <Col xs={12} lg={6}><Card><Statistic title="待审核" value={pageStats.pending} prefix={<SafetyCertificateOutlined />} /></Card></Col>
      <Col xs={12} lg={6}><Card><Statistic title="本页文本块" value={pageStats.chunks} prefix={<FileSearchOutlined />} /></Card></Col>
    </Row>

    <Card className="kb-upload-card">
      <div className="kb-upload-layout">
        <Upload.Dragger {...uploadProps} className="kb-dragger">
          <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p>
          <p className="ant-upload-text">点击选择或将文档拖到这里</p>
          <p className="ant-upload-hint">PDF / DOC / DOCX / TXT / MD · 单文件最大 50MB</p>
        </Upload.Dragger>
        <div className="kb-upload-options">
          <label>文档标题 <span>可选，默认使用文件名</span></label>
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：本科生奖学金管理办法" maxLength={120} />
          <label>知识分类</label>
          <Select value={category} onChange={setCategory} options={["校园服务", "学校概况", "教学管理", "招生就业", "规章制度", "其他"].map((value) => ({ value, label: value }))} />
          {uploading && <div className="kb-upload-progress"><span>文件上传中</span><Progress percent={uploadProgress} status="active" /></div>}
          <Alert type="info" showIcon message={isAdmin ? "管理员上传默认直接入库，处理任务在后台运行。" : "提交后由管理员审核；通过后系统自动完成提取、切分和向量化。"} />
        </div>
      </div>
    </Card>

    <Card className="kb-table-card">
      <div className="kb-toolbar">
        <Space wrap>
          <Input.Search allowClear value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或文件名" style={{ width: 260 }} />
          <Select allowClear value={status} onChange={(value) => { setStatus(value); setPage(1); }} placeholder="全部状态" style={{ width: 140 }} options={Object.entries(statusMap).map(([value, item]) => ({ value, label: item.label }))} />
          <Select allowClear value={reviewStatus} onChange={(value) => { setReviewStatus(value); setPage(1); }} placeholder="全部审核状态" style={{ width: 160 }} options={Object.entries(reviewMap).map(([value, item]) => ({ value, label: item.label }))} />
          <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
        </Space>
        {isAdmin && selected.length > 0 && <Space className="kb-batch-bar">
          <span>已选 {selected.length} 项</span>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => batchAction("reprocess")}>批量重处理</Button>
          <Popconfirm title={`确认删除选中的 ${selected.length} 篇文档？`} onConfirm={() => batchAction("delete")} okButtonProps={{ danger: true }}>
            <Button size="small" danger icon={<DeleteOutlined />}>批量删除</Button>
          </Popconfirm>
        </Space>}
      </div>
      <Table<KnowledgeDocument>
        rowKey="id" columns={columns} dataSource={docs} loading={loading} scroll={{ x: 1180 }}
        rowSelection={isAdmin ? { selectedRowKeys: selected, onChange: setSelected, getCheckboxProps: (record) => ({ disabled: record.review_status === "APPROVED" && record.status === "PROCESSING" }) } : undefined}
        pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50], showTotal: (value) => `共 ${value} 篇文档`, onChange: (next, size) => { setPage(next); setPageSize(size); } }}
        locale={{ emptyText: <Empty description="暂无匹配文档，请上传第一篇知识资料" /> }}
      />
    </Card>

    <Modal title="文档详情与文本预览" open={previewOpen} onCancel={() => setPreviewOpen(false)} footer={<Button onClick={() => setPreviewOpen(false)}>关闭</Button>} width={820}>
      <Spin spinning={detailLoading} tip="正在加载文档信息…">
      {detail && <>
        <Descriptions bordered size="small" column={2} items={[
          { key: "title", label: "文档标题", children: detail.title },
          { key: "file", label: "原始文件", children: detail.filename },
          { key: "category", label: "分类", children: detail.category || "其他" },
          { key: "size", label: "文件大小", children: formatSize(detail.size) },
          { key: "chunks", label: "文本块", children: `${detail.chunk_count} 块` },
          { key: "status", label: "状态", children: <Tag color={statusMap[detail.status as DocumentStatus]?.color}>{statusMap[detail.status as DocumentStatus]?.label}</Tag> },
          { key: "review", label: "审核状态", children: <Tag color={reviewMap[detail.review_status as ReviewStatus]?.color}>{reviewMap[detail.review_status as ReviewStatus]?.label}</Tag> },
          { key: "reviewNote", label: "审核意见", span: 1, children: detail.review_note || "暂无" },
        ]} />
        {detail.review_status === "APPROVED" && detail.status === "PROCESSING" && <Steps className="kb-detail-steps" current={Math.max(0, stepOrder.indexOf(detail.processing_step))} size="small" items={stepItems} />}
        {detail.review_status === "PENDING" && <Alert type="warning" showIcon message="等待管理员审核" description="审核通过后系统将自动提取文本并构建向量索引。" style={{ marginTop: 16 }} />}
        {detail.review_status === "REJECTED" && <Alert type="error" showIcon message="提交未通过" description={detail.review_note} style={{ marginTop: 16 }} />}
        {detail.error && <Alert type="error" showIcon message="处理失败" description={detail.error} style={{ marginTop: 16 }} />}
        {detail.preview_pending && <Alert
          type="info"
          showIcon
          message="正在恢复源文件结构"
          description="当前先展示已入库文本块；系统正在后台解析原始文件，稍后点击“刷新预览”即可看到标题、列表和表格结构。"
          action={<Button size="small" onClick={() => showDetail(detail)}>刷新预览</Button>}
          style={{ marginTop: 16 }}
        />}
        <div className="kb-preview">
          <div className="kb-preview-head">
            <div><strong>文档内容预览</strong><span>按源文件层级还原标题、列表、段落与表格</span></div>
            <Space>
              {detail.preview_truncated && <Tag>已截取前 20,000 字</Tag>}
              <Segmented
                size="small"
                value={previewMode}
                onChange={(value) => setPreviewMode(value as "rendered" | "source")}
                options={[{ label: "格式化预览", value: "rendered" }, { label: "源文本", value: "source" }]}
              />
            </Space>
          </div>
          {detail.preview ? (
            previewMode === "rendered"
              ? <div className="kb-document-render"><ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.preview}</ReactMarkdown></div>
              : <pre className="kb-document-source">{detail.preview}</pre>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={detail.review_status === "PENDING" ? "审核通过并处理完成后将在此显示提取文本" : "暂无可预览文本"} />}
        </div>
      </>}
      </Spin>
    </Modal>

    <Modal title="驳回文档提交" open={Boolean(rejecting)} onCancel={() => setRejecting(undefined)} onOk={() => rejecting && review(rejecting, "reject", reviewNote)} okText="确认驳回" cancelText="取消" okButtonProps={{ danger: true, disabled: reviewNote.trim().length < 2 }}>
      <Alert type="warning" showIcon message={rejecting ? `将驳回「${rejecting.title}」` : ""} description="请给出清晰、可执行的修改意见，上传者将在状态详情中看到。" />
      <Input.TextArea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="例如：缺少发布部门与生效日期，请补充后重新提交" maxLength={500} showCount rows={4} style={{ marginTop: 16 }} />
    </Modal>

    <Modal title="编辑文档" open={Boolean(editDoc)} onCancel={() => setEditDoc(undefined)} onOk={saveEdit} confirmLoading={saving} okButtonProps={{ disabled: editContentLoading }} okText="保存并重新处理" cancelText="取消" width={1120}>
      <div className="kb-edit-form">
        <label>文档标题</label><Input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} maxLength={120} />
        <label>知识分类</label><Select value={editCategory} onChange={setEditCategory} options={["校园服务", "学校概况", "教学管理", "招生就业", "规章制度", "其他"].map((value) => ({ value, label: value }))} />
        <label>知识正文 <span>左侧编辑结构化文本，右侧实时查看最终展示效果；保存后将覆盖旧向量</span></label>
        <Spin spinning={editContentLoading}>
          <div className="kb-editor-grid">
            <section className="kb-editor-pane">
              <div className="kb-editor-pane-head"><strong>结构化文本</strong><span>支持 Markdown 标题、列表和表格</span></div>
              <Input.TextArea
                value={editContent}
                onChange={(event) => setEditContent(event.target.value)}
                disabled={replacement.length > 0}
                placeholder="输入用于知识检索与问答的正文内容"
                autoSize={false}
                maxLength={200000}
                showCount
              />
            </section>
            <section className="kb-editor-pane kb-editor-preview-pane">
              <div className="kb-editor-pane-head"><strong>实时预览</strong><span>保存前检查内容层级</span></div>
              <div className="kb-document-render">
                {editContent
                  ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{editContent}</ReactMarkdown>
                  : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无正文内容" />}
              </div>
            </section>
          </div>
        </Spin>
        <label>替换原始文件 <span>可选；保存后会覆盖旧向量</span></label>
        <Upload beforeUpload={(file) => { if (!validateFile(file)) return Upload.LIST_IGNORE; setReplacement([file]); return false; }} fileList={replacement} onRemove={() => { setReplacement([]); return true; }} maxCount={1} accept={ACCEPTED.join(",")}>
          <Button icon={<CloudUploadOutlined />}>选择新文件</Button>
        </Upload>
      </div>
    </Modal>
  </div>;
}
