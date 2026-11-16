"""Day 4 acceptance tests for the document lifecycle APIs."""


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def upload(client, token: str, filename: str, content: bytes, title: str = "Day4 测试文档"):
    return client.post(
        "/api/doc/upload",
        headers=auth_headers(token),
        data={"title": title, "category": "校园服务"},
        files={"file": (filename, content, "text/plain")},
    )


def test_day4_upload_list_preview_download_and_update(client, admin_token):
    response = upload(client, admin_token, "guide.txt", "河海大学图书馆开放时间。".encode())
    assert response.status_code == 201
    document_id = response.json()["data"]["id"]

    listing = client.get("/api/doc/list?status=READY&page=1&page_size=10", headers=auth_headers(admin_token))
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] >= 1
    assert any(item["id"] == document_id for item in listing.json()["data"]["items"])

    detail = client.get(f"/api/doc/{document_id}", headers=auth_headers(admin_token))
    assert detail.status_code == 200
    assert detail.json()["data"]["chunks"]
    assert "图书馆" in detail.json()["data"]["preview"]

    downloaded = client.get(f"/api/doc/{document_id}/download", headers=auth_headers(admin_token))
    assert downloaded.status_code == 200
    assert "图书馆" in downloaded.content.decode("utf-8")

    updated = client.put(
        f"/api/doc/{document_id}",
        headers=auth_headers(admin_token),
        data={"title": "更新后的图书馆指南", "category": "规章制度"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "更新后的图书馆指南"


def test_day4_reprocess_is_idempotent_and_delete_cleans_record(client, admin_token):
    response = upload(client, admin_token, "repeat.txt", "校训是艰苦朴素、实事求是、严格要求、勇于探索。".encode())
    document_id = response.json()["data"]["id"]
    before = client.get(f"/api/doc/{document_id}", headers=auth_headers(admin_token)).json()["data"]["chunk_count"]

    retry = client.post(f"/api/doc/{document_id}/reprocess", headers=auth_headers(admin_token))
    assert retry.status_code == 200
    after = client.get(f"/api/doc/{document_id}", headers=auth_headers(admin_token)).json()["data"]["chunk_count"]
    assert after == before

    deleted = client.delete(f"/api/doc/{document_id}", headers=auth_headers(admin_token))
    assert deleted.status_code == 204
    assert client.get(f"/api/doc/{document_id}", headers=auth_headers(admin_token)).status_code == 404


def test_day4_rejects_invalid_file_signature_and_allows_student_submission(client, admin_token):
    invalid = client.post(
        "/api/doc/upload",
        headers=auth_headers(admin_token),
        data={"title": "假 PDF"},
        files={"file": ("not-a-pdf.pdf", b"plain text", "application/pdf")},
    )
    assert invalid.status_code == 400

    import uuid
    registered = client.post(
        "/api/auth/register",
        json={"name": "文档学生", "email": f"doc{uuid.uuid4().hex[:8]}@test.com", "password": "123456"},
    )
    student_token = registered.json()["data"]["token"]
    assert client.get("/api/doc/list", headers=auth_headers(student_token)).status_code == 200


def test_legacy_kb_document_supports_preview_download_reprocess_and_inline_edit(client, admin_token):
    from app.config import settings
    from app.database import connect, utc_now

    settings.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
    source = settings.knowledge_base_dir / "legacy-campus-guide.md"
    original_text = "历史知识库原文：江宁校区图书馆正常开放。"
    source.write_text(original_text, encoding="utf-8")

    with connect() as db:
        admin_id = db.execute(
            "SELECT id FROM users WHERE email='admin@campus.example'"
        ).fetchone()["id"]
        now = utc_now()
        cursor = db.execute(
            """
            INSERT INTO documents(
                title,filename,stored_name,mime_type,size,status,chunk_count,
                category,original_path,uploaded_by,created_at,updated_at,
                processing_step,review_status,uploader_key
            ) VALUES(?,?,?,?,?,'READY',3,?,?,?,?,?,'COMPLETED','APPROVED',?)
            """,
            (
                "历史校园指南", source.name, f"kb:{source.name}", "text/markdown",
                len(original_text.encode()), "校园服务", str(source), admin_id,
                now, now, f"user:{admin_id}",
            ),
        )
        document_id = int(cursor.lastrowid)
        db.commit()

    detail = client.get(f"/api/doc/{document_id}", headers=auth_headers(admin_token))
    assert detail.status_code == 200
    assert "历史知识库原文" in detail.json()["data"]["preview"]

    downloaded = client.get(f"/api/doc/{document_id}/download", headers=auth_headers(admin_token))
    assert downloaded.status_code == 200
    assert downloaded.content.decode("utf-8") == original_text

    retried = client.post(f"/api/doc/{document_id}/reprocess", headers=auth_headers(admin_token))
    assert retried.status_code == 200

    edited_text = "管理员修订正文：江宁校区图书馆开放至晚上十点。"
    edited = client.put(
        f"/api/doc/{document_id}",
        headers=auth_headers(admin_token),
        data={"title": "历史校园指南", "category": "校园服务", "text_content": edited_text},
    )
    assert edited.status_code == 200

    edited_detail = client.get(f"/api/doc/{document_id}", headers=auth_headers(admin_token)).json()["data"]
    assert edited_text in edited_detail["preview"]
    assert edited_detail["content_override"] == edited_text

    original_download = client.get(f"/api/doc/{document_id}/download", headers=auth_headers(admin_token))
    assert original_download.content.decode("utf-8") == original_text
