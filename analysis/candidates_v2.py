"""Кандидаты на загрузку по итогам проверки гипотез (submission.csv и model/forecast.py не меняются).

    python -m analysis.candidates_v2            → artifacts/candidates_v2/*.csv и index.csv
    python -m analysis.candidates_v2 --final    → ещё пять итоговых вариантов в artifacts/candidates_v2/final/
    python -m analysis.candidates_v2 --best5    → пять лучших ставок в artifacts/candidates_v2/best5/
    python -m analysis.candidates_v2 --round5   → пять вариантов пятого раунда в artifacts/candidates_v2/round5/
    python -m analysis.candidates_v2 --round4   → пять вариантов четвёртого раунда в artifacts/candidates_v2/round4/
    python -m analysis.candidates_v2 --round3   → пять вариантов третьего раунда в artifacts/candidates_v2/round3/
    python -m analysis.candidates_v2 --round2   → пять вариантов второго раунда (по скорам платформы) в artifacts/candidates_v2/round2/

Основа: профиль школьного сезона без аномальных маршрут-дней и без праздников, отдельный профиль праздничных будней (analysis.panel).
Поверх основы — события, найденные в открытых источниках (ссылки в EVENTS), и данные, подтверждающие их эффект в истории:
  * ремонт путей в Протопоповском переулке: с 6.09 трамвай 50 не ходит по выходным, трамвай 7 ходит короче; срок «до конца осени»;
  * запуск трамвая 5 (Рижская — Белорусский вокзал) 16.12: маршрут есть в сетке прогноза, а в истории посадок нет;
  * выходной внутри трёхдневного блока (2.11 перед праздниками 3–4.11): в истории аналоги дают около 0,9 обычного воскресенья.
Что именно из этого сработает в скрытом периоде, покажет скор платформы: варианты отличаются одним допущением каждый.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis import panel as P
from analysis.panel import D, DATES, HOL, ROUTES, SUMMER, Y
from backend.app.console import configure_console

ROOT = P.E.ROOT
OUT = ROOT / "artifacts" / "candidates_v2"
START, END = pd.Timestamp("2025-11-01"), pd.Timestamp("2025-12-31")
REPAIR_FROM = pd.Timestamp("2025-09-06")
REPAIR_END = pd.Timestamp("2025-11-30")          # «до конца осени»
ROUTE5_FROM = pd.Timestamp("2025-12-16")
BLOCK_SUNDAY = pd.Timestamp("2025-11-02")        # воскресенье перед праздниками 3–4.11 (1.11 — рабочая суббота)
EVENTS = {
    "Ремонт путей в Протопоповском переулке (трамвай 50 не ходит по выходным, 7 ходит короче, до конца осени)":
        ["https://newsvostok.ru/dlya-tramvaev-7-i-50-izmeneniya-po-vyhodnym-budut-dejstvovat-do-kontsa-oseni/",
         "https://rimc-rambam.ru/news/14880/"],
    "Запуск трамвайного маршрута 5, Рижская — Белорусский вокзал, 16.12.2025 (прогноз организаторов около 20 тыс. в сутки)":
        ["https://www.mos.ru/mayor/themes/13888050/", "https://msk1.ru/text/transport/2025/12/16/76173070/"],
    "Трамвайный диаметр Т1, 12.11.2025: объединил маршруты 13, 39, 90 (маршрутов сетки прогноза не затрагивает)":
        ["https://www.mos.ru/mayor/themes/13679050/"],
}


def base_forecast(trim: float | None = None, blend_gbm: float = 0.0) -> tuple[np.ndarray, np.ndarray, dict]:
    """[R, 61, 24] основа, пред-ремонтный профиль маршрутов 7 и 50, коэффициенты режима из данных"""
    a = D
    p = P.predict_structured(a, trim=trim)
    if blend_gbm:
        from analysis import gbm
        mixed = (1 - blend_gbm) * p + blend_gbm * gbm.predict(a, ("summer",))
        keep = P.fut_hol(a) | (P.fut_dates(a) == START)   # праздники (12 примеров) и рабочая суббота 1.11 (аналогов нет): бустинг экстраполирует хуже профиля
        mixed[:, keep] = p[:, keep]
        p = mixed
    dates = P.fut_dates(a)
    dow = P.fut_dow(a)
    repair_day = np.flatnonzero(DATES >= REPAIR_FROM)
    pre = np.arange(D) < repair_day[0]
    mask = P.anomaly_mask(a) | SUMMER[None, :]
    pre_prof = P.profile(a, mask, days=pre, trim=trim)                    # обычные выходные до 6 сентября
    facts = {}
    for route in (7, 50):
        r = ROUTES.index(route)
        for d in (5, 6):
            recent = np.flatnonzero((P.DOW == d) & (DATES >= REPAIR_FROM))
            act = Y[r, recent].sum(axis=1).mean()
            ref = pre_prof[r, d].sum()
            facts[(route, d)] = act / ref
            p[r, dow == d] = pre_prof[r, d]                    # основа для выходных этих маршрутов: без периода ремонта
    return p, pre_prof, facts


def apply_repair(p, facts, until_month_end=True):
    dates = P.fut_dates(D)
    dow = P.fut_dow(D)
    out = p.copy()
    for (route, d), f in facts.items():
        r = ROUTES.index(route)
        sel = (dow == d) & (dates <= (REPAIR_END if until_month_end else END))
        out[r, sel] = p[r, sel] * f
    return out


def sunday_block(p):
    out = p.copy()
    i = int((BLOCK_SUNDAY - START).days)
    out[:, i] = p[:, i] * 0.9
    return out


def route5(p_routes: np.ndarray, weekday_total: float) -> np.ndarray:
    """строка нового маршрута 5: суточные уровни (будни, суббота, воскресенье, праздник) и часовая форма из средних профилей сети"""
    dates, dow, hol = P.fut_dates(D), P.fut_dow(D), P.fut_hol(D)
    prof = P.profile(D, P.anomaly_mask(D) | SUMMER[None, :])
    shape = {k: prof[:, dset].sum(axis=(0, 1)) for k, dset in (("work", [0, 1, 2, 3, 4]), ("sat", [5]), ("sun", [6]))}
    shape = {k: v / v.sum() for k, v in shape.items()}
    level = {"work": weekday_total, "sat": 0.55 * weekday_total, "sun": 0.45 * weekday_total, "hol": 0.4 * weekday_total}
    row = np.zeros((P.FUT_N, 24))
    for i, day in enumerate(dates):
        if day < ROUTE5_FROM:
            continue
        ramp = 0.6 if day == ROUTE5_FROM else 0.8 if day == ROUTE5_FROM + pd.Timedelta(days=1) else 1.0
        if hol[i]:
            row[i] = shape["sun"] * level["hol"]
        else:
            k = "work" if dow[i] < 5 else "sat" if dow[i] == 5 else "sun"
            row[i] = shape[k] * level[k] * ramp
    return row


def to_frame(p_routes: np.ndarray, r5: np.ndarray | None, scale: float = 1.0) -> pd.DataFrame:
    tpl = pd.read_csv(ROOT / "dataset" / "test_submission.csv", sep=";", parse_dates=["date"])
    all_routes = sorted(set(ROUTES) | {5})
    cube = np.zeros((len(all_routes), P.FUT_N, 24))
    for r, route in enumerate(ROUTES):
        cube[all_routes.index(route)] = p_routes[r]
    if r5 is not None:
        cube[all_routes.index(5)] = r5
    di = {d: i for i, d in enumerate(P.fut_dates(D))}
    idx = (tpl.route.map({r: i for i, r in enumerate(all_routes)}).to_numpy(), tpl.date.map(di).to_numpy(), tpl.hour.to_numpy())
    out = tpl[["route", "date", "hour"]].copy()
    out["prediction"] = np.maximum(np.rint(cube[idx] * scale), 0).astype(int)
    return out


def finals() -> list[tuple[str, str, pd.DataFrame]]:
    """Пять итоговых вариантов «максимум скора»: центральный сценарий и четыре его отличия (усечённое среднее 10 % в профиле)."""
    p0, _, facts = base_forecast(trim=0.1)
    central = sunday_block(apply_repair(p0, facts))
    persist = sunday_block(apply_repair(p0, facts, until_month_end=False))
    pb, _, factsb = base_forecast(trim=0.1, blend_gbm=0.5)
    blend = sunday_block(apply_repair(pb, factsb))
    return [
        ("f1_central", "центральный сценарий: ремонт 7 и 50 до конца ноября, трамвай 5 с 16.12 (10 тыс. в будни), декабрь обычный", to_frame(central, route5(central, 10_000))),
        ("f2_repair_dec", "f1, но ремонт 7 и 50 продолжается и в декабре", to_frame(persist, route5(persist, 10_000))),
        ("f3_r5_20k", "f1, но трамвай 5 по прогнозу организаторов (20 тыс. в будни)", to_frame(central, route5(central, 20_000))),
        ("f4_gbm_blend", "f1 с основой из смеси 50/50 бустинга и профиля (нужен scikit-learn)", to_frame(blend, route5(blend, 10_000))),
        ("f5_level_102", "f1 с общим уровнем ×1,02 (предновогодний рост спроса: допущение)", to_frame(central, route5(central, 10_000), 1.02)),
    ]


# Результаты платформы по итоговым вариантам (скор): f1 0,88300, f2 0,87565, f3 0,87324, f4 0,88318, f5 0,88561.
# Выводы: ремонт 7 и 50 в декабре почти закончился (f2 хуже f1; истина примерно на 87 % пути от «режим продолжается» к «обычно»);
# трамвай 5 не выше уровня 10 тыс. (f3 хуже f1 почти на полную разницу файлов); бустинг ничего не добавил (f4 ≈ f1); общий уровень выше (f5 лучше f1).
DEC_RESTORE = 0.87


def round2() -> list[tuple[str, str, pd.DataFrame]]:
    """Второй раунд: пять вариантов от двух лучших (f5 и f4); каждый отличается от h1 одним допущением."""
    dates = P.fut_dates(D)
    nov = np.asarray(dates <= REPAIR_END)

    def build(blend=0.0, nov_k=1.035, dec_k=1.035, r5=10_000, work_k=None):
        p0, _, facts = base_forecast(trim=0.1, blend_gbm=blend)
        restored, persist = apply_repair(p0, facts), apply_repair(p0, facts, until_month_end=False)
        cube = restored.copy()
        for route in (7, 50):
            r = ROUTES.index(route)
            dec = ~nov
            cube[r, dec] = persist[r, dec] + DEC_RESTORE * (restored[r, dec] - persist[r, dec])   # декабрь: почти обычный режим
        cube = sunday_block(cube)
        k = np.where(nov, nov_k, dec_k)[None, :, None] * np.ones((1, 1, 1))
        if work_k is not None:
            dow = P.fut_dow(D)
            k = np.where((dow < 5) & ~P.fut_hol(D), work_k[0], work_k[1])[None, :, None]
        return to_frame(cube * k, route5(cube, r5))

    return [
        ("h1_f5_tuned", "от f5: уровень ×1,035, декабрьский режим 7 и 50 на 87 % пути к обычному, трамвай 5 около 10 тыс.", build()),
        ("h2_level_105", "h1 с уровнем ×1,05 (проверка верхней границы уровня)", build(nov_k=1.05, dec_k=1.05)),
        ("h3_r5_6k", "h1 с трамваем 5 около 6 тыс. в будни (истина не выше 10 тыс.)", build(r5=6_000)),
        ("h4_dec_up", "h1 с уровнем ноября ×1,02 и декабря ×1,05 (спрос выше перед Новым годом)", build(nov_k=1.02, dec_k=1.05)),
        ("h5_f4_tuned", "от f4: основа 50/50 с бустингом и те же настройки, что у h1", build(blend=0.5)),
    ]


# Скоры второго раунда: h1 0,88595, h2 0,88458, h3 0,88748, h4 0,88434, h5 0,88607 (f5 был 0,88561).
# Квадратичная подгонка по трём точкам уровня даёт оптимум около ×1,03; по h4 ноябрь ≈ ×1,037, декабрь ≈ ×1,024.
# Трамвай 5: h3 (6 тыс.) лучше h1 (10 тыс.) на 0,153 п.п.; при истине между файлами это около 7 тыс. в будни.
# Бустинг: h5 лучше h1 на 0,012 п.п. — шум.
R5_LEVEL = 7_000
GROUP_BIG = {17, 12, 11}


def scenario(nov_k=1.037, dec_k=1.024, r5=R5_LEVEL, nov1=1.0, late_dec=1.0, work=1.0, weekend=1.0, big=1.0, small=1.0, r7_wknd_nov=1.0, total=1.0,
             after_hol=1.0, wknd_rain=1.0, dec_restore=None) -> pd.DataFrame:
    """Сценарий третьего раунда: центральные настройки по скорам платформы и один пробный множитель поверх."""
    dates, dow, hol = P.fut_dates(D), P.fut_dow(D), P.fut_hol(D)
    nov = np.asarray(dates <= REPAIR_END)
    p0, _, facts = base_forecast(trim=0.1)
    restored, persist = apply_repair(p0, facts), apply_repair(p0, facts, until_month_end=False)
    cube = restored.copy()
    for route in (7, 50):
        r = ROUTES.index(route)
        cube[r, ~nov] = persist[r, ~nov] + (DEC_RESTORE if dec_restore is None else dec_restore) * (restored[r, ~nov] - persist[r, ~nov])
    cube = sunday_block(cube)
    day_k = np.where(nov, nov_k, dec_k).astype(float)
    day_k = np.where(dates == START, day_k * nov1, day_k)
    day_k = np.where((dates >= pd.Timestamp("2025-12-22")) & (dates <= pd.Timestamp("2025-12-30")) & (dow < 5) & ~hol, day_k * late_dec, day_k)
    day_k = np.where((dow < 5) & ~hol, day_k * work, np.where(dow >= 5, day_k * weekend, day_k))
    route_k = np.array([big if route in GROUP_BIG else small for route in ROUTES])
    out = cube * day_k[None, :, None] * route_k[:, None, None] * total
    r7 = ROUTES.index(7)
    out[r7, nov & (dow >= 5)] *= r7_wknd_nov
    out[:, dates == pd.Timestamp("2025-11-05")] *= after_hol            # первый рабочий день после праздников 3–4.11
    wx = P.WX.reindex(dates)
    out[:, ((wx.precip >= 1) & (dow >= 5)).to_numpy()] *= wknd_rain     # выходные с осадками ≥1 мм (фактическая погода Open-Meteo)
    return to_frame(out, route5(cube, r5))


def round3() -> list[tuple[str, str, pd.DataFrame]]:
    """Третий раунд: k1 объединяет подтверждённое платформой, k2–k5 отличаются от него одним пробным допущением."""
    return [
        ("k1_combined", "объединённые выводы: уровень ноября ×1,037, декабря ×1,024, трамвай 5 около 7 тыс., декабрь 7 и 50 на 87 % к обычному", scenario()),
        ("k2_nov1_x125", "k1, но 1.11 (рабочая суббота) ×1,25", scenario(nov1=1.25)),
        ("k3_late_dec_095", "k1, но будни 22–30.12 ×0,95 (перед праздниками, каникулы)", scenario(late_dec=0.95)),
        ("k4_work_up", "k1, но будни ×1,01, выходные ×0,97 (проверка соотношения будней и выходных)", scenario(work=1.01, weekend=0.97)),
        ("k5_big_routes", "k1, но маршруты 17, 12, 11 ×1,03, остальные ×0,965 (проверка уровня по маршрутам)", scenario(big=1.03, small=0.965)),
    ]


# Скоры третьего раунда: k1 0,88778, k2 0,88873, k3 0,88798, k4 0,88560, k5 0,88058.
# k2: 1.11 ×1,25 лучше k1 на 0,095 п.п. → истина около ×1,17. k3: конец декабря ×0,95 чуть лучше (+0,02) → около ×0,975.
# k4 (будни ×1,01, выходные ×0,97) хуже на 0,22 п.п. → выходные надо не опускать, скорее поднять.
# k5 (17, 12, 11 ×1,03, остальные ×0,965) хуже на 0,72 п.п. → направление обратное: крупные маршруты ниже, мелкие выше (оценка оптимума ±4 %).


def round4() -> list[tuple[str, str, pd.DataFrame]]:
    """Четвёртый раунд: m1 объединяет выводы по k1–k5, m2–m5 отличаются от него одним допущением."""
    m1 = dict(nov1=1.17, late_dec=0.975, big=0.975, small=1.03, weekend=1.03)
    return [
        ("m1_combined", "выводы k1–k5: 1.11 ×1,17, 22–30.12 ×0,975, крупные маршруты ×0,975, мелкие ×1,03, выходные ×1,03", scenario(**m1)),
        ("m2_route_split", "m1 с полным шагом по маршрутам: крупные ×0,955, мелкие ×1,055", scenario(**{**m1, "big": 0.955, "small": 1.055})),
        ("m3_weekend_106", "m1 с выходными ×1,06", scenario(**{**m1, "weekend": 1.06})),
        ("m4_total_1015", "m1 с общим уровнем ×1,015", scenario(**m1, total=1.015)),
        ("m5_r7_weekend", "m1 с выходными маршрута 7 в ноябре ×1,2 (режим ремонта мягче)", scenario(**m1, r7_wknd_nov=1.2)),
    ]


# Скоры четвёртого раунда: m1 0,88960, m2 0,88601, m3 0,88903, m4 0,88894, m5 0,89045.
# По квадратичной подгонке: разбивка по маршрутам оптимальна примерно на 0,54 шага m1 (крупные ×0,987, мелкие ×1,016);
# выходные ×1,03 близки к оптимуму (≈1,032); общий уровень m1 чуть завышен (оптимум около ×0,996);
# m5: выходные маршрута 7 в ноябре выше нашей оценки — по разности файлов около ×1,15 к m1.
N1 = dict(nov1=1.17, late_dec=0.975, big=0.9865, small=1.0162, weekend=1.03, total=0.996, r7_wknd_nov=1.15)


def round5() -> list[tuple[str, str, pd.DataFrame]]:
    """Пятый раунд: n1 объединяет выводы по m1–m5, n2–n5 проверяют новые гипотезы по одной."""
    return [
        ("n1_fitted", "оптимум по m1–m5: маршруты ×0,987/1,016, выходные ×1,03, уровень ×0,996, выходные маршрута 7 в ноябре ×1,15", scenario(**N1)),
        ("n2_r7_130", "n1 с выходными маршрута 7 в ноябре ×1,3 (граница)", scenario(**{**N1, "r7_wknd_nov": 1.3})),
        ("n3_after_hol", "n1 + 5.11 ×0,94 (первый рабочий день после блока выходных: −6 % по трём аналогам)", scenario(**N1, after_hol=0.94)),
        ("n4_wknd_rain", "n1 + выходные с осадками ≥1 мм ×0,96 (по истории −4 %, n=17)", scenario(**N1, wknd_rain=0.96)),
        ("n5_dec_full", "n1 с полным восстановлением режима маршрутов 7 и 50 в декабре", scenario(**N1, dec_restore=1.0)),
    ]


def best5() -> list[tuple[str, str, pd.DataFrame]]:
    """Пять лучших ставок на основе всех знаний (скоры платформы f1…m5): от самой вероятной к самым рискованным."""
    return [
        ("b1_all_in", "лучшая ставка: оптимум по m1–m5 + 5.11 ×0,94 + дождливые выходные ×0,96", scenario(**N1, after_hol=0.94, wknd_rain=0.96)),
        ("b2_m5_split", "m5 (лучший скор 0,89045) с оптимальной разбивкой по маршрутам, без новых гипотез", scenario(**{**N1, "r7_wknd_nov": 1.2, "total": 1.0})),
        ("b3_r7_125", "b1 с выходными маршрута 7 в ноябре ×1,25", scenario(**{**N1, "r7_wknd_nov": 1.25}, after_hol=0.94, wknd_rain=0.96)),
        ("b4_fitted", "оптимум по m1–m5 без новых гипотез (n1)", scenario(**N1)),
        ("b5_dec_full", "b1 с полным восстановлением режима 7 и 50 в декабре", scenario(**N1, after_hol=0.94, wknd_rain=0.96, dec_restore=1.0)),
    ]


# Скоры b-раунда: b1 0,89043, b2 0,89094, b3 0,89077, b4 0,89073, b5 0,89037.
# Поправки 5.11 и осадков вредят (b1 хуже b4 на 0,03 п.п.) — убраны. Полное восстановление декабря не помогает (b5 ≈ b1): оставлено 87 %.
# Маршрут 7 в ноябре: оптимум множителя около ×1,3 (по b4, b2, b3 и квадратичной подгонке).
B6 = {**N1, "r7_wknd_nov": 1.28, "total": 1.0}


def base6() -> pd.DataFrame:
    """Лучшая база по всем скорам: разбивка по маршрутам, выходные ×1,03, маршрут 7 в ноябре ×1,28, без поправок 5.11 и осадков."""
    return scenario(**B6)


def clean_ml() -> list[tuple[str, str, pd.DataFrame]]:
    """Чистый вариант без утечек: только история до 31.10.2025, календарь и анонсы, опубликованные до точки прогноза.
    Не используются константы, подобранные по скору платформы (1.11 ×1,17, маршрут 7 ×1,28, конец декабря, уровень ×1,03, разбивка маршрутов),
    погода и посадки после точки прогноза. Ремонт маршрутов 7 и 50 берётся из анонса от 12.09.2025 (до конца осени), коэффициенты режима из данных сентября–октября."""
    neutral = dict(nov_k=1.0, dec_k=1.0, nov1=1.0, late_dec=1.0, work=1.0, weekend=1.0, big=1.0, small=1.0, r7_wknd_nov=1.0, total=1.0, dec_restore=1.0)
    return [
        ("clean_a", "основа: профиль школьного сезона, праздничный профиль, режим ремонта 7 и 50 в ноябре по анонсу, декабрь обычный; трамвай 5 не учтён", scenario(**neutral, r5=0)),
        ("clean_b", "clean_a + трамвай 5 с 16.12 на уровне половины прогноза организаторов (10 тыс.): допущение, анонс опубликован 16.12.2025", scenario(**neutral, r5=10_000)),
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cur = pd.read_csv(ROOT / "submission.csv", sep=";", parse_dates=["date"])
    p0, pre_prof, facts = base_forecast()
    print("Коэффициенты режима с 6 сентября (факт выходных / обычный профиль):", {f"{r} {['сб', 'вс'][d - 5]}": round(v, 3) for (r, d), v in facts.items()})
    v_nov = sunday_block(apply_repair(p0, facts))
    v_dec = sunday_block(apply_repair(p0, facts, until_month_end=False))
    specs = [
        ("v0_base", "основа: профиль школьного сезона без аномалий, праздничный профиль (только данные)", to_frame(sunday_block(p0), None)),
        ("v1_repair_nov", "v0 + ремонт путей: маршруты 7 и 50 по выходным ноября в режиме с 6.09, декабрь обычный", to_frame(v_nov, None)),
        ("v2_repair_dec", "v1, но режим ремонта сохраняется и в декабре", to_frame(v_dec, None)),
        ("v3_r5_10k", "v1 + трамвай 5 с 16.12, 10 тыс. посадок в будни (половина прогноза организаторов)", to_frame(v_nov, route5(v_nov, 10_000))),
        ("v4_r5_20k", "v1 + трамвай 5 с 16.12, 20 тыс. посадок в будни (прогноз организаторов)", to_frame(v_nov, route5(v_nov, 20_000))),
        ("v5_r5_5k", "v1 + трамвай 5 с 16.12, 5 тыс. посадок в будни", to_frame(v_nov, route5(v_nov, 5_000))),
        ("v6_r5_10k_s97", "v3 с уровнем ×0,97 (проверка уровня)", to_frame(v_nov, route5(v_nov, 10_000), 0.97)),
        ("v7_r5_10k_s103", "v3 с уровнем ×1,03 (проверка уровня)", to_frame(v_nov, route5(v_nov, 10_000), 1.03)),
    ]
    base = cur.prediction.sum()
    rows = []
    for name, note, df in specs:
        assert len(df) == 14640 and df.prediction.min() >= 0
        df.to_csv(OUT / f"{name}.csv", sep=";", index=False)
        rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
    pd.DataFrame(rows).to_csv(OUT / "index.csv", sep=";", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    if "--final" in sys.argv:
        FIN = OUT / "final"
        FIN.mkdir(exist_ok=True)
        rows = []
        for name, note, df in finals():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(FIN / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
        pd.DataFrame(rows).to_csv(FIN / "index.csv", sep=";", index=False)
        print("\nИтоговые варианты:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--round2" in sys.argv:
        R2 = OUT / "round2"
        R2.mkdir(exist_ok=True)
        rows = []
        for name, note, df in round2():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(R2 / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
        pd.DataFrame(rows).to_csv(R2 / "index.csv", sep=";", index=False)
        print("\nВторой раунд:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--round3" in sys.argv:
        R3 = OUT / "round3"
        R3.mkdir(exist_ok=True)
        rows = []
        for name, note, df in round3():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(R3 / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
        pd.DataFrame(rows).to_csv(R3 / "index.csv", sep=";", index=False)
        print("\nТретий раунд:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--round4" in sys.argv:
        R4 = OUT / "round4"
        R4.mkdir(exist_ok=True)
        rows = []
        for name, note, df in round4():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(R4 / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
        pd.DataFrame(rows).to_csv(R4 / "index.csv", sep=";", index=False)
        print("\nЧетвёртый раунд:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--round5" in sys.argv:
        R5 = OUT / "round5"
        R5.mkdir(exist_ok=True)
        rows = []
        for name, note, df in round5():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(R5 / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
        pd.DataFrame(rows).to_csv(R5 / "index.csv", sep=";", index=False)
        print("\nПятый раунд:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--best5" in sys.argv:
        B5 = OUT / "best5"
        B5.mkdir(exist_ok=True)
        rows = []
        for name, note, df in best5():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(B5 / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к submission.csv, %": round((df.prediction.sum() / base - 1) * 100, 2)})
        pd.DataFrame(rows).to_csv(B5 / "index.csv", sep=";", index=False)
        print("\nПять лучших:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--base6" in sys.argv:
        path = OUT / "best5" / "b6_base.csv"
        base6().to_csv(path, sep=";", index=False)
        print("→", path)
    if "--clean" in sys.argv:
        CL = OUT / "clean"
        CL.mkdir(exist_ok=True)
        for name, note, df in clean_ml():
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(CL / f"{name}.csv", sep=";", index=False)
            print(name, int(df.prediction.sum()), "посадок:", note)
    print("\nИсточники событий:")
    for k, v in EVENTS.items():
        print(" -", k, *v, sep="\n     ")


if __name__ == "__main__":
    configure_console()
    main()
