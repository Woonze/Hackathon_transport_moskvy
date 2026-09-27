from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import create_app
from backend.app.services.security import hash_password


class FakeDatabase:
    def __init__(self, _dsn):
        self.users = {}
        self.sessions = {}

    def open(self):
        pass

    def close(self):
        pass

    def ensure_user(self, username, password_hash):
        self.users[username] = password_hash

    def get_user(self, username):
        encoded = self.users.get(username)
        return {"username": username, "password_hash": encoded} if encoded else None

    def create_session(self, username, token_hash, _created, _expires):
        self.sessions[token_hash] = username

    def session_user(self, token_hash):
        return self.sessions.get(token_hash)

    def delete_session(self, token_hash):
        self.sessions.pop(token_hash, None)

    def ingest_revision(self):
        return 0

    def read_ingested(self):
        from backend.app.services.overlay import empty
        return empty()


def test_login_only_and_protected_api(monkeypatch):
    from backend.app import main

    password_hash = hash_password("correct horse battery")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(config, "AUTH_USERNAME", "fotur")
    monkeypatch.setattr(config, "AUTH_PASSWORD_HASH", password_hash)
    monkeypatch.setattr(main, "Database", FakeDatabase)

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/routes").status_code == 401
        assert client.post("/api/auth/register", json={"username": "other", "password": "x"}).status_code in (404, 405)
        assert client.post("/api/auth/login", json={"username": "fotur", "password": "wrong"}).status_code == 401

        response = client.post("/api/auth/login", json={"username": "fotur", "password": "correct horse battery"})
        assert response.status_code == 200
        assert response.json()["username"] == "fotur"
        assert "httponly" in response.headers["set-cookie"].lower()
        assert client.get("/api/routes").status_code == 200

        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/routes").status_code == 401
