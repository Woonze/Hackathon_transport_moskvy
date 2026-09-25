import pytest
import pandas as pd
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.services import ingest
from backend.app.store import DataStore
from backend.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def rec(ts="2025-11-03 08:15:00", route="7 трамвай", result=1, **extra):
    return {"tran_date_time": ts, "validation_result": result, "ngpt_route": route, **extra}


def post(client, records, **kw):
    return client.post("/api/v1/ingest/validations", json={"records": records, **kw})


def hour_total(client, route, day, hour):
    rows = client.get(f"/api/v1/history?route={route}&granularity=hour&start={day}&end={day}").json()
    return next(r["passengers"] for r in rows if r["hour"] == hour)


def test_ingest_normalizes_and_extends_history(client):
    before = hour_total(client, 7, "2025-10-20", 8)
    r = post(client, [
        rec("2025-10-20 08:15:00"), rec("2025-10-20 08:59:59"),            # два принятых
        rec("2025-10-20 08:30:00", result=90),                             # отказ валидации
        rec("2025-10-20 08:30:00", route="99 трамвай"),                     # неизвестный маршрут
        rec("2025-10-20 08:30:00", route="автобус 7"),                      # битый формат маршрута
        rec("вчера"),                                                       # битое время
        rec("2019-01-01 08:00:00"),                                         # вне периода
    ])
    body = r.json()
    assert r.status_code == 200 and body["status"] == "accepted" and body["accepted"] == 2
    assert body["rejected"] == {"validation_failed": 1, "bad_route_format": 1, "bad_time": 1, "unknown_route": 1, "date_out_of_range": 1}
    assert hour_total(client, 7, "2025-10-20", 8) == before + 2


def test_ingest_is_idempotent_by_content_and_batch_id(client):
    records = [rec("2025-10-21 10:00:00")]
    before = hour_total(client, 7, "2025-10-21", 10)
    assert post(client, records).json()["status"] == "accepted"
    again = post(client, records).json()
    assert again["status"] == "already_ingested" and again["accepted"] == 0
    assert hour_total(client, 7, "2025-10-21", 10) == before + 1
    assert post(client, records, batch_id="manual-1").json()["status"] == "accepted"
    assert post(client, records, batch_id="manual-1").json()["status"] == "already_ingested"
    conflict = post(client, [rec("2025-10-21 11:00:00")], batch_id="manual-1")
    assert conflict.status_code == 409 and conflict.json()["code"] == "batch_id_conflict"


def test_ingest_content_idempotency_ignores_record_order(client):
    records = [rec("2025-10-21 10:00:00"), rec("2025-10-21 10:30:00")]
    before = hour_total(client, 7, "2025-10-21", 10)
    assert post(client, records).json()["status"] == "accepted"
    retry = post(client, list(reversed(records))).json()
    assert retry["status"] == "already_ingested"
    assert hour_total(client, 7, "2025-10-21", 10) == before + 2


def test_ingest_dedups_device_and_tran_no_within_batch(client):
    r = post(client, [rec("2025-10-22 09:00:00", device_no="5", tran_no="1"),
                      rec("2025-10-22 09:00:01", device_no="5", tran_no="1"),
                      rec("2025-10-22 09:00:02", device_no="6", tran_no="1")]).json()
    assert r["duplicates"] == 1 and r["accepted"] == 2


@pytest.mark.parametrize("failed_first", [True, False])
def test_failed_duplicate_cannot_hide_successful_validation(client, failed_first):
    before = _day(client, 7, "2025-10-22")
    failed = rec("2025-10-22 09:00:00", result=90, device_no="8", tran_no="2")
    successful = rec("2025-10-22 09:00:00", device_no="8", tran_no="2")
    records = [failed, successful] if failed_first else [successful, failed]

    result = post(client, records).json()

    assert result["accepted"] == 1
    assert result["duplicates"] == 0
    assert result["rejected"]["validation_failed"] == 1
    assert _day(client, 7, "2025-10-22") == before + 1


def test_new_month_extends_history_and_export(client):
    assert client.get("/api/v1/history?start=2025-11-03&end=2025-11-03").status_code == 422
    post(client, [rec("2025-11-03 08:15:00")] * 3)
    assert client.get("/api/health").json()["history_period"][1] == "2025-11-03"
    rows = client.get("/api/v1/history?route=7&start=2025-11-03&end=2025-11-03").json()
    assert rows == [{"route": 7, "date": "2025-11-03", "passengers": 3}]
    assert "2025-11-03" in client.get("/api/v1/export?kind=history&granularity=day&route=7&start=2025-11-03&end=2025-11-03").text


def test_second_worker_sees_ingested_data(client):
    """Другой процесс дописал файл — этот воркер подхватывает его по mtime и сбрасывает свой кэш."""
    before = hour_total(client, 1, "2025-10-23", 12)  # заодно прогревает кэш этого воркера
    other_store = DataStore()  # «второй воркер»: своя память, общий файл
    ingest.process([rec("2025-10-23 12:00:00", route="1 трамвай")], None, other_store)
    assert other_store is not client.app.state.store
    assert hour_total(client, 1, "2025-10-23", 12) == before + 1


