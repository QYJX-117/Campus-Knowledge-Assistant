"""Chat + conversation routes."""

import json
import sqlite3
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from ..models.chat import ChatBody, FeedbackBody
from ..models.common import Result
from ..services.chat_service import ChatService
from ..database import get_db
from ..security import decode_token

router = APIRouter(prefix="/api", tags=["chat"])


def current_user(authorization: Annotated[str | None, Header()] = None, db: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row | dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "请先登录")
    payload = decode_token(authorization.removeprefix("Bearer ").strip())
    if not payload:
        raise HTTPException(401, "登录状态已失效")
    # Guest token — no real user in DB
    if payload.get("guest"):
        guest_id = str(payload.get("guest_id") or "")
        if len(guest_id) < 16:
            raise HTTPException(401, "访客登录状态已失效")
        return {"id": 0, "role": "STUDENT", "is_active": True, "guest": True, "guest_id": guest_id}
    user = db.execute("SELECT * FROM users WHERE id=?", (int(str(payload["sub"])),)).fetchone()
    if not user or not user["is_active"]:
        raise HTTPException(401, "账号不可用")
    return user


def is_guest_user(user: sqlite3.Row | dict) -> bool:
    return bool(user.get("guest")) if isinstance(user, dict) else False


def registered_user(user: Annotated[sqlite3.Row | dict, Depends(current_user)]) -> sqlite3.Row:
    """Require a persisted STUDENT/ADMIN account; guest tokens are not enough."""
    if is_guest_user(user):
        raise HTTPException(403, "悬浮问答仅限学生和管理员使用")
    if user["role"] not in {"STUDENT", "ADMIN"}:
        raise HTTPException(403, "当前账号无权使用悬浮问答")
    return user


def admin_user(user: Annotated[sqlite3.Row, Depends(current_user)]) -> sqlite3.Row:
    if user["role"] != "ADMIN":
        raise HTTPException(403, "需要管理员权限")
    return user


