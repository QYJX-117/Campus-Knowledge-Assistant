/** Campus Q&A Widget — Shadow DOM embedded chat component */
import { useState, useRef, useEffect, useCallback, useId } from "react";

/* ── Types ──────────────────────────────────────────────────── */
interface Source {
  index: number;
  title: string;
  source_url: string;
  category: string;
  score: number;
  content: string;
}

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sources?: Source[];
  isStreaming?: boolean;
  timestamp: number;
}

type WidgetView = "bubble" | "chat";
type ChatPhase = "welcome" | "chatting";

interface WidgetConfig {
  title?: string;
  guestApiBase?: string;
  quickQuestions?: string[];
  loginUrl?: string;
  showSources?: boolean;
  draggable?: boolean;
  accessToken?: string;
}

interface DockPosition { right: number; bottom: number; }
interface DragSession {
  pointerId: number;
  startX: number;
  startY: number;
  startRight: number;
  startBottom: number;
  moved: boolean;
}

/* ── Quick Questions Default ────────────────────────────────── */
const DEFAULT_QUESTIONS = [
  "如何办理校园卡？",
  "图书馆开放时间是？",
  "河海大学的校训是什么？",
  "奖学金如何申请？",
];

/* ── Helpers ────────────────────────────────────────────────── */
function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function withoutCitations(text: string): string {
  return text.replace(/(?:\[|【)\d+(?:\]|】)/g, "").replace(/[ \t]+([，。；！？])/g, "$1");
}

function clampDock(position: DockPosition, view: WidgetView): DockPosition {
  if (view === "chat" && window.innerWidth <= 480) return { right: 0, bottom: 0 };
  const margin = 8;
  const width = view === "chat" ? Math.min(400, window.innerWidth - 32) : 56;
  const height = view === "chat" ? Math.min(600, window.innerHeight - 48) : 56;
  return {
    right: Math.max(margin, Math.min(position.right, Math.max(margin, window.innerWidth - width - margin))),
    bottom: Math.max(margin, Math.min(position.bottom, Math.max(margin, window.innerHeight - height - margin))),
  };
}

/* ── Icons (inline SVGs, no icon library) ───────────────────── */
const IconChat = () => {
  const uid = useId().replace(/:/g, "");
  const glowId = `wgDropGlow-${uid}`;
  const strokeId = `wgDropStroke-${uid}`;
  return (
  <svg className="wg-droplet-svg" viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <defs>
      <radialGradient id={glowId} cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(18 12) rotate(61) scale(38)">
        <stop stopColor="white" stopOpacity="0.95" />
        <stop offset="0.36" stopColor="#BFE7FF" stopOpacity="0.85" />
        <stop offset="0.72" stopColor="#1492FF" stopOpacity="0.95" />
        <stop offset="1" stopColor="#0458C7" />
      </radialGradient>
      <linearGradient id={strokeId} x1="12" y1="6" x2="40" y2="43" gradientUnits="userSpaceOnUse">
        <stop stopColor="white" stopOpacity="0.92" />
        <stop offset="1" stopColor="white" stopOpacity="0.14" />
      </linearGradient>
    </defs>
    <path d="M25.2 4.6C21.4 10.4 12 17.8 12 28.2C12 38 19.2 44 27 44C35.1 44 41 38.1 41 30.2C41 19.9 30 12.4 25.2 4.6Z" fill={`url(#${glowId})`} />
    <path d="M25.2 4.6C21.4 10.4 12 17.8 12 28.2C12 38 19.2 44 27 44C35.1 44 41 38.1 41 30.2C41 19.9 30 12.4 25.2 4.6Z" stroke={`url(#${strokeId})`} strokeWidth="2" />
    <path d="M18.8 18.2C22.3 13.5 25.1 9 25.1 9" stroke="white" strokeWidth="3" strokeLinecap="round" opacity="0.8" />
    <circle cx="30" cy="33" r="5" fill="#0B6FCC" opacity="0.72" />
  </svg>
  );
};
const IconClose = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
);
const IconSend = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
);
const IconSchool = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>
);
const IconAlert = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
);
const IconRefresh = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
);

/* ═══════════════════════════════════════════════════════════════
   Main Widget Component
   ═══════════════════════════════════════════════════════════════ */