def test_overlay_lock_serializes_concurrent_processes(tmp_path):
    """Два процесса одновременно добавляют пакет: заголовок и обе строки сохраняются."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pandas as pd

    overlay_path = tmp_path / "concurrent.csv"
    code = (
        "import pandas as pd, sys; "
        "from pathlib import Path; "
        "from backend.app import config; config.OVERLAY = Path(sys.argv[1]); "
        "from backend.app.services.overlay import append; "
        "append(sys.argv[2], pd.DataFrame([{'route': 7, 'date': pd.Timestamp('2025-10-25'), 'hour': 11, 'boardings': 1}]))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["INGEST_FILE"] = str(overlay_path)
    cwd = Path(__file__).resolve().parents[1]
    processes = [
        subprocess.Popen([sys.executable, "-c", code, str(overlay_path), f"parallel-{i}"], cwd=cwd, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i in range(2)
    ]
    outputs = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], outputs
    saved = pd.read_csv(overlay_path, sep=";")
    assert sorted(saved["batch_id"].tolist()) == ["parallel-0", "parallel-1"]


@pytest.mark.parametrize("body,status,code", [
    ({"records": []}, 422, "validation_error"),
    ({"records": [{"foo": 1}]}, 422, "missing_fields"),
    ({"records": [rec()], "batch_id": "плохой id!"}, 422, "validation_error"),
    ({}, 422, "validation_error"),
])
def test_ingest_errors(client, body, status, code):
    r = client.post("/api/v1/ingest/validations", json=body)
    assert r.status_code == status and r.json()["code"] == code


def test_ingest_size_limit(client, monkeypatch):
    big = [rec()] * (config.INGEST_MAX_RECORDS + 1)
    assert post(client, big).status_code == 422


def test_validation_messages_are_russian(client):
    import re

    for body in ({"records": []}, {"records": [rec()], "batch_id": "плохой id!"}, {"records": "не список"}):
        detail = client.post("/api/v1/ingest/validations", json=body).json()["detail"]
        assert not re.search(r"[A-Za-z]{4,} [a-z]{2,}", detail.replace("batch_id", "").replace("records", "")), detail


def test_ingest_requires_api_key_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "INGEST_API_KEY", "test-secret-key")
    key = config.INGEST_API_KEY
    body = {"records": [rec("2025-10-24 10:00:00")]}
    r = client.post("/api/v1/ingest/validations", json=body)
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    assert client.post("/api/v1/ingest/validations", json=body, headers={"X-API-Key": "wrong-key"}).status_code == 401
    ok = client.post("/api/v1/ingest/validations", json=body, headers={"X-API-Key": key})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert client.get("/api/v1/health").json()["ingest_protected"] is True
    assert client.get("/api/v1/forecast?route=7").status_code == 200  # чтение ключа не требует


def _day(client, route, day):
    return client.get(f"/api/v1/history?route={route}&start={day}&end={day}").json()[0]["passengers"]


def test_corrupted_overlay_file_does_not_break_service(client):
    """Обрыв записи и мусор в файле принятых данных: сервис отвечает, битые строки пропускаются, приём продолжает работать."""
    base = _day(client, 7, "2025-10-22")
    assert post(client, [rec("2025-10-22 09:00:00")]).json()["accepted"] == 1
    with open(config.OVERLAY, "a", encoding="utf-8") as fh:
        fh.write("b-broken;7;2025-10-22;9;")                      # оборвана посреди строки, без перевода строки
    with open(config.OVERLAY, "a", encoding="utf-8") as fh:
        fh.write("\nнеправильная строка\nb-x;7;2025-10-22;99;5\nb-y;7;2025-10-22;9;-3\n")  # мусор, час 99, отрицательное число
    import os, time
    os.utime(config.OVERLAY, (time.time() + 5, time.time() + 5))  # гарантируем смену отпечатка файла
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/forecast?route=7").status_code == 200
    assert _day(client, 7, "2025-10-22") == base + 1               # корректная строка осталась, битые пропущены
    assert post(client, [rec("2025-10-22 10:00:00")]).json()["accepted"] == 1   # новый пакет не склеился с оборванной строкой
    assert _day(client, 7, "2025-10-22") == base + 2


def test_empty_and_foreign_overlay_files_are_ignored(client):
    config.OVERLAY.write_text("", encoding="utf-8")
    assert client.get("/api/v1/health").status_code == 200
    config.OVERLAY.write_text("совсем;другие;столбцы\n1;2;3\n", encoding="utf-8")
    import os, time
    os.utime(config.OVERLAY, (time.time() + 5, time.time() + 5))
    assert client.get("/api/v1/routes").status_code == 200
    assert _day(client, 7, "2025-10-22") >= 0


@pytest.mark.parametrize("contents", ["", "совсем;другие;столбцы\n1;2;3\n"])
def test_ingest_recovers_empty_or_foreign_overlay_file(client, contents):
    config.OVERLAY.write_text(contents, encoding="utf-8")
    assert client.get("/api/v1/health").status_code == 200
    before = _day(client, 7, "2025-10-27")

    result = post(client, [rec("2025-10-27 08:15:00")], batch_id="recovered-file").json()

    assert result["status"] == "accepted" and result["accepted"] == 1
    saved = pd.read_csv(config.OVERLAY, sep=";")
    assert list(saved.columns) == ["batch_id", "route", "date", "hour", "boardings"]
    assert saved.iloc[0]["batch_id"] == "recovered-file"
    assert _day(client, 7, "2025-10-27") == before + 1


def test_service_starts_with_corrupted_overlay(client):
    config.OVERLAY.write_text("не csv вообще \x00\x00 ;;;\n;;;\n", encoding="utf-8")
    store = DataStore()                       # раньше такой файл ронял запуск
    assert store.history.values.sum() > 0
