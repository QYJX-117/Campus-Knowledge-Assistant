"""Floating assistant permission and source-hiding acceptance tests."""

import json


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_widget_rejects_guest(client):
    guest = client.post("/api/auth/guest").json()["data"]
    response = client.post(
        "/api/widget/chat/stream",
        headers=_headers(guest["token"]),
        json={"question": "河海大学的校训是什么？"},
    )
    assert response.status_code == 403
    assert "学生和管理员" in response.json()["detail"]


def test_widget_allows_registered_user_and_hides_sources(client, monkeypatch):
    registered = client.post(
        "/api/auth/register",
        json={"name": "气泡学生", "email": "bubble-student@test.com", "password": "123456"},
    ).json()["data"]

    def fake_stream(_db, _question, _user_id, _conversation_id=None, _strategy="hybrid"):
        meta = {"conversation_id": 99, "sources": [{"title": "内部资料"}]}
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
        yield 'event: token\ndata: {"text":"测试回答 [1]"}\n\n'
        yield "event: done\ndata: {}\n\n"

    from app.api import chat as chat_api
    monkeypatch.setattr(chat_api.ChatService, "stream_chat", fake_stream)
    response = client.post(
        "/api/widget/chat/stream",
        headers=_headers(registered["token"]),
        json={"question": "河海大学的校训是什么？"},
    )
    assert response.status_code == 200
    assert '"sources": []' in response.text
    assert "内部资料" not in response.text
    assert "测试回答" in response.text
