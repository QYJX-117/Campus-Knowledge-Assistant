import { useState, useRef, useEffect, useCallback } from "react";
import { App as AntdApp, Input, Button, Tooltip, Upload, Modal } from "antd";
import {
  SendOutlined, PlusOutlined, DeleteOutlined,
  CopyOutlined, StopOutlined, DownloadOutlined,
  HistoryOutlined, CloseOutlined, FileTextOutlined, CheckOutlined,
  LikeOutlined, DislikeOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuthStore } from "../store/authStore";
import api from "../services/api";

interface Source { index: number; title: string; content: string; score: number; source_url?: string; category?: string; }
type GenerationMode = "llm" | "fallback" | "cache" | "no_context" | "guardrail";
interface Msg { role: "user" | "ai"; text: string; sources?: Source[]; id?: string; generationMode?: GenerationMode; feedback?: "helpful" | "unhelpful"; }
interface Conv { id: number; title: string; message_count: number; updated_at: string; }

const msgId = () => `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

export default function ChatPage() {
  const { message, modal } = AntdApp.useApp();
  const { token, user } = useAuthStore();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [convs, setConvs] = useState<Conv[]>([]);
  const [cid, setCid] = useState<number | undefined>();
  const [showHistory, setShowHistory] = useState(true);
  const [showToc, setShowToc] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [inputFocused, setInputFocused] = useState(false);
  const [feedbackLoading, setFeedbackLoading] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const msgRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const loadConvs = useCallback(async () => {
    try { setConvs(await api.get("/conversations")); } catch {}
  }, []);

  useEffect(() => { loadConvs(); }, [loadConvs]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const send = async (text?: string) => {
    const q = (text || input).trim();
    if (!q || loading) return;
    setMsgs((current) => [...current, { role: "user", text: q, id: msgId() }, { role: "ai", text: "", id: msgId() }]);
    setInput("");
    setShowToc(false);
    setLoading(true);
    abort.current = new AbortController();
    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: q, conversation_id: cid, strategy: "hybrid" }),
        signal: abort.current.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const p of parts) {
          const evt = p.match(/^event: (\w+)/m)?.[1];
          const data = p.match(/^data: (.+)$/m)?.[1];
          if (!data) continue;
          try {
            if (evt === "meta") {
              const m = JSON.parse(data);
              if (m.conversation_id) setCid(m.conversation_id);
              setMsgs((items) => {
                const last = items[items.length - 1];
                if (!last) return items;
                last.sources = m.sources;
                last.generationMode = m.generation_mode;
                return [...items.slice(0, -1), { ...last }];
              });
            }
            if (evt === "token") {
              const { text: t } = JSON.parse(data);
              setMsgs((items) => {
                const last = items[items.length - 1];
                if (!last) return items;
                last.text += t;
                return [...items.slice(0, -1), { ...last }];
              });
            }
            if (evt === "done") break;
          } catch {}
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setMsgs((items) => {
          const last = items[items.length - 1];
          if (last && !last.text) last.text = "请求失败，请重试";
          return [...items.slice(0, -1), last ? { ...last } : last];
        });
        message.error("请求失败");
      }
    }
    setLoading(false);
    abort.current = null;
    loadConvs();
  };

  const loadConv = async (id: number) => {
    try {
      const d: any = await api.get(`/conversations/${id}`);
      setCid(id);
      setShowToc(false);
      setInput("");
      setMsgs(d.messages.map((m: any) => ({
        role: m.role === "USER" ? "user" : "ai",
        text: m.content,
        sources: m.sources,
        id: msgId(),
      })));
    } catch {
      message.error("加载失败");
    }
  };

  const delConv = async (id: number, e?: React.MouseEvent) => {
    e?.stopPropagation();
    modal.confirm({
      title: "删除会话？",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        await api.delete(`/conversations/${id}`);
        if (cid === id) {
          setCid(undefined);
          setMsgs([]);
          setInput("");
          setShowToc(false);
        }
        loadConvs();
      },
    });
  };

  const copyText = async (text: string, idx: number) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      el.remove();
    }
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
    message.success("已复制");
  };

  const submitFeedback = async (msg: Msg, helpful: boolean) => {
    if (!cid || user?.role === "GUEST" || !msg.id) return;
    setFeedbackLoading(msg.id);
    try {
      const result: any = await api.post("/chat/feedback", { conversation_id: cid, message_id: 0, helpful });
      setMsgs((items) => items.map((item) => item.id === msg.id ? {
        ...item,
        text: result.corrected_answer || item.text,
        sources: result.corrected_sources?.length ? result.corrected_sources : item.sources,
        generationMode: result.corrected_answer ? "llm" : item.generationMode,
        feedback: helpful ? "helpful" : "unhelpful",
      } : item));
      message.success(result.corrected_answer ? "已重新检索并优化回答" : (result.message || "感谢反馈"));
    } catch {
      message.error("反馈提交失败，请稍后重试");
    } finally {
      setFeedbackLoading(null);
    }
  };

  const exportMD = () => {
    if (!msgs.length) return;
    let md = "# 会话记录\n\n";
    msgs.forEach((m, i) => {
      md += `### ${m.role === "user" ? "提问" : "回答"} ${i + 1}\n${m.text}\n\n`;
      if (m.sources?.length) {
        md += "**参考来源:**\n";
        m.sources.forEach((s: Source) => md += `- [${s.index}] ${s.title}（相关度 ${(s.score * 100).toFixed(0)}%）\n`);
        md += "\n";
      }
    });
    const b = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const a = document.createElement("a");
    const url = URL.createObjectURL(b);
    a.href = url;
    a.download = `会话-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.success("已导出");
  };

  const handleFile = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", file.name);
    try {
      await api.post("/documents", form, { headers: { "Content-Type": "multipart/form-data" } });
      message.success(`${file.name} 已上传`);
    } catch {
      message.error("上传失败");
    }
    return false;
  };

  const scrollToMsg = (id: string) => {
    msgRefs.current.get(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const tocItems = msgs.filter((m) => m.role === "user");
  const hasMessages = msgs.length > 0;
  const showHeaderActions = hasMessages;

  const renderComposer = (mode: "empty" | "docked") => (
    <div className={`chat-composer-shell chat-composer-shell--${mode} ${inputFocused ? "is-focused" : ""}`}>
      <div className="chat-composer">
        <Upload beforeUpload={handleFile} showUploadList={false} accept=".txt,.md,.pdf,.docx">
          <Tooltip title="上传文件到知识库">
            <Button type="text" icon={<PlusOutlined />} className="chat-icon-attach" />
          </Tooltip>
        </Upload>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          onFocus={() => setInputFocused(true)}
          onBlur={() => setInputFocused(false)}
          placeholder="问问河海智答，Enter 发送 · Shift+Enter 换行"
          autoSize={{ minRows: 1, maxRows: 5 }}
          disabled={loading}
          variant="borderless"
          className="chat-composer-input"
        />
        {loading ? (
          <Button danger icon={<StopOutlined />} onClick={() => abort.current?.abort()} className="chat-send-btn" />
        ) : (
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => send()}
            disabled={!input.trim()}
            className="chat-send-btn"
          />
        )}
      </div>
    </div>
  );

  return (
    <div className={`chat-workbench ${hasMessages ? "chat-workbench--active" : "chat-workbench--empty"} ${showHistory ? "chat-workbench--history-open" : "chat-workbench--history-closed"}`}>
      <aside className={`chat-history-panel ${showHistory ? "is-open" : "is-collapsed"}`}>
        <div className="chat-history-head">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={() => { setCid(undefined); setMsgs([]); setInput(""); setShowToc(false); }}
            className="chat-new-conv"
          >
            新对话
          </Button>
        </div>
        <div className="chat-history-list">
          {convs.map((c) => (
            <div key={c.id} onClick={() => loadConv(c.id)} className={`chat-history-item ${c.id === cid ? "is-active" : ""}`}>
              <div className="chat-history-item-head">
                <div className="chat-history-title">{c.title || "新会话"}</div>
                <DeleteOutlined className="chat-history-delete" onClick={(e) => delConv(c.id, e)} />
              </div>
              <div className="chat-history-meta">{c.message_count} 条消息</div>
            </div>
          ))}
          {convs.length === 0 && <div className="chat-history-empty">暂无历史会话</div>}
        </div>
        <div className="chat-history-foot">
          <Button type="text" icon={<CloseOutlined />} size="small" block onClick={() => setShowHistory(false)} className="chat-history-toggle">
            收起侧栏
          </Button>
        </div>
      </aside>

      <section className="chat-main">
        <div className="chat-surface-glow chat-surface-glow-a" />
        <div className="chat-surface-glow chat-surface-glow-b" />

        <header className="chat-topbar">
          <div className="chat-topbar-left">
            {!showHistory && (
              <Tooltip title="显示历史">
                <Button type="text" icon={<HistoryOutlined />} onClick={() => setShowHistory(true)} className="chat-icon-btn" />
              </Tooltip>
            )}
          </div>
          {showHeaderActions && (
            <div className="chat-topbar-actions">
              <Tooltip title="对话概览">
                <Button
                  type="text"
                  size="small"
                  icon={<FileTextOutlined />}
                  onClick={() => setShowToc(!showToc)}
                  className={`chat-icon-btn ${showToc ? "is-active" : ""}`}
                />
              </Tooltip>
              <Tooltip title="导出 MD">
                <Button type="text" size="small" icon={<DownloadOutlined />} onClick={exportMD} className="chat-icon-btn" />
              </Tooltip>
            </div>
          )}
        </header>

        <main className={`chat-stage ${hasMessages ? "chat-stage--active" : "chat-stage--empty"}`}>
          {!hasMessages && (
            <section className="chat-empty-hero">
              <div className="chat-empty-mark">
                <span className="chat-droplet-mark">
                  <span className="chat-droplet-highlight" />
                  <span className="chat-droplet-core" />
                </span>
              </div>
              <p>制度、流程、办事指南和校园知识，一次问清。</p>
              {renderComposer("empty")}
            </section>
          )}

          {hasMessages && (
            <div className="chat-thread-wrap">
              <div className="chat-message-column">
                {msgs.map((m, i) => (
                  <div
                    key={m.id || i}
                    ref={(el) => { if (el && m.id) msgRefs.current.set(m.id, el); }}
                    className={`chat-message-row ${m.role}`}
                  >
                    <div className={`chat-message-bubble ${m.role}`}>
                      {m.role === "ai" && !m.text && loading && (
                        <span className="chat-loading-dots">
                          {[0, 1, 2].map((d) => <span key={d} style={{ animationDelay: `${d * 0.15}s` }} />)}
                        </span>
                      )}
                      {m.role === "ai" && m.text ? (
                        <>
                          <div className="answer-mode-row">
                            <span className={`answer-mode ${m.generationMode === "fallback" ? "fallback" : ""}`}>
                              {m.generationMode === "fallback" ? "知识库降级摘录" : m.generationMode === "cache" ? "高频答案缓存" : m.generationMode === "no_context" ? "未检索到证据" : "AI 综合生成"}
                            </span>
                          </div>
                          <div className="ai-markdown">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                          </div>
                        </>
                      ) : (
                        <span style={{ whiteSpace: "pre-wrap" }}>{m.text}</span>
                      )}

                      {m.text && m.role === "ai" && m.sources && m.sources.length > 0 && (
                        <div className="chat-sources-block">
                          <div className="chat-sources-title">参考来源</div>
                          <div className="source-list">
                            {m.sources.map((s: Source) => (
                              <button
                                key={s.index}
                                type="button"
                                className="source-row"
                                onClick={() => modal.info({
                                  title: s.title,
                                  content: <div style={{ maxHeight: 420, overflow: "auto", whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.8 }}>{s.content}</div>,
                                  width: 680,
                                })}
                              >
                                <span className="source-index">[{s.index}]</span>
                                <span className="source-title">{s.title}</span>
                                <span className="source-relevance">相关度 {(s.score * 100).toFixed(0)}%</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {m.text && (
                        <div className="chat-message-actions">
                          {m.role === "ai" && cid && user?.role !== "GUEST" && i === msgs.length - 1 && (
                            <div className="chat-feedback-actions">
                              <Tooltip title="回答有帮助">
                                <Button
                                  type="text"
                                  size="small"
                                  aria-label="回答有帮助"
                                  loading={feedbackLoading === m.id && !m.feedback}
                                  icon={<LikeOutlined />}
                                  disabled={!!m.feedback}
                                  onClick={() => submitFeedback(m, true)}
                                  className={`chat-feedback-btn ${m.feedback === "helpful" ? "is-active" : ""}`}
                                />
                              </Tooltip>
                              <Tooltip title="需要改进并重新检索回答">
                                <Button
                                  type="text"
                                  size="small"
                                  aria-label="需要改进"
                                  disabled={!!m.feedback}
                                  icon={<DislikeOutlined />}
                                  onClick={() => submitFeedback(m, false)}
                                  className={`chat-feedback-btn ${m.feedback === "unhelpful" ? "is-warning" : ""}`}
                                />
                              </Tooltip>
                            </div>
                          )}
                          <Tooltip title={m.role === "user" ? "复制问题" : "复制回答"}>
                            <Button
                              type="text"
                              size="small"
                              aria-label={m.role === "user" ? "复制问题" : "复制回答"}
                              icon={copiedIdx === i ? <CheckOutlined /> : <CopyOutlined />}
                              className={`chat-copy-btn ${copiedIdx === i ? "is-active" : ""} ${m.role}`}
                              onClick={() => copyText(m.text, i)}
                            />
                          </Tooltip>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                <div ref={bottom} />
              </div>

              {showToc && tocItems.length > 0 && (
                <aside className="chat-toc-panel">
                  <div className="chat-toc-head">
                    <span>对话概览</span>
                    <Button type="text" size="small" icon={<CloseOutlined />} onClick={() => setShowToc(false)} className="chat-icon-btn" />
                  </div>
                  <div className="chat-toc-list">
                    {tocItems.map((m, i) => (
                      <button key={m.id || i} type="button" onClick={() => scrollToMsg(m.id!)} className="chat-toc-item">
                        <span>Q{i + 1}</span>
                        <strong>{m.text.slice(0, 38)}{m.text.length > 38 ? "…" : ""}</strong>
                      </button>
                    ))}
                  </div>
                </aside>
              )}
            </div>
          )}

        </main>
        {hasMessages && renderComposer("docked")}
      </section>
    </div>
  );
}
