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
output = ROOT / "artifacts" / "routes.geojson"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")
print(f"Сохранено {len(features)} вариантов маршрута в {output}")
