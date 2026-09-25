from __future__ import annotations

import json
import math
from collections import defaultdict

from .. import config

METHOD = (
    "Оценка, а не измерение: в валидациях нет привязки к остановкам (place_id — депо). Посадки маршрута делятся между "
    "остановками по весам: начальная остановка направления ×{first_board}, конечная ×{last_board}, узловая (остановка "
    "нескольких маршрутов) ×{hub}; направления поровну. Загрузка участка: севший на остановке пассажир проезжает в среднем "
    "~{trip} остановок (экспоненциальный спад), высадка предпочтительнее на узловых, остаток высаживается на конечной."
).format(**config.STOP_WEIGHTS, trip=config.STOP_MEAN_TRIP)


def _normalized(weights: list[float]) -> list[float]:
    total = sum(weights)
    return [w / total for w in weights] if total else [0.0] * len(weights)


def _onboard(board: list[float], hub: list[float]) -> list[float]:
    """Доля посадок направления, находящаяся в вагоне на участке после остановки k (k = 0 … n-2)."""
    n = len(board)
    decay = math.exp(-1 / config.STOP_MEAN_TRIP)
    load = [0.0] * (n - 1)
    for i in range(n - 1):
        w = [hub[j] * decay ** (j - i) for j in range(i + 1, n)]  # высадка на остановке j > i
        suffix = [0.0] * (len(w) + 1)
        for t in range(len(w) - 1, -1, -1):
            suffix[t] = suffix[t + 1] + w[t]
        for k in range(i, n - 1):
            load[k] += board[i] * suffix[k - i] / suffix[0]  # на участке k едет тот, кто выходит не раньше k+1
    return load


def build_index(routes: list[int]) -> dict[int, dict[int, list[dict]]]:
    """route → direction → остановки по порядку с долями посадок и высадок (от посадок всего маршрута)."""
    if not config.STOPS_FILE.exists():
        return {}
    w = config.STOP_WEIGHTS
    grouped: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for rec in json.loads(config.STOPS_FILE.read_text(encoding="utf-8")):
        if rec["route"] in routes:
            grouped[rec["route"]][rec["direction"]].append(rec)

    index: dict[int, dict[int, list[dict]]] = {}
    for route, directions in grouped.items():
        share = 1 / len(directions)
        index[route] = {}
        for direction, stops in directions.items():
            stops = sorted(stops, key=lambda s: s["sequence"])
            n = len(stops)
            hub = [w["hub"] if len(s["routes_serving"]) > 1 else 1.0 for s in stops]
            board = [h * (w["first_board"] if i == 0 else w["last_board"] if i == n - 1 else 1.0) for i, h in enumerate(hub)]
            shares = [share * b for b in _normalized(board)]
            onboard = _onboard(shares, hub)
            index[route][direction] = [
                {**s, "is_hub": len(s["routes_serving"]) > 1, "board_share": sh, "onboard_after": ob}
                for s, sh, ob in zip(stops, shares, onboard + [None])
            ]
    return index
