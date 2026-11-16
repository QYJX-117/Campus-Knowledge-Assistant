"""Auth integration tests."""


class TestAuth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_register(self, client):
        import uuid
        email = f"test{uuid.uuid4().hex[:8]}@test.com"
        r = client.post("/api/auth/register", json={"name": "测试", "email": email, "password": "123456"})
        assert r.status_code == 201
        data = r.json()["data"]
        assert "token" in data
        assert data["user"]["role"] == "STUDENT"

    def test_register_duplicate(self, client):
        client.post("/api/auth/register", json={"name": "A", "email": "dup@test.com", "password": "123456"})
        r = client.post("/api/auth/register", json={"name": "B", "email": "dup@test.com", "password": "654321"})
        assert r.status_code in [409, 422]  # 409 from our code, 422 from pydantic

    def test_login_admin(self, client):
        r = client.post("/api/auth/login", json={"email": "admin@campus.example", "password": "admin123"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["user"]["role"] == "ADMIN"

    def test_login_wrong_password(self, client):
        r = client.post("/api/auth/login", json={"email": "admin@campus.example", "password": "wrong"})
        assert r.status_code == 401

    def test_guest_login(self, client):
        r = client.post("/api/auth/guest")
        assert r.status_code == 200
        data = r.json()["data"]
        assert "token" in data
        assert data["user"]["role"] == "STUDENT"
        assert "guest-" in data["user"]["email"]
