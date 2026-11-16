"""End-to-end smoke test — full user journey."""

import pytest


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@campus.example", "password": "admin123"})
    return r.json()["data"]["token"]


def test_full_user_journey(client):
    """注册 → 登录 → 上传文档 → 同步问答 → 查看历史 → 删除会话"""
    # 1. Register
    import uuid
    email = f"e2e{uuid.uuid4().hex[:6]}@test.com"
    r = client.post("/api/auth/register", json={"name": "E2E用户", "email": email, "password": "123456"})
    assert r.status_code == 201
    token = r.json()["data"]["token"]

    # 2. Login
    r = client.post("/api/auth/login", json={"email": email, "password": "123456"})
    assert r.status_code == 200

    # 3. Sync chat (non-streaming)
    r = client.post("/api/chat/sync", headers={"Authorization": f"Bearer {token}"},
                    json={"question": "河海大学的校训是什么？"})
    assert r.status_code == 200
    answer = r.json()["data"]["answer"]
    assert len(answer) > 5

    # 4. Check conversations
    r = client.get("/api/conversations", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    convs = r.json()["data"]
    assert len(convs) > 0

    # 5. Delete conversation
    conv_id = convs[0]["id"]
    r = client.delete(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204


def test_admin_workflow(client, admin):
    """Admin: upload doc → check status → delete"""
    # Upload
    r = client.post("/api/documents", headers={"Authorization": f"Bearer {admin}"},
                    data={"title": "测试规则"},
                    files={"file": ("rules.txt", b"Dormitory curfew is at 11pm. Late returns must be reported.", "text/plain")})
    assert r.status_code == 201
    doc_id = r.json()["data"]["id"]

    # Check list
    r = client.get("/api/documents", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200
    docs = [d for d in r.json()["data"] if d["id"] == doc_id]
    assert len(docs) == 1

    # Delete
    r = client.delete(f"/api/documents/{doc_id}", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 204


def test_guest_flow(client):
    """Guest login → ask question → get answer"""
    r = client.post("/api/auth/guest")
    assert r.status_code == 200
    token = r.json()["data"]["token"]

    r = client.post("/api/chat/sync", headers={"Authorization": f"Bearer {token}"},
                    json={"question": "图书馆开放时间？"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert "answer" in data
