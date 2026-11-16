# API 概览

统一响应格式：

```json
{ "code": 200, "message": "success", "data": {}, "timestamp": "2026-11-16T00:00:00+00:00" }
```

除公开接口外，请求头需携带：

```http
Authorization: Bearer <token>
```

## 认证

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/auth/captcha` | 公开 | 返回 `captcha_token` 与算术题 `question` |
| POST | `/api/auth/register` | 公开 | 注册学生账号 |
| POST | `/api/auth/login` | 公开 | 登录，需 `captcha_token` + `captcha_answer` |
| POST | `/api/auth/guest` | 公开 | 访客令牌（不创建账号） |

## 问答与会话

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/chat/stream` | 登录 | SSE 流式问答，事件：`meta` / `token` / `done` |
| POST | `/api/chat/sync` | 登录 | 同步问答，返回完整回答 |
| POST | `/api/chat/feedback` | 登录 | 点赞 / 点踩 |
| GET | `/api/conversations` | 登录 | 当前用户会话列表 |
| GET | `/api/conversations/{id}` | 登录 | 会话消息与来源 |
| DELETE | `/api/conversations/{id}` | 登录 | 删除会话 |
| GET | `/api/quick-questions` | 公开 | 快捷问题列表 |

## 知识库

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/doc/list` | 管理员 | 分页、搜索、按状态筛选 |
| POST | `/api/doc/upload` | 管理员 | 上传 TXT / MD / PDF / DOCX（≤ 50 MB） |
| GET | `/api/doc/{id}` | 管理员 | 文档详情与预览 |
| PUT | `/api/doc/{id}` | 管理员 | 修改标题 / 替换文件 |
| POST | `/api/doc/{id}/reprocess` | 管理员 | 重新解析与索引 |
| POST | `/api/doc/{id}/review` | 管理员 | 审核通过 / 驳回 |
| POST | `/api/doc/batch/action` | 管理员 | 批量审核 / 重处理 / 删除 |
| GET | `/api/doc/{id}/download` | 管理员 | 下载原文件 |
| DELETE | `/api/doc/{id}` | 管理员 | 删除文档 |
| GET | `/api/kb/versions` | 管理员 | 知识库版本记录 |
| POST | `/api/kb/rebuild` | 管理员 | 重建知识库索引 |

## 用户、统计与系统

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/users` | 管理员 | 用户列表 |
| PATCH | `/api/users/{id}` | 管理员 | 修改角色 / 状态 |
| PATCH | `/api/users/me` | 登录 | 修改个人资料 |
| GET | `/api/stats/dashboard` | 管理员 | 文档数、今日问答、活跃用户、向量块数 |
| GET | `/api/stats/trends?days=7` | 管理员 | 问答趋势 |
| GET | `/api/system/logs` | 管理员 | 操作日志分页 |
| GET | `/api/system/config` | 管理员 | 读取系统配置 |
| PUT | `/api/system/config` | 管理员 | 保存系统配置 |
| GET | `/api/health` | 公开 | 健康检查 |

## SSE 事件格式

```text
event: meta
data: {"conversation_id": 1, "sources": [...], "generation_mode": "llm"}

event: token
data: {"text": "河海大学的校训是"}

event: done
data: {}
```
