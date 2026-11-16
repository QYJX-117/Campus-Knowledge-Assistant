"""Document management integration tests."""


class TestDocuments:
    def test_list_documents(self, client, admin_token):
        r = client.get("/api/documents", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def test_upload_txt(self, client, admin_token):
        r = client.post("/api/documents", headers={"Authorization": f"Bearer {admin_token}"},
                        data={"title": "测试文档"},
                        files={"file": ("test.txt", b"This is a test document.", "text/plain")})
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["status"] == "PROCESSING"
        # TestClient waits for Starlette background tasks before returning,
        # while the response correctly preserves the initial processing state.
        listed = client.get("/api/documents", headers={"Authorization": f"Bearer {admin_token}"}).json()["data"]
        finished = next(item for item in listed if item["id"] == data["id"])
        assert finished["status"] == "READY"
        assert finished["chunk_count"] > 0

    def test_upload_invalid_type(self, client, admin_token):
        r = client.post("/api/documents", headers={"Authorization": f"Bearer {admin_token}"},
                        data={"title": "bad"},
                        files={"file": ("bad.exe", b"x" * 100, "application/octet-stream")})
        assert r.status_code == 400

    def test_delete_document(self, client, admin_token):
        # Upload first
        r = client.post("/api/documents", headers={"Authorization": f"Bearer {admin_token}"},
                        data={"title": "to-delete"},
                        files={"file": ("tmp.txt", b"temp doc", "text/plain")})
        doc_id = r.json()["data"]["id"]
        # Delete
        r2 = client.delete(f"/api/documents/{doc_id}", headers={"Authorization": f"Bearer {admin_token}"})
        assert r2.status_code == 204

    def test_student_upload_is_submitted_for_review(self, client):
        import uuid
        r = client.post("/api/auth/register", json={"name": "学生", "email": f"stu{uuid.uuid4().hex[:8]}@test.com", "password": "123456"})
        token = r.json()["data"]["token"]
        r2 = client.post("/api/documents", headers={"Authorization": f"Bearer {token}"},
                         data={"title": "x"}, files={"file": ("x.txt", b"x", "text/plain")})
        assert r2.status_code == 400  # Title validation still applies.
        r3 = client.post("/api/documents", headers={"Authorization": f"Bearer {token}"},
                         data={"title": "学生提交"}, files={"file": ("x.txt", b"campus guide", "text/plain")})
        assert r3.status_code == 201
        assert r3.json()["data"]["review_status"] == "PENDING"
        listing = client.get("/api/documents", headers={"Authorization": f"Bearer {token}"})
        assert any(item["id"] == r3.json()["data"]["id"] for item in listing.json()["data"])