export default function Widget({
  title = "校园问答助手",
  guestApiBase = "",
  quickQuestions = DEFAULT_QUESTIONS,
  loginUrl = "",
  showSources = true,
  draggable = false,
  accessToken = "",
}: WidgetConfig) {
  const [view, setView] = useState<WidgetView>("bubble");
  const [phase, setPhase] = useState<ChatPhase>("welcome");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [drawerSource, setDrawerSource] = useState<Source | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(!navigator.onLine);
  const tokenReady = Boolean(accessToken);
  const [conversationId, setConversationId] = useState<number | undefined>();
  const [dock, setDock] = useState<DockPosition>({ right: 24, bottom: 24 });

  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const msgIdRef = useRef(0);
  const dragRef = useRef<DragSession | null>(null);
  const suppressClickRef = useRef(false);

  const apiBase = guestApiBase || "";

  /* ── Online/Offline ─────────────────────────────────────── */
  useEffect(() => {
    const go = () => { setOffline(false); setError(null); };
    const gone = () => setOffline(true);
    window.addEventListener("online", go);
    window.addEventListener("offline", gone);
    return () => { window.removeEventListener("online", go); window.removeEventListener("offline", gone); };
  }, []);

  /* ── Auto-scroll ────────────────────────────────────────── */
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    const keepInViewport = () => setDock((current) => clampDock(current, view));
    keepInViewport();
    window.addEventListener("resize", keepInViewport);
    return () => window.removeEventListener("resize", keepInViewport);
  }, [view]);

  /* ── Handlers ───────────────────────────────────────────── */
  const openChat = useCallback(() => {
    setView("chat");
    setTimeout(() => inputRef.current?.focus(), 300);
  }, []);

  const closeChat = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
    setView("bubble");
  }, []);

  const beginDrag = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (!draggable || (e.pointerType === "mouse" && e.button !== 0)) return;
    if (view === "chat" && window.innerWidth <= 480) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startRight: dock.right,
      startBottom: dock.bottom,
      moved: false,
    };
  }, [dock, draggable, view]);

  // Keep a mouse fallback for embedded hosts/browsers that do not deliver
  // pointermove events consistently from inside a Shadow DOM.
  const beginMouseDrag = useCallback((e: React.MouseEvent<HTMLElement>) => {
    if (dragRef.current || !draggable || e.button !== 0) return;
    if (view === "chat" && window.innerWidth <= 480) return;
    e.preventDefault();
    dragRef.current = {
      pointerId: -1,
      startX: e.clientX,
      startY: e.clientY,
      startRight: dock.right,
      startBottom: dock.bottom,
      moved: false,
    };
  }, [dock, draggable, view]);

  const updateDockFromPoint = useCallback((clientX: number, clientY: number) => {
    const session = dragRef.current;
    if (!session) return;
    const dx = clientX - session.startX;
    const dy = clientY - session.startY;
    if (Math.abs(dx) + Math.abs(dy) >= 4) session.moved = true;
    if (!session.moved) return;
    setDock(clampDock({
      right: session.startRight - dx,
      bottom: session.startBottom - dy,
    }, view));
  }, [view]);

  const moveDrag = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const session = dragRef.current;
    if (!session || session.pointerId !== e.pointerId) return;
    updateDockFromPoint(e.clientX, e.clientY);
  }, [updateDockFromPoint]);

  const endDrag = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const session = dragRef.current;
    if (!session || session.pointerId !== e.pointerId) return;
    suppressClickRef.current = session.moved;
    dragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  }, []);

  useEffect(() => {
    const onPointerMove = (e: PointerEvent) => {
      if (!dragRef.current || dragRef.current.pointerId < 0) return;
      updateDockFromPoint(e.clientX, e.clientY);
    };
    const onPointerUp = () => {
      const session = dragRef.current;
      if (!session || session.pointerId < 0) return;
      suppressClickRef.current = session.moved;
      dragRef.current = null;
    };
    const onMouseMove = (e: MouseEvent) => {
      if (!dragRef.current || dragRef.current.pointerId !== -1) return;
      updateDockFromPoint(e.clientX, e.clientY);
    };
    const onMouseUp = () => {
      const session = dragRef.current;
      if (!session || session.pointerId !== -1) return;
      suppressClickRef.current = session.moved;
      dragRef.current = null;
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [updateDockFromPoint]);

  const addMessage = useCallback((msg: Omit<Message, "id" | "timestamp">) => {
    const id = `msg-${++msgIdRef.current}`;
    setMessages((prev) => [...prev, { ...msg, id, timestamp: Date.now() }]);
    return id;
  }, []);

  const updateLastAssistant = useCallback((content: string, sources?: Source[], isStreaming?: boolean) => {
    setMessages((prev) => {
      const idx = prev.length - 1;
      if (idx < 0 || prev[idx].role !== "assistant") return prev;
      const updated = [...prev];
      updated[idx] = { ...updated[idx], content, sources, isStreaming };
      return updated;
    });
  }, []);

  /* ── Send / Stream ──────────────────────────────────────── */
  const sendMessage = useCallback(async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || streaming || offline) return;
    setInput("");
    setPhase("chatting");
    setError(null);
    addMessage({ role: "user", content: q });
    addMessage({ role: "assistant", content: "", isStreaming: true });
    setStreaming(true);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      if (!accessToken) throw new Error("请先使用学生或管理员账号登录");
      const res = await fetch(`${apiBase}/api/widget/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ question: q, conversation_id: conversationId }),
        signal: ctrl.signal,
      });

      if (!res.ok) {
        if (res.status === 401 || res.status === 403) throw new Error("仅学生和管理员可使用，请登录正式账号");
        if (res.status === 429) throw new Error("请求过于频繁，请稍后再试");
        throw new Error(`服务异常 (${res.status})`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("无法读取响应");
      const decoder = new TextDecoder();
      let buffer = "";
      let fullText = "";
      let sources: Source[] | undefined;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const evt = part.match(/^event: (\w+)/m)?.[1];
          const dataRaw = part.match(/^data: (.+)$/m)?.[1];
          if (evt === "meta" && dataRaw) {
            try {
              const meta = JSON.parse(dataRaw);
              sources = showSources ? meta.sources : undefined;
              if (meta.conversation_id) setConversationId(meta.conversation_id);
            } catch {}
          }
          if (evt === "token" && dataRaw) {
            try { fullText += JSON.parse(dataRaw).text ?? ""; } catch {}
            updateLastAssistant(showSources ? fullText : withoutCitations(fullText), sources, true);
          }
          if (evt === "done") {
            updateLastAssistant(showSources ? fullText : withoutCitations(fullText), sources, false);
          }
          if (evt === "error") {
            try {
              const e = JSON.parse(dataRaw ?? "{}");
              setError(e.message || "回答生成失败");
            } catch { setError("回答生成失败"); }
            updateLastAssistant(
              fullText ? (showSources ? fullText : withoutCitations(fullText)) : "抱歉，回答生成失败，请重试。",
              sources,
              false,
            );
          }
        }
      }
      if (!fullText && !sources) {
        updateLastAssistant("", sources, false);
      }
    } catch (e: any) {
      if (e.name === "AbortError") {
        updateLastAssistant("", undefined, false);
      } else {
        setError(e.message || "网络请求失败");
        updateLastAssistant("", undefined, false);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, offline, apiBase, accessToken, addMessage, updateLastAssistant, conversationId, showSources]);

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }, [sendMessage]);

  const retry = useCallback(() => {
    setError(null);
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) sendMessage(lastUser.content);
  }, [messages, sendMessage]);

  /* ── Derived ─────────────────────────────────────────────── */
  const hasMessages = messages.length > 0;
  const showWelcome = phase === "welcome" || (!hasMessages && !streaming);

  /* ── Render: Bubble ──────────────────────────────────────── */
  if (view === "bubble") {
    return (
      <div
        className={`wg-bubble ${draggable ? "wg-draggable" : ""}`}
        style={{ right: dock.right, bottom: dock.bottom }}
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onMouseDown={beginMouseDrag}
        onClick={() => {
          if (suppressClickRef.current) { suppressClickRef.current = false; return; }
          openChat();
        }}
        title={draggable ? "校园问答（可拖动）" : "校园问答"}
      >
        <IconChat />
        <button
          className="wg-bubble__keyboard"
          onClick={(e) => { e.stopPropagation(); openChat(); }}
          aria-label="打开校园问答助手"
        >
          打开校园问答助手
        </button>
      </div>
    );
  }

  /* ── Render: Chat Window ─────────────────────────────────── */
  return (
    <div className="wg-window" style={{ right: dock.right, bottom: dock.bottom }} role="dialog" aria-label={title}>
      {/* Header */}
      <div
        className={`wg-header ${draggable ? "wg-draggable" : ""}`}
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onMouseDown={beginMouseDrag}
      >
        <div className="wg-header__logo"><IconSchool /></div>
        <div>
          <div className="wg-header__title">{title}</div>
          <div className="wg-header__subtitle">河海大学校园知识问答</div>
        </div>
        <button className="wg-header__btn" onPointerDown={(e) => e.stopPropagation()} onClick={closeChat} aria-label="关闭窗口" title="关闭">
          <IconClose />
        </button>
      </div>

      {/* Offline banner */}
      {offline && (
        <div className="wg-banner wg-banner--offline">
          <IconAlert />
          <span className="wg-banner__text">网络连接已断开</span>
        </div>
      )}

      {/* Error banner */}
      {error && !offline && (
        <div className="wg-banner wg-banner--error">
          <IconAlert />
          <span className="wg-banner__text">{error}</span>
          <button className="wg-banner__btn" onClick={retry}><IconRefresh /> 重试</button>
        </div>
      )}

      {/* Body */}
      <div className="wg-body" ref={bodyRef}>
        {showWelcome && (
          <div className="wg-welcome">
            <div className="wg-welcome__icon"><IconChat /></div>
            <div className="wg-welcome__title">你好，有什么可以帮你？</div>
            <div className="wg-welcome__desc">我是河海大学校园知识问答助手，可以回答关于校园生活、学习等方面的问题。</div>
            {!tokenReady && <div className="wg-auth-notice">请先使用学生或管理员账号登录后使用</div>}
            <div className="wg-quick-questions">
              {quickQuestions.map((q) => (
                <button key={q} className="wg-quick-btn" onClick={() => sendMessage(q)} disabled={!tokenReady || offline}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages */}
        {messages.map((msg) => {
          if (msg.role === "system") {
            return (
              <div key={msg.id} className="wg-msg wg-msg--system">
                <div className="wg-msg__bubble">{msg.content}</div>
              </div>
            );
          }
          return (
            <div key={msg.id} className={`wg-msg wg-msg--${msg.role}`}>
              <div className="wg-msg__bubble">
                {msg.content || (msg.isStreaming ? (
                  <div className="wg-typing"><span /><span /><span /></div>
                ) : "暂无内容")}
              </div>
              {showSources && msg.sources && msg.sources.length > 0 && (
                <div className="wg-msg__sources">
                  {msg.sources.map((s) => (
                    <button
                      key={s.index}
                      className="wg-msg__source-chip"
                      onClick={() => setDrawerSource(s)}
                      title={s.title}
                    >
                      <span>[{s.index}] {s.title}</span>
                      <span>{Math.round(s.score * 100)}%</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="wg-msg__time">{formatTime(msg.timestamp)}</div>
            </div>
          );
        })}
      </div>

      {/* Login prompt */}
      {loginUrl && (
        <div className="wg-login-prompt">
          登录后可保存聊天记录 —— <a href={loginUrl} target="_blank" rel="noopener">前往登录</a>
        </div>
      )}

      {/* Input area */}
      <div className="wg-input-area">
        <textarea
          ref={inputRef}
          className="wg-input"
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入你的问题，Enter 发送..."
          disabled={!tokenReady || offline}
          aria-label="输入问题"
        />
        {streaming ? (
          <button className="wg-stop-btn" onClick={stopStream} aria-label="停止生成" title="停止生成">
            <span className="wg-stop-btn__inner" />
          </button>
        ) : (
          <button
            className="wg-send-btn"
            onClick={() => sendMessage()}
            disabled={!input.trim() || !tokenReady || offline}
            aria-label="发送"
            title="发送"
          >
            <IconSend />
          </button>
        )}
      </div>

      {/* Source Drawer */}
      {showSources && drawerSource && (
        <>
          <div className="wg-drawer-overlay" onClick={() => setDrawerSource(null)} />
          <div className="wg-drawer">
            <div className="wg-drawer__header">
              <span className="wg-drawer__title">来源详情</span>
              <button className="wg-drawer__close" onClick={() => setDrawerSource(null)} aria-label="关闭来源详情">✕</button>
            </div>
            <div className="wg-drawer__body">
              <div className="wg-drawer__source">
                <div>
                  <span className="wg-drawer__source-index">{drawerSource.index}</span>
                  <span className="wg-drawer__source-title">{drawerSource.title}</span>
                </div>
                <div className="wg-drawer__source-score">检索相关度: {Math.round(drawerSource.score * 100)}%</div>
                {drawerSource.content && (
                  <div className="wg-drawer__source-content">{drawerSource.content}</div>
                )}
                {drawerSource.source_url && (
                  <div className="wg-drawer__source-url">
                    来源: <a href={drawerSource.source_url} target="_blank" rel="noopener noreferrer">{drawerSource.source_url}</a>
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
