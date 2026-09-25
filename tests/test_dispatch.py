import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def day(client, **q):
    return client.get("/api/v1/dispatch/day", params=q)


def test_day_plan_structure_and_sums(client):
    d = day(client, date="2025-11-10", route=7).json()
    assert d["weekday"] == "понедельник" and len(d["hours"]) == 24 and d["estimated"] is True
    assert sum(h["boardings"] for h in d["hours"]) == d["day_total"]
    fc = client.get("/api/v1/forecast?route=7&granularity=day&start=2025-11-10&end=2025-11-10").json()[0]["passengers"]
    assert d["day_total"] == fc  # обычный день: поправки ничего не меняют
    assert d["peaks"]["hours"] == [8, 17, 18] and 0.2 < d["peaks"]["share"] < 0.35 and d["peaks"]["peak_to_mean"] > 1.3
    assert [h["level"] for h in d["hours"] if h["hour"] in (8, 17, 18)] == ["пик"] * 3
    assert d["hours"][3]["level"] in ("нет движения", "обычно", "ниже обычного", "выше обычного")


def test_holiday_is_flagged_by_calendar_correction(client):
    plain = day(client, date="2025-11-03", route=7, corrections="").json()
    fixed = day(client, date="2025-11-03", route=7).json()  # по умолчанию calendar,regime
    assert fixed["corrections"] == ["calendar", "regime"] and plain["corrections"] == []
    assert fixed["day_total"] < plain["day_total"] * 0.5
    assert plain["hours"][8]["index"] == 1.0 and fixed["hours"][8]["index"] < 0.6


def test_vehicle_calculator(client):
    d = day(client, date="2025-11-10", route=7, capacity=400, vehicles=4).json()
    h8 = d["hours"][8]
    assert h8["vehicles_needed"] == -(-h8["boardings"] // 400) and h8["vehicles_delta"] == h8["vehicles_needed"] - 4
    assert h8["load_level"] == "перегрузка" and 8 in d["vehicles"]["overloaded_hours"]
    quiet = day(client, date="2025-11-10", route=7, capacity=400, vehicles=40).json()
    assert quiet["vehicles"]["overloaded_hours"] == [] and quiet["hours"][8]["load_level"] == "запас"


@pytest.mark.parametrize("q,code", [
    ({"date": "2025-11-10", "route": 7, "capacity": 400}, "capacity_and_vehicles"),
    ({"date": "2025-11-10", "capacity": 400, "vehicles": 5}, "vehicles_need_route"),
    ({"date": "2025-11-10", "route": 7, "corrections": "bogus"}, "unknown_correction"),
    ({"date": "2025-11-10", "route": 99}, "route_not_found"),
    ({"date": "2024-01-01", "route": 7}, "out_of_range"),
    ({"date": "2025-11-10", "route": 7, "capacity": 0, "vehicles": 5}, "validation_error"),
    ({"date": "вчера"}, "validation_error"),
])
def test_day_plan_errors(client, q, code):
    r = day(client, **q)
    assert r.status_code in (404, 422) and r.json()["code"] == code


def test_hotspots_only_for_routes_with_stops(client):
    with_stops = day(client, date="2025-11-10", route=7).json()["hotspots"]
    assert 1 <= len(with_stops) <= 5 and with_stops == sorted(with_stops, key=lambda x: -x["passengers"])
    assert day(client, date="2025-11-10", route=17).json()["hotspots"] is None
    assert day(client, date="2025-11-10").json()["hotspots"] is None


def test_savings_lists_holidays_and_regime_days(client):
    r = client.get("/api/v1/dispatch/savings", params={"limit": 200}).json()
    assert r["total_days"] == len(r["days"]) and r["total_delta"] == sum(x["delta"] for x in r["days"])
    assert all(x["corrected"] <= x["base"] * 0.75 for x in r["days"])
    holiday = [x for x in r["days"] if x["date"] in ("2025-11-03", "2025-11-04", "2025-12-31")]
    assert len(holiday) == 27 and all("праздничный день" in x["reasons"] for x in holiday)  # 3 праздничных дня × 9 маршрутов (у маршрута 5 нулевой прогноз)
    r50 = client.get("/api/v1/dispatch/savings", params={"route": 50, "limit": 200}).json()
    weekends = [x for x in r50["days"] if x["weekday"] in ("суббота", "воскресенье")]
    assert len(weekends) == 18 and all("сдвиг режима маршрута" in x["reasons"] for x in weekends)


def test_savings_without_corrections_and_limits(client):
    none = client.get("/api/v1/dispatch/savings", params={"corrections": ""}).json()
    assert none["total_days"] == 0 and none["days"] == []
    few = client.get("/api/v1/dispatch/savings", params={"limit": 2}).json()
    assert len(few["days"]) == 2 and few["total_days"] > 2 and few["days"][0]["delta"] >= few["days"][1]["delta"]
    strict = client.get("/api/v1/dispatch/savings", params={"threshold": 0.9}).json()
    assert strict["total_days"] < few["total_days"]
    assert client.get("/api/v1/dispatch/savings", params={"threshold": 1.5}).status_code == 422
    assert client.get("/api/v1/dispatch/savings", params={"route": 99}).status_code == 404
