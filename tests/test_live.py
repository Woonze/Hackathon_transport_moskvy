import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "LIVE_POLL_SECONDS", 0.05)
    with TestClient(app) as c:
        yield c


def events(response):
    """Разбирает поток SSE в список (имя, данные)."""
    out, name = [], None
    for line in response.iter_lines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and name:
            out.append((name, json.loads(line.split(":", 1)[1])))
            name = None
    return out


def rec(ts):
    return {"tran_date_time": ts, "validation_result": 1, "ngpt_route": "7 трамвай"}


def test_stream_sends_snapshot_on_connect(client):
    with client.stream("GET", "/api/v1/stream?wait=0.3") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        ev = events(r)
    assert len(ev) == 1 and ev[0][0] == "update"
    assert set(ev[0][1]) == {"version", "history_end", "ingested_boardings", "updated_at", "worker_pid", "ml_model"}
    assert ev[0][1]["ml_model"]["name"] == "HistGradientBoostingRegressor"
    assert ev[0][1]["ml_model"]["training_rows"] > 0


def test_stream_pushes_update_after_ingest(client):
    def send():
        time.sleep(0.4)
        client.post("/api/v1/ingest/validations", json={"records": [rec("2025-11-05 09:10:00"), rec("2025-11-05 09:20:00")], "complete": True})

    t = threading.Thread(target=send)
    t.start()
    with client.stream("GET", "/api/v1/stream?wait=2") as r:
        ev = events(r)
    t.join()
    assert len(ev) == 2, ev
    first, second = ev[0][1], ev[1][1]
    assert first["version"] != second["version"]
    assert first["history_end"] == "2025-10-31" and second["history_end"] == "2025-11-05"
    assert second["ingested_boardings"] == 2
    assert second["ml_model"]["updates"] == first["ml_model"]["updates"] + 1


def test_stream_sees_data_written_by_another_worker(client):
    """Второй воркер = запись в общий файл мимо этого процесса: поток обязан заметить."""
    from backend.app.services import ingest
    from backend.app.store import DataStore

    other = DataStore()  # «чужой воркер»: свой экземпляр хранилища на том же файле
    threading.Timer(0.4, lambda: ingest.process([rec("2025-11-06 10:00:00")], None, other)).start()
    with client.stream("GET", "/api/v1/stream?wait=2") as r:
        ev = events(r)
    assert ev[-1][1]["history_end"] == "2025-11-06" and len(ev) == 2


def test_stream_rejects_bad_wait(client):
    r = client.get("/api/v1/stream?wait=-1")
    assert r.status_code == 422 and r.json()["code"]


def test_health_reports_data_freshness(client):
    h = client.get("/api/v1/health").json()
    assert "data_updated_at" in h and h["ingested_boardings"] == 0
    assert h["ml_model"]["name"] == "HistGradientBoostingRegressor"
    assert h["ml_model"]["training_rows"] > 0


def test_version_supports_postgres_revision_and_file_stamp():
    """С PostgreSQL отпечаток данных — целое число ревизии, без БД — кортеж (mtime, размер); поток не должен падать ни на одном."""
    from backend.app.services.live import _version

    assert _version(None) == "0"
    assert _version((255, 7)) == "ff-7"
    assert _version(12) == "r12"
