import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_catalog_only_routes_with_stops(client):
    body = client.get("/api/v1/stops").json()
    assert body["estimated"] is True and body["routes"] == [1, 5, 7, 11, 12] and body["method"]
    for route in body["routes"]:
        shares = sum(s["boarding_share"] for s in body["stops"] if s["route"] == route)
        assert abs(shares - 1) < 1e-3, route
    assert {"stop_id", "name", "lat", "lon", "district", "direction", "sequence", "is_hub"} <= set(body["stops"][0])


def test_flow_sums_to_route_total_and_respects_hours(client):
    full = client.get("/api/v1/stops/flow?route=7&start=2025-11-03&end=2025-11-09").json()
    assert sum(s["boardings"] for s in full["stops"]) == full["route_total"]
    peak = client.get("/api/v1/stops/flow?route=7&start=2025-11-03&end=2025-11-09&hour_from=7&hour_to=9").json()
    assert 0 < peak["route_total"] < full["route_total"]
    first = next(s for s in full["stops"] if s["direction"] == 0 and s["sequence"] == 1)
    last = [s for s in full["stops"] if s["direction"] == 0][-1]
    assert first["boardings"] > last["boardings"]  # начальная остановка нагружена сильнее конечной


@pytest.mark.parametrize("route", [1, 5, 7, 11, 12])
def test_flow_conserves_total_for_every_route_with_stops(client, route):
    result = client.get(f"/api/v1/stops/flow?route={route}&start=2025-11-03&end=2025-11-03").json()
    assert sum(stop["boardings"] for stop in result["stops"]) == result["route_total"]


def test_flow_history_and_route5_zero(client):
    assert client.get("/api/v1/stops/flow?route=7&kind=history").json()["route_total"] > 0
    z = client.get("/api/v1/stops/flow?route=5").json()
    assert z["route_total"] == 0 and all(s["boardings"] == 0 for s in z["stops"])


def test_segments_have_midroute_peak(client):
    g = client.get("/api/v1/stops/segments?route=7").json()
    for d in (0, 1):
        loads = [s["passengers"] for s in g["segments"] if s["direction"] == d]
        stops = [s for s in client.get("/api/v1/stops?route=7").json()["stops"] if s["direction"] == d]
        assert len(loads) == len(stops) - 1 and min(loads) >= 0
        peak = loads.index(max(loads))
        assert 0 < peak < len(loads) - 1
    assert g["peak"]["passengers"] == max(s["passengers"] for s in g["segments"])


def test_stop_series_matches_flow(client):
    flow = client.get("/api/v1/stops/flow?route=1&start=2025-11-03&end=2025-11-09").json()
    stop = flow["stops"][3]
    ser = client.get(f"/api/v1/stops/{stop['stop_id']}/series?route=1&start=2025-11-03&end=2025-11-09").json()
    expected = sum(s["boardings"] for s in flow["stops"] if s["stop_id"] == stop["stop_id"])
    assert len(ser["data"]) == 7 and abs(sum(p["passengers"] for p in ser["data"]) - expected) <= 8
    hourly = client.get(f"/api/v1/stops/{stop['stop_id']}/series?start=2025-11-03&end=2025-11-03&granularity=hour").json()
    assert len(hourly["data"]) == 24 and {"date", "hour", "passengers"} <= set(hourly["data"][0])


def test_stop_series_can_filter_a_shared_stop_by_route(client):
    route_7 = client.get("/api/v1/stops?route=7").json()["stops"]
    route_11_ids = {s["stop_id"] for s in client.get("/api/v1/stops?route=11").json()["stops"]}
    stop = next(s for s in route_7 if s["stop_id"] in route_11_ids)
    params = "start=2025-11-03&end=2025-11-09"

    route_only = client.get(f"/api/v1/stops/{stop['stop_id']}/series?{params}&route=7").json()
    all_routes = client.get(f"/api/v1/stops/{stop['stop_id']}/series?{params}").json()

    assert route_only["routes"] == [7]
    assert set(all_routes["routes"]) == {7, 11}
    assert sum(p["passengers"] for p in all_routes["data"]) > sum(p["passengers"] for p in route_only["data"])


def test_route_filtered_stop_series_uses_single_route_hour_limit(client):
    stop = client.get("/api/v1/stops?route=7").json()["stops"][0]
    base = f"/api/v1/stops/{stop['stop_id']}/series?start=2025-11-01&end=2025-12-31&granularity=hour"

    route_only = client.get(f"{base}&route=7")
    all_routes = client.get(base)

    assert route_only.status_code == 200 and len(route_only.json()["data"]) == 61 * 24
    assert all_routes.status_code == 422 and all_routes.json()["code"] == "range_too_wide"


@pytest.mark.parametrize("url,status,code", [
    ("/api/v1/stops?route=17", 404, "stops_not_available"),
    ("/api/v1/stops/flow?route=99", 404, "route_not_found"),
    ("/api/v1/stops/flow", 422, "validation_error"),
    ("/api/v1/stops/flow?route=7&hour_from=10&hour_to=5", 422, "bad_hours"),
    ("/api/v1/stops/flow?route=7&hour_to=30", 422, "validation_error"),
    ("/api/v1/stops/segments?route=25", 404, "stops_not_available"),
    ("/api/v1/stops/000/series", 404, "stop_not_found"),
    ("/api/v1/stops/3614/series?route=99", 404, "route_not_found"),
    ("/api/v1/stops/flow?route=7&start=2030-01-01&end=2030-01-02", 422, "out_of_range"),
])
def test_stops_errors(client, url, status, code):
    r = client.get(url)
    assert r.status_code == status and r.json()["code"] == code and r.json()["detail"]
