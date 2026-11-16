"""Document submission, ownership and administrator review workflow."""

import uuid


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client, name: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={"name": name, "email": f"{uuid.uuid4().hex[:10]}@test.com", "password": "123456"},
    )
    return response.json()["data"]["token"]


def submit(client, token: str, title: str) -> dict:
    response = client.post(
        "/api/doc/upload",
        headers=headers(token),
        data={"title": title, "category": "校园服务"},
        files={"file": (f"{title}.txt", "河海大学校园服务资料。".encode(), "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_student_submission_is_private_until_admin_approves(client, admin_token):
    owner = register(client, "上传者")
    other = register(client, "其他用户")
    document = submit(client, owner, "审核流程文档")

    assert document["review_status"] == "PENDING"
    assert document["processing_step"] == "AWAITING_REVIEW"
    assert client.get(f"/api/doc/{document['id']}", headers=headers(other)).status_code == 404

    admin_list = client.get("/api/doc/list?review_status=PENDING", headers=headers(admin_token)).json()["data"]
    assert any(item["id"] == document["id"] for item in admin_list["items"])

    approved = client.post(
        f"/api/doc/{document['id']}/review",
        headers=headers(admin_token),
        json={"action": "approve", "note": "来源清晰，内容有效"},
    )
    assert approved.status_code == 200
    detail = client.get(f"/api/doc/{document['id']}", headers=headers(owner)).json()["data"]
    assert detail["review_status"] == "APPROVED"
    assert detail["status"] == "READY"
    assert detail["chunk_count"] > 0
    duplicate = client.post(
        f"/api/doc/{document['id']}/review",
        headers=headers(admin_token),
        json={"action": "approve", "note": "重复审核"},
    )
    assert duplicate.status_code == 409


def test_admin_rejection_requires_reason_and_remains_visible_to_owner(client, admin_token):
    owner = register(client, "待修改用户")
    document = submit(client, owner, "待驳回文档")

    retry_before_review = client.post(f"/api/doc/{document['id']}/reprocess", headers=headers(admin_token))
    assert retry_before_review.status_code == 409

    missing_reason = client.post(
        f"/api/doc/{document['id']}/review",
        headers=headers(admin_token),
        json={"action": "reject", "note": ""},
    )
    assert missing_reason.status_code == 400

    rejected = client.post(
        f"/api/doc/{document['id']}/review",
        headers=headers(admin_token),
        json={"action": "reject", "note": "请补充发布部门和生效日期"},
    )
    assert rejected.status_code == 200
    detail = client.get(f"/api/doc/{document['id']}", headers=headers(owner)).json()["data"]
    assert detail["review_status"] == "REJECTED"
    assert "发布部门" in detail["review_note"]
    assert detail["chunk_count"] == 0


def test_guest_submission_is_scoped_to_its_guest_session(client):
    first = client.post("/api/auth/guest").json()["data"]["token"]
    second = client.post("/api/auth/guest").json()["data"]["token"]
    document = submit(client, first, "访客资料")

    first_items = client.get("/api/doc/list", headers=headers(first)).json()["data"]["items"]
    second_items = client.get("/api/doc/list", headers=headers(second)).json()["data"]["items"]
    assert any(item["id"] == document["id"] for item in first_items)
    assert all(item["id"] != document["id"] for item in second_items)
    assert client.get(f"/api/doc/{document['id']}", headers=headers(second)).status_code == 404
