# 系统架构

## 总体结构

```text
React 18 + TypeScript + Vite + Ant Design 5
                    │
                    │ REST / JSON + POST SSE
                    ▼
              FastAPI 2.0（Python 3.11+）
        ┌───────────┼────────────┬─────────────┐
        ▼           ▼            ▼             ▼
    Auth / JWT  文档服务      会话与反馈    统计与日志
        │           │            │             │
        │           ▼            ▼             │
        │      LlamaIndex       SQLite ────────┘
        │      FAISS + BGE
        │      BM25 + jieba
        │           │
        └──────► RAG Engine ──► DeepSeek / OpenAI 兼容 LLM
```

## 模块说明

| 模块 | 主要文件 | 职责 |
|---|---|---|
| 应用入口 | `backend/app/main.py` | 启动时初始化数据库、种子管理员与示例文档、加载知识库索引 |
| 认证 | `api/auth.py`、`security.py` | 注册、登录、访客令牌、JWT 签发与校验、PBKDF2 密码哈希、算术验证码 |
| 问答 | `api/chat.py`、`services/chat_service.py` | SSE 流式问答、同步问答、会话读写、点赞 / 点踩反馈 |
| 文档 | `api/documents.py`、`services/document_service.py` | 上传、解析、切分、索引、审核、重处理、下载、批量操作 |
| RAG | `rag/engine.py`、`rag/hot_cache.py` | 混合检索、策略路由、查询改写、上下文压缩、热 FAQ、Self-RAG |
| 用户 | `api/users.py` | 用户列表、角色切换、启用 / 停用 |
| 统计 | `api/stats.py` | 仪表盘统计、7 天趋势、操作日志、系统配置、知识库重建 |
| 中间件 | `middleware/security.py` | 限流、安全响应头 |

## 数据存储

- **SQLite**：用户、文档元数据、会话、消息、操作日志。
- **文件**：上传原文件在 `backend/data/uploads/`；FAISS 索引、BM25 索引与 docstore 在 `backend/data/llama_index_storage/`；两者均为运行时生成，不提交到 Git。
- **知识库**：`knowledge-base/` 下的 Markdown 文档，启动时自动加载；`backend/app/cli.py` 可显式重建索引。

## 请求链路（流式问答）

```text
POST /api/chat/stream
  → JWT 校验
  → 安全护栏（敏感词 / PII）
  → 热 FAQ 缓存命中则直接返回
  → 查询改写（可选）
  → 检索策略（hybrid / dense / bm25 / hyde / multi / decompose / parent_child / full）
  → RRF 融合 + 上下文压缩（+ 可选重排）
  → 拼接 System Prompt 与来源
  → LLM 流式生成
  → SSE: meta（来源 / 会话 ID）→ token（增量文本）→ done
```

## 关键设计取舍

- 用 FastAPI 一体化实现替代课程示例里的 Spring Boot + 独立 Python AI 服务，减少演示时的进程数量。
- 未配置 `DASHSCOPE_API_KEY` 时走本地 BGE Embedding，避免云端向量化费用。
- 文档索引在启动时同步加载，避免后台任务与用户请求争抢索引锁。
- Windows 下 FAISS 对 Unicode 路径敏感，索引临时文件优先写入 ASCII 目录（`settings.data_dir/tmp`，测试环境回退到工作目录）。
