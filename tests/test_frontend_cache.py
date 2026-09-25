from fastapi.testclient import TestClient

from backend.app import config
from backend.app.main import create_app


def test_frontend_entry_never_reuses_stale_build(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>new build</html>", encoding="utf-8")
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path)
    with TestClient(create_app()) as client:
        first = client.get("/")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"

        second = client.get("/", headers={"If-None-Match": '"stale-index"', "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"})
        assert second.status_code == 200
        assert second.text == "<html>new build</html>"
