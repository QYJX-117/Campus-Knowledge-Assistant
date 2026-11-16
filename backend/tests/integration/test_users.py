"""User management integration tests."""


class TestUsers:
    def test_user_can_update_own_profile_and_password(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        updated = client.patch(
            "/api/users/me",
            headers=headers,
            json={
                "name": "资料管理员", "email": "admin@campus.example",
                "current_password": "admin123", "new_password": "admin456",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "资料管理员"

        login = client.post(
            "/api/auth/login",
            json={"email": "admin@campus.example", "password": "admin456"},
        )
        assert login.status_code == 200
        restored = client.patch(
            "/api/users/me",
            headers={"Authorization": f"Bearer {login.json()['data']['token']}"},
            json={
                "name": "系统管理员", "email": "admin@campus.example",
                "current_password": "admin456", "new_password": "admin123",
            },
        )
        assert restored.status_code == 200

    def test_profile_update_rejects_wrong_current_password(self, client, admin_token):
        response = client.patch(
            "/api/users/me",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "系统管理员", "email": "admin@campus.example",
                "current_password": "wrong-password",
            },
        )
        assert response.status_code == 400

    def test_paginated_search_and_role_filter(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = client.get("/api/users", headers=headers, params={"page": 1, "size": 10, "keyword": "admin"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["page"] == 1
        assert data["size"] == 10
        assert data["total"] >= 1
        assert any("admin" in user["email"] for user in data["records"])

        admins = client.get("/api/users", headers=headers, params={"page": 1, "size": 10, "role": "ADMIN"}).json()["data"]
        assert all(user["role"] == "ADMIN" for user in admins["records"])

    def test_admin_can_create_and_edit_user(self, client, admin_token):
        import uuid
        headers = {"Authorization": f"Bearer {admin_token}"}
        suffix = uuid.uuid4().hex[:10]
        created = client.post("/api/users", headers=headers, json={
            "name": "课程用户", "email": f"course-user-{suffix}@example.com", "password": "123456", "role": "STUDENT",
        })
        assert created.status_code == 201
        user = created.json()["data"]
        assert user["role"] == "STUDENT"

        updated = client.patch(f"/api/users/{user['id']}", headers=headers, json={
            "name": "课程管理员", "email": f"course-admin-{suffix}@example.com", "role": "ADMIN",
        })
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "课程管理员"
        assert updated.json()["data"]["role"] == "ADMIN"

    def test_admin_cannot_disable_or_demote_self(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        users = client.get("/api/users", headers=headers).json()["data"]
        me = next(user for user in users if user["email"] == "admin@campus.example")
        assert client.patch(f"/api/users/{me['id']}", headers=headers, json={"is_active": False}).status_code == 400
        assert client.patch(f"/api/users/{me['id']}", headers=headers, json={"role": "STUDENT"}).status_code == 400
