"""Student and guest chat must share the configured RAG retrieval engine."""

import json


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_student_and_guest_both_use_hybrid_rag_engine(client, monkeypatch):
    from app.rag.engine import rag_engine

    calls: list[tuple[str, int | None]] = []

    def fake_stream(question: str, conversation_id: int | None = None, strategy: str = "hybrid", top_k=None):
        calls.append((strategy, conversation_id))
        meta = {
            "sources": [{
                "index": 1,
                "title": "向量库命中文档",
                "content": "来自 FAISS 与 BM25 混合检索的证据",
                "score": 0.88,
            }],
            "generation_mode": "llm",
        }
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
        yield 'event: token\ndata: {"text":"检索回答"}\n\n'
        yield "event: done\ndata: {}\n\n"

    monkeypatch.setattr(rag_engine, "stream_query", fake_stream)

    guest = client.post("/api/auth/guest").json()["data"]
    guest_response = client.post(
        "/api/chat/stream",
        headers=_headers(guest["token"]),
        json={"question": "访客问题", "strategy": "hybrid"},
    )

    student = client.post(
        "/api/auth/register",
        json={"name": "检索测试学生", "email": "rag-student@example.com", "password": "student123"},
    ).json()["data"]
    student_response = client.post(
        "/api/chat/stream",
        headers=_headers(student["token"]),
        json={"question": "学生问题", "strategy": "hybrid"},
    )

    assert guest_response.status_code == 200
    assert student_response.status_code == 200
    assert calls[0] == ("hybrid", None)
    assert calls[1][0] == "hybrid"
    assert calls[1][1] is not None