@router.post("/chat/stream")
async def chat_stream(body: ChatBody, db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)):
    if is_guest_user(user):
        from ..rag.engine import rag_engine
        return StreamingResponse(
            rag_engine.stream_query(body.question, None, body.strategy),
            media_type="text/event-stream",
        )
    if body.conversation_id and not ChatService.owns_conversation(db, body.conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在")
    return StreamingResponse(
        ChatService.stream_chat(db, body.question, user["id"], body.conversation_id, body.strategy),
        media_type="text/event-stream",
    )


@router.post("/widget/chat/stream")
async def widget_chat_stream(
    body: ChatBody,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(registered_user),
):
    """Authenticated floating-assistant stream with source metadata removed."""
    if body.conversation_id and not ChatService.owns_conversation(db, body.conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在")

    def source_free_stream():
        for event in ChatService.stream_chat(
            db, body.question, user["id"], body.conversation_id, body.strategy
        ):
            if "event: meta" in event:
                try:
                    payload = json.loads(event.split("data: ", 1)[1])
                    payload["sources"] = []
                    event = f"event: meta\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except (IndexError, json.JSONDecodeError):
                    pass
            yield event

    return StreamingResponse(
        source_free_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/sync")
def chat_sync(body: ChatBody, db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)):
    """同步问答——返回完整答案（非流式）。访客不保存记录。"""
    from ..rag.engine import rag_engine
    if is_guest_user(user):
        result = rag_engine.query(body.question, None, body.strategy)
        result["conversation_id"] = None
        return Result.ok(result)

    import json as _json
    from ..database import utc_now
    if body.conversation_id and not ChatService.owns_conversation(db, body.conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在")
    result = rag_engine.query(body.question, body.conversation_id, body.strategy)

    # Save to DB (same logic as stream endpoint)
    now = utc_now()
    conv_id = body.conversation_id
    if not conv_id:
        cur = db.execute("INSERT INTO conversations(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                         (user["id"], body.question[:28], now, now))
        conv_id = int(cur.lastrowid)
    db.execute("INSERT INTO messages(conversation_id,role,content,sources,created_at) VALUES(?,'USER',?,'[]',?)",
               (conv_id, body.question, now))
    db.execute("INSERT INTO messages(conversation_id,role,content,sources,created_at) VALUES(?,'ASSISTANT',?,?,?)",
               (conv_id, result["answer"], _json.dumps(result.get("sources", []), ensure_ascii=False), utc_now()))
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conv_id))
    db.commit()

    result["conversation_id"] = conv_id
    return Result.ok(result)


@router.get("/conversations")
def list_conversations(db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)):
    if is_guest_user(user):
        return Result.ok([])
    return Result.ok(ChatService.list_conversations(db, user["id"]))


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)):
    if is_guest_user(user):
        raise HTTPException(404, "会话不存在")
    data = ChatService.get_conversation(db, conversation_id, user["id"])
    if not data:
        raise HTTPException(404, "会话不存在")
    return Result.ok(data)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)):
    if is_guest_user(user):
        raise HTTPException(404, "会话不存在")
    if not ChatService.delete_conversation(db, conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在")


@router.post("/chat/feedback")
def chat_feedback(body: FeedbackBody, db: sqlite3.Connection = Depends(get_db), user: sqlite3.Row = Depends(current_user)):
    """User feedback — like records, dislike triggers Self-RAG corrective loop."""
    if is_guest_user(user):
        return Result.ok({"status": "recorded", "message": "感谢反馈！"})
    if not ChatService.owns_conversation(db, body.conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在")
    from ..database import utc_now
    from ..rag.engine import rag_engine

    # Log the feedback
    db.execute(
        "INSERT INTO api_logs(user_id,endpoint,method,status_code,duration_ms,created_at) VALUES(?,?,?,?,?,?)",
        (user["id"], "/api/chat/feedback", "POST", 200, 0, utc_now()),
    )

    # If helpful (like), record + add to hot FAQ cache (Design fusion)
    if body.helpful:
        # Find Q&A pair for hot cache
        um = db.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND role='USER' ORDER BY id DESC LIMIT 1",
            (body.conversation_id,),
        ).fetchone()
        am = db.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND role='ASSISTANT' ORDER BY id DESC LIMIT 1",
            (body.conversation_id,),
        ).fetchone()
        if um and am:
            try:
                from ..rag.hot_cache import add_to_hot_faq
                add_to_hot_faq(um["content"], am["content"])
            except Exception as e:
                print(f"[Feedback] Hot cache add failed: {e}")
        db.commit()
        return Result.ok({"status": "recorded", "message": "感谢反馈！已加入热库缓存。"})

    # If not helpful (dislike), trigger Self-RAG correction
    # Find the last AI message in this conversation
    msg_row = db.execute(
        "SELECT content, sources FROM messages WHERE conversation_id=? AND role='ASSISTANT' ORDER BY id DESC LIMIT 1",
        (body.conversation_id,),
    ).fetchone()

    if not msg_row:
        db.commit()
        return Result.ok({"status": "no_message", "message": "未找到可纠正的回答"})

    # Find the last user message for context
    user_msg = db.execute(
        "SELECT content FROM messages WHERE conversation_id=? AND role='USER' ORDER BY id DESC LIMIT 1",
        (body.conversation_id,),
    ).fetchone()

    question = user_msg["content"] if user_msg else ""
    original_answer = msg_row["content"]
    original_sources = json.loads(msg_row["sources"]) if msg_row["sources"] else []

    if not question:
        db.commit()
        return Result.ok({"status": "no_question", "message": "未找到原始问题"})

    # Run Self-RAG correction
    try:
        result = rag_engine.self_rag_correct(question, original_answer, original_sources)
    except Exception as e:
        db.commit()
        return Result.ok({"status": "self_rag_failed", "message": f"Self-RAG 执行失败: {e}"})

    # If corrected, save the new answer as a new ASSISTANT message
    if result.get("status") == "corrected" and result.get("new_answer"):
        new_answer = result["new_answer"]
        new_sources = result.get("new_sources", [])
        db.execute(
            "INSERT INTO messages(conversation_id,role,content,sources,created_at) VALUES(?,'ASSISTANT',?,?,?)",
            (body.conversation_id, new_answer,
             json.dumps(new_sources, ensure_ascii=False), utc_now()),
        )
        db.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?",
            (utc_now(), body.conversation_id),
        )

    db.commit()
    return Result.ok({
        "status": result.get("status"),
        "retries": result.get("retries", 0),
        "diagnosis": result.get("diagnosis", ""),
        "corrected_answer": result.get("new_answer") if result.get("status") == "corrected" else None,
        "corrected_sources": result.get("new_sources", []) if result.get("status") == "corrected" else [],
        "message": "Self-RAG 自检完成" if result.get("status") == "corrected" else "未能显著改进回答",
    })
