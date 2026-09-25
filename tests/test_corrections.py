import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.services import regime
from backend.app.store import DataStore, Series
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def day(client, url):
    return {p["date"]: p["passengers"] for p in client.get(url).json()}


def test_regime_endpoint_finds_known_shifts(client):
    body = client.get("/api/v1/regime").json()
    cells = {(c["route"], c["weekday"]): c["factor"] for c in body["cells"]}
    assert set(cells) == {(7, 6), (50, 5), (50, 6)}
    assert 0.6 < cells[(7, 6)] < 0.75 and cells[(50, 5)] < 0.1 and cells[(50, 6)] < 0.12
    assert body["weeks"] == 6 and body["method"] and body["thresholds"] == [0.7, 1.3]


def _series(values_by_day):
    dates = pd.date_range("2025-01-01", "2025-10-31")
    cube = np.zeros((1, len(dates), 24), dtype=np.int64)
    for i, d in enumerate(dates):
        cube[0, i, :] = values_by_day(d)
    return Series([1], dates, cube)


def test_regime_detection_on_synthetic_series():
    stable = _series(lambda d: 10)
    assert regime.compute(stable, {}) == []                       # ровный ряд: сдвигов нет
    last = pd.Timestamp("2025-10-31") - pd.Timedelta(days=42)
    shifted = _series(lambda d: 1 if (d.dayofweek == 5 and d > last) else 10)   # с осени по субботам почти пусто
    cells = regime.compute(shifted, {})
    assert [(c["route"], c["weekday"]) for c in cells] == [(1, 5)] and cells[0]["factor"] < 0.3
    short = _series(lambda d: 1 if (d.dayofweek == 5 and d > pd.Timestamp("2025-10-25")) else 10)
    assert regime.compute(short, {}) == []                        # одна-две недели: слишком мало для вывода о сдвиге


def test_forecast_regime_scales_only_flagged_cells(client):
    base = day(client, "/api/v1/forecast?route=50&start=2025-11-01&end=2025-11-07")
    fixed = day(client, "/api/v1/forecast?route=50&start=2025-11-01&end=2025-11-07&corrections=regime")
    assert fixed["2025-11-01"] < base["2025-11-01"] * 0.1 and fixed["2025-11-02"] < base["2025-11-02"] * 0.12   # сб и вс
    assert all(fixed[d] == base[d] for d in ("2025-11-05", "2025-11-06", "2025-11-07"))                         # будни без изменений
    other = day(client, "/api/v1/forecast?route=1&start=2025-11-01&end=2025-11-02")
    assert other == day(client, "/api/v1/forecast?route=1&start=2025-11-01&end=2025-11-02&corrections=regime")  # другие маршруты не тронуты


def test_weather_endpoint_and_factor(client):
    body = client.get("/api/v1/weather?start=2025-11-14&end=2025-11-16").json()
    by = {d["date"]: d for d in body["days"]}
    assert by["2025-11-14"]["factor"] == 1.0 and by["2025-11-15"]["flags"] == ["осадки ≥ 5 мм", "снегопад ≥ 2 см"]
    assert abs(by["2025-11-15"]["factor"] - body["rain_factor"] * body["snow_factor"]) < 1e-3 and body["rain_factor"] < 1
    assert "не прогноз" in body["note"]
    assert client.get("/api/v1/weather?start=2030-01-01&end=2030-01-02").json()["code"] == "out_of_range"
    assert client.get("/api/v1/weather?start=2025-12-01&end=2025-11-01").status_code == 400


def test_forecast_weather_correction_hits_only_flagged_days(client):
    base = day(client, "/api/v1/forecast?route=7&start=2025-11-13&end=2025-11-17")
    w = day(client, "/api/v1/forecast?route=7&start=2025-11-13&end=2025-11-17&corrections=weather")
    factor = client.get("/api/v1/weather?start=2025-11-15&end=2025-11-15").json()["days"][0]["factor"]
    assert w["2025-11-14"] == base["2025-11-14"] and w["2025-11-16"] == base["2025-11-16"]
    assert abs(w["2025-11-15"] - base["2025-11-15"] * factor) <= 12


def test_calendar_is_not_applied_twice_to_ml_forecast(client):
    health = client.get("/api/v1/health").json()
    assert health["ml_model"]["calendar_in_model"] is True
    base = day(client, "/api/v1/forecast?route=7&start=2025-11-03&end=2025-11-04")
    corrected = day(client, "/api/v1/forecast?route=7&start=2025-11-03&end=2025-11-04&corrections=calendar")
    assert corrected == base


def test_corrections_equal_adjusted_endpoint(client):
    query = "/api/v1/forecast?route=7&granularity=day&corrections=calendar,regime,weather"
    corrected = day(client, query)
    adj = client.post("/api/v1/forecast/adjusted", json={"route": 7, "calendar": True, "regime": True, "weather_auto": True}).json()
    assert corrected == {p["date"]: p["passengers"] for p in adj["data"]}                 # один и тот же механизм
    cells = adj["summary"]["regime_cells"]
    assert [(c["route"], c["weekday"]) for c in cells] == [(7, "вс")]                      # только маршрут из запроса
    all_routes = client.post("/api/v1/forecast/adjusted", json={"regime": True}).json()["summary"]["regime_cells"]
    assert len(all_routes) == 3
    assert len(adj["summary"]["weather_days"]) == 8 and len(adj["summary"]["calendar_days"]) == 3


def test_export_with_corrections(client):
    r = client.get("/api/v1/export?route=50&granularity=day&start=2025-11-01&end=2025-11-02&corrections=regime")
    assert "corr-regime" in r.headers["content-disposition"]
    rows = pd.read_csv(io.StringIO(r.text), sep=";")
    assert rows.prediction.tolist() == list(day(client, "/api/v1/forecast?route=50&start=2025-11-01&end=2025-11-02&corrections=regime").values())
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(client.get("/api/v1/export?format=xlsx&route=7&granularity=day&corrections=calendar").content))
    assert any(row[0] == "Поправки" and row[1] == "calendar" for row in wb["Сводка"].iter_rows(values_only=True))


@pytest.mark.parametrize("url,status,code", [
    ("/api/v1/forecast?corrections=nope", 422, "unknown_correction"),
    ("/api/v1/export?corrections=regime,nope", 422, "unknown_correction"),
    ("/api/v1/export?kind=history&corrections=regime", 422, "corrections_forecast_only"),
])
def test_corrections_errors(client, url, status, code):
    r = client.get(url)
    assert r.status_code == status and r.json()["code"] == code and r.json()["detail"]


def test_unavailable_weather_is_reported(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXTERNAL_DIR", tmp_path)
    original = client.app.state.store
    client.app.state.store = DataStore()
    try:
        r = client.get("/api/v1/forecast?corrections=weather")
        assert r.status_code == 422 and r.json()["code"] == "weather_unavailable"
        assert client.get("/api/v1/forecast?corrections=regime").status_code == 200      # сдвиги режима от календаря не зависят
    finally:
        client.app.state.store = original
