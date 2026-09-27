from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
workbooks = list((ROOT / "dataset" / "spravochniki").glob("*справочники*.xlsx"))
if not workbooks:
    raise FileNotFoundError("Не найден справочник трамвайных маршрутов")
workbook = openpyxl.load_workbook(workbooks[0], read_only=True, data_only=True)
sheet = workbook["Порядок_с_координатами"]
variants: dict[tuple[str, str, str], list[tuple[int, float, float, str]]] = defaultdict(list)
for row in sheet.iter_rows(min_row=3, values_only=True):
    route, trip, direction, sequence, stop_id = row[1], row[4], row[6], row[9], row[10]
    name, lat, lon = row[14], row[15], row[16]
    if not route or not lat or not lon:
        continue
    try:
        variants[(str(route), str(trip), str(direction))].append(
            (int(sequence), float(lon), float(lat), str(name or "Остановка"))
        )
    except (TypeError, ValueError):
        continue

features = []
for (route, trip, direction), stops in variants.items():
    stops.sort(key=lambda item: item[0])
    if len(stops) < 3:
        continue
    features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[s[1], s[2]] for s in stops]},
        "properties": {
            "route": int(route), "trip": trip, "direction": direction,
            "stop_count": len(stops), "stops": [s[3] for s in stops],
        },
    })
def _eq(a: list[float], b: list[float], eps: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def _merge_ways(ways: list[dict]) -> list[list[float]]:
    """Сшивает way-сегменты маршрута OSM в одну линию по совпадающим концам (порядок членов relation не гарантирован)."""
    remaining = [[[p["lon"], p["lat"]] for p in w["geometry"]] for w in ways]
    if not remaining:
        return []
    coords = remaining.pop(0)
    while remaining:
        head, tail = coords[0], coords[-1]
        for i, pts in enumerate(remaining):
            if _eq(tail, pts[0]):
                coords += remaining.pop(i)[1:]
                break
            if _eq(tail, pts[-1]):
                coords += list(reversed(remaining.pop(i)))[1:]
                break
            if _eq(head, pts[-1]):
                coords = remaining.pop(i)[:-1] + coords
                break
            if _eq(head, pts[0]):
                coords = list(reversed(remaining.pop(i)))[:-1] + coords
                break
        else:
            print(f"build_map_data: не нашёл совпадающий конец при сшивке OSM-геометрии, {len(remaining)} сегментов останется несостыкованными — проверить dataset/osm/tram_routes_extra.json")
            coords += remaining.pop(0)
    return coords


# Организаторский справочник даёт координаты только для маршрутов 1,5,7,11,12 (см. dataset/README.md,
# раздел «Геопривязка» — остановочная детализация помечена необязательным бонусом). Геометрия
# маршрутов 17,25,26,28,50 достаётся из OpenStreetMap (кэш в dataset/osm/, не от организаторов).
osm_cache = ROOT / "dataset" / "osm" / "tram_routes_extra.json"
if osm_cache.exists():
    osm_data = json.loads(osm_cache.read_text(encoding="utf-8"))
    osm_direction_seq: dict[int, int] = defaultdict(int)
    for rel in osm_data["elements"]:
        ways = [m for m in rel["members"] if m.get("type") == "way" and "geometry" in m and m.get("role", "") == ""]
        coords = _merge_ways(ways)
        if not coords:
            continue
        route = int(rel["tags"]["ref"])
        direction = osm_direction_seq[route]
        osm_direction_seq[route] += 1
        stop_count = sum(1 for m in rel["members"] if m.get("type") == "node" and m.get("role", "").startswith("stop"))
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "route": route, "trip": str(rel["id"]), "direction": str(direction),
                "stop_count": stop_count, "stops": [], "source": "OpenStreetMap",
            },
        })

output = ROOT / "artifacts" / "routes.geojson"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")
print(f"Сохранено {len(features)} вариантов маршрута в {output}")
