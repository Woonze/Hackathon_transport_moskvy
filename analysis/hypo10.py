"""Десять новых гипотез поверх эталона b2 (скор 0,89094): каждая — одно изменение, чтобы скор платформы показал знак и размер.

    python -m analysis.hypo10 [--ref файл.csv] [--combos]     → artifacts/candidates_v2/t10/t01…t10.csv, index.csv и совмещения combos/c1…c6.csv

Эталон: разбивка по маршрутам, выходные ×1,03, маршрут 7 в ноябре ×1,2, 1.11 ×1,17, 22–30.12 ×0,975.
Гипотезы опираются на данные:
  t01, t09 — свежий (8.09–31.10) уровень маршрута к профилю школьного сезона: маршрут 25 выше на 7–15 %, 12 и 7 ниже на 4 %;
  t02, t03 — свежая часовая форма: вечер и ночь ниже профиля, утро выходных выше;
  t04, t05 — праздничные будни вне января в 1,07 раза выше среднего праздничного дня (0,47 против 0,44 обычного будня);
  t06 — воскресенье и суббота могут отличаться от общего множителя выходных;
  t07, t10 — конец декабря и школьные каникулы с 29.12 (по календарю, в данных аналогов нет).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis import panel as P
from analysis.panel import D, DATES, DOW, HOL, ROUTES, Y
from backend.app.console import configure_console

ROOT = P.E.ROOT
OUT = ROOT / "artifacts" / "candidates_v2" / "t10"
BLOCKS = [(0, 6), (6, 10), (10, 16), (16, 20), (20, 24)]
BIG = {17, 12, 11}
SPLIT = {"big": 0.9865, "small": 1.0162}      # разбивка эталона: её заменяет t01 и t09


def autumn_ratios(since: str = "2025-09-08") -> tuple[dict, dict, float]:
    """свежий уровень (с даты since по 31.10, нормальные дни) к профилю школьного сезона: по маршрутам и часовым блокам, отдельно будни и выходные"""
    a = D
    mask = P.anomaly_mask(a) | P.SUMMER[:a][None, :]
    prof = P.profile(a, mask, trim=0.1)
    pred = np.stack([prof[:, DOW[i]] for i in range(a)], axis=1)
    ok = ((DATES[:a] >= pd.Timestamp(since)) & ~HOL[:a])[None, :] & ~mask
    typ = np.where(DOW[:a] < 5, 0, 1)
    total = (Y[:, :a] * ok[:, :, None]).sum() / (pred * ok[:, :, None]).sum()
    route, block = {}, {}
    for r, route_id in enumerate(ROUTES):
        for t in (0, 1):
            m = ok[r] & (typ == t)
            route[(route_id, t)] = Y[r, :a][m].sum() / max(pred[r][m].sum(), 1)
    for t in (0, 1):
        m = ok & (typ[None, :] == t)
        tt = (Y[:, :a] * m[:, :, None]).sum() / (pred * m[:, :, None]).sum()
        for k, (lo, hi) in enumerate(BLOCKS):
            block[(k, t)] = ((Y[:, :a, lo:hi] * m[:, :, None]).sum() / (pred[:, :, lo:hi] * m[:, :, None]).sum()) / tt
    return route, block, total


def apply(ref: pd.DataFrame, mult: np.ndarray) -> pd.DataFrame:
    out = ref.copy()
    out["prediction"] = np.maximum(np.rint(ref.prediction.to_numpy() * mult), 0).astype(int)
    return out


def build(ref: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    date, route, hour = ref.date, ref.route.to_numpy(), ref.hour.to_numpy()
    dow = date.dt.dayofweek.to_numpy()
    off = (dow >= 5) | date.isin(pd.to_datetime(["2025-11-03", "2025-11-04", "2025-12-31"])).to_numpy()
    nov = (date <= pd.Timestamp("2025-11-30")).to_numpy()
    r7_50_weekend = np.isin(route, (7, 50)) & off
    ratio_route, ratio_block, tot = autumn_ratios()

    def route_factor(shrink: float) -> np.ndarray:
        """заменяем разбивку эталона на свежие относительные уровни маршрутов (шаг shrink)"""
        m = np.ones(len(ref))
        for rid in ROUTES:
            for t in (0, 1):
                sel = (route == rid) & (off == bool(t))
                if rid in (7, 50) and t == 1:
                    continue
                rel = ratio_route[(rid, t)] / (tot if t == 0 else np.mean([ratio_route[(x, 1)] for x in ROUTES if x not in (7, 50)]))
                old = SPLIT["big"] if rid in BIG else SPLIT["small"]
                m[sel] = rel ** shrink / old
        return m

    def block_factor(t: int, shrink: float) -> np.ndarray:
        m = np.ones(len(ref))
        for k, (lo, hi) in enumerate(BLOCKS):
            sel = (hour >= lo) & (hour < hi) & (off == bool(t)) & (route != 5)
            m[sel] = ratio_block[(k, t)] ** shrink
        return m

    one = np.ones(len(ref))
    def day(dates, k):
        return np.where(date.isin(pd.to_datetime(dates)).to_numpy(), k, 1.0)

    t04 = day(["2025-11-03", "2025-11-04"], 1.07)
    t05 = day(["2025-12-31"], 1.15)
    sat, sun = dow == 5, dow == 6
    t06 = np.where(sat & ~r7_50_weekend, 0.99, np.where(sun & ~r7_50_weekend, 1.012, 1.0))
    t07 = np.where(((date >= pd.Timestamp("2025-12-15")) & (date <= pd.Timestamp("2025-12-30"))).to_numpy() & ~off, 0.985, 1.0)
    t08 = np.where(route == 25, 1.08, 1.0)
    t10 = day(["2025-12-29", "2025-12-30"], 0.97)
    return [
        ("t01_route_autumn", "уровни маршрутов по свежей осени вместо разбивки эталона (шаг 0,6)", apply(ref, route_factor(0.6))),
        ("t02_hours_weekday", "часовая форма будней по свежей осени: утро выше, вечер и ночь ниже (шаг 0,7)", apply(ref, block_factor(0, 0.7))),
        ("t03_hours_weekend", "часовая форма выходных по свежей осени (шаг 0,7)", apply(ref, block_factor(1, 0.7))),
        ("t04_holiday_nov", "праздники 3–4.11 ×1,07 (вне января праздничные дни выше)", apply(ref, t04)),
        ("t05_dec31", "31.12 ×1,15", apply(ref, t05)),
        ("t06_sat_sun", "суббота ×0,99, воскресенье ×1,012 (разное к общему множителю выходных)", apply(ref, t06)),
        ("t07_dec_late", "будни 15–30.12 ×0,985", apply(ref, t07)),
        ("t08_route25", "маршрут 25 ×1,08 (свежий уровень выше профиля на 7–15 %)", apply(ref, t08)),
        ("t09_route_full", "как t01, но полный шаг (1,0)", apply(ref, route_factor(1.0))),
        ("t10_school_break", "29–30.12 ×0,97 (школьные каникулы с конца декабря)", apply(ref, t10)),
    ]


# Скоры десяти гипотез (эталон b2 0,89094): t01 0,89184, t02 0,89105, t03 0,89075, t04 0,89120, t05 0,89002,
# t06 0,89089, t07 0,89065, t08 0,89083, t09 0,89232, t10 0,89138.
# Сработали: уровни маршрутов по свежей осени (t09 +0,138 п.п., полный шаг лучше 0,6; оптимум около шага 1,2), 29–30.12 ниже (+0,044; оптимум около ×0,98),
# праздники 3–4.11 выше (+0,026; оптимум около ×1,04), часовая форма будней (+0,011). Не сработали: 31.12 ×1,15 (−0,092), часы выходных, суббота и воскресенье отдельно,
# будни 15–30.12 ×0,985, маршрут 25 ×1,08.


def combo(ref: pd.DataFrame, route_s=1.0, route_since="2025-09-08", hours_wd=0.7, hol=1.04, dec2930=0.975, dec2628=1.0, nov5=1.0, hol_dec31=1.0,
          rb_shrink=0.0, dow_shrink=0.0, resid_since="2025-10-06", rb_blocks=None, rb_clip=0.1) -> pd.DataFrame:
    """Совмещение сработавших гипотез поверх эталона."""
    date, route, hour = ref.date, ref.route.to_numpy(), ref.hour.to_numpy()
    dow = date.dt.dayofweek.to_numpy()
    off = (dow >= 5) | date.isin(pd.to_datetime(["2025-11-03", "2025-11-04", "2025-12-31"])).to_numpy()
    ratio_route, ratio_block, tot = autumn_ratios(route_since)
    _, ratio_block_full, _ = autumn_ratios()
    mult = np.ones(len(ref))
    weekend_mean = np.mean([ratio_route[(x, 1)] for x in ROUTES if x not in (7, 50)])
    for rid in ROUTES:
        for t in (0, 1):
            if rid in (7, 50) and t == 1:
                continue
            sel = (route == rid) & (off == bool(t))
            rel = ratio_route[(rid, t)] / (tot if t == 0 else weekend_mean)
            old = SPLIT["big"] if rid in BIG else SPLIT["small"]
            mult[sel] = rel ** route_s / old
    for k, (lo, hi) in enumerate(BLOCKS):
        sel = (hour >= lo) & (hour < hi) & ~off & (route != 5)
        mult[sel] *= ratio_block_full[(k, 0)] ** hours_wd
    if rb_shrink or dow_shrink:
        rb_blocks = rb_blocks or BLOCKS
        rho, rho_dow = residual_ratios(route_s, route_since, hours_wd, resid_since, rb_blocks)
        if rb_shrink:
            for r_i, rid in enumerate(ROUTES):
                for t in (0, 1):
                    if rid in (7, 50) and t == 1:
                        continue
                    for k, (lo, hi) in enumerate(rb_blocks):
                        sel = (route == rid) & (off == bool(t)) & (hour >= lo) & (hour < hi)
                        mult[sel] *= float(np.clip(rho[r_i, t, k] ** rb_shrink, 1 - rb_clip, 1 + rb_clip))     # мелкие ячейки не раскачиваем
        if dow_shrink:
            mult *= (rho_dow[dow] ** dow_shrink) * ((route != 5) | True)
    mult *= np.where(date.isin(pd.to_datetime(["2025-11-03", "2025-11-04"])).to_numpy(), hol, 1.0)
    mult *= np.where(date.isin(pd.to_datetime(["2025-12-31"])).to_numpy(), hol_dec31, 1.0)
    mult *= np.where(date.isin(pd.to_datetime(["2025-12-29", "2025-12-30"])).to_numpy(), dec2930, 1.0)
    mult *= np.where(date.isin(pd.to_datetime(["2025-12-26", "2025-12-27", "2025-12-28"])).to_numpy(), dec2628, 1.0)
    mult *= np.where(date == pd.Timestamp("2025-11-05"), nov5, 1.0)
    return apply(ref, mult)


def residual_ratios(route_s, route_since, hours_wd, since, blocks=None) -> tuple[np.ndarray, np.ndarray]:
    """что осталось после уровней маршрутов и часовой формы: отношение фактических посадок за свежие недели к профилю с этими поправками
    по маршрут × тип дня × часовой блок (blocks — границы блоков, по умолчанию пять) и по дням недели"""
    blocks = blocks or BLOCKS
    a = D
    mask = P.anomaly_mask(a) | P.SUMMER[:a][None, :]
    prof = P.profile(a, mask, trim=0.1)
    pred = np.stack([prof[:, DOW[i]] for i in range(a)], axis=1)
    ratio_route, _, tot = autumn_ratios(route_since)
    _, ratio_block, _ = autumn_ratios()
    weekend_mean = np.mean([ratio_route[(x, 1)] for x in ROUTES if x not in (7, 50)])
    typ = np.where(DOW[:a] < 5, 0, 1)
    ok = ((DATES[:a] >= pd.Timestamp(since)) & ~HOL[:a])[None, :] & ~mask
    hour_k = np.zeros(24, int)
    for k, (lo, hi) in enumerate(BLOCKS):
        hour_k[lo:hi] = k
    adj = pred.copy()
    for r_i, rid in enumerate(ROUTES):
        for t in (0, 1):
            rel = ratio_route[(rid, t)] / (tot if t == 0 else weekend_mean)
            hf = np.array([ratio_block[(hour_k[h], t)] ** hours_wd if t == 0 else 1.0 for h in range(24)])
            adj[r_i][typ == t] = pred[r_i][typ == t] * (rel ** route_s) * hf[None, :]
    rho = np.ones((len(ROUTES), 2, len(blocks)))
    for r_i, rid in enumerate(ROUTES):
        for t in (0, 1):
            if (rid in (7, 50) and t == 1) or rid == 5:
                continue
            m = ok[r_i] & (typ == t)
            for k, (lo, hi) in enumerate(blocks):
                den = adj[r_i][m][:, lo:hi].sum()
                if den > 0:
                    rho[r_i, t, k] = Y[r_i, :a][m][:, lo:hi].sum() / den
    rho_dow = np.ones(7)
    for d in range(7):
        mm = ok & (DOW[:a] == d)[None, :]
        den = (adj * mm[:, :, None]).sum()
        rho_dow[d] = (Y[:, :a] * mm[:, :, None]).sum() / den if den > 0 else 1.0
    overall = (Y[:, :a] * ok[:, :, None]).sum() / max((adj * ok[:, :, None]).sum(), 1)
    return rho, rho_dow / overall



def round_c(ref: pd.DataFrame, d1: float = 0.0, d2: bool = False, d3: float = 0.0, hours_wd: float = 0.7, nov5: float = 1.0, rb_blocks=None, rb_clip=0.1) -> pd.DataFrame:
    """Совмещение находок раунда B поверх c3: d1 — шаг остаточных уровней маршрут × час, d2 — уровни маршрутов по трём неделям,
    d3 — шаг множителей по дням недели; общий уровень нормируется к c3 (меняется только структура)."""
    df = combo(ref, route_since="2025-10-13" if d2 else "2025-10-06", hours_wd=hours_wd, nov5=nov5, rb_shrink=d1, dow_shrink=d3, rb_blocks=rb_blocks, rb_clip=rb_clip)
    c3 = pd.read_csv(ROOT / "artifacts" / "candidates_v2" / "combos" / "c3_route_oct.csv", sep=";")
    df["prediction"] = np.maximum(np.rint(df.prediction * c3.prediction.sum() / df.prediction.sum()), 0).astype(int)
    return df


def combos(ref: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    return [
        ("c1_sum", "сумма сработавших: маршруты по осени (шаг 1,0), часы будней 0,7, 3–4.11 ×1,04, 29–30.12 ×0,975", combo(ref)),
        ("c2_route_125", "c1 с шагом по маршрутам 1,25 (экстраполяция: оптимум около 1,2)", combo(ref, route_s=1.25)),
        ("c3_route_oct", "c1 с уровнями маршрутов по октябрю (с 6.10) вместо сентября–октября", combo(ref, route_since="2025-10-06")),
        ("c4_hours_full", "c1 с часовой формой будней в полную силу (шаг 1,0)", combo(ref, hours_wd=1.0)),
        ("c5_dec_end", "c1 с концом декабря ниже: 26–28.12 ×0,985 и 29–30.12 ×0,97", combo(ref, dec2930=0.97, dec2628=0.985)),
        ("c6_nov5", "c1 с 5.11 ×0,97 (первый рабочий день после праздников)", combo(ref, nov5=0.97)),
    ]


# Скоры раунда A: c1 0,89288, c2 0,89287, c3 0,89306, c5 0,89289. Шаг по маршрутам 1,25 не лучше 1,0 (плато), уровни по октябрю лучше (+0,018), конец декабря нейтрален.
def round_b(ref: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    base = dict(route_since="2025-10-06")
    return [
        ("d1_route_hours", "c3 + остаточные уровни маршрут × часовой блок × тип дня по октябрю (шаг 0,5)", combo(ref, **base, rb_shrink=0.5)),
        ("d2_oct13", "c3 с уровнями маршрутов только по трём последним неделям (с 13.10)", combo(ref, route_since="2025-10-13")),
        ("d3_dow", "c3 + остаточные множители по дням недели по октябрю (шаг 0,6)", combo(ref, **base, dow_shrink=0.6)),
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ref_path = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else str(ROOT / "artifacts" / "candidates_v2" / "best5" / "b2_m5_split.csv")
    ref = pd.read_csv(ref_path, sep=";", parse_dates=["date"])
    rows = []
    for name, note, df in build(ref):
        assert len(df) == 14640 and df.prediction.min() >= 0
        df.to_csv(OUT / f"{name}.csv", sep=";", index=False)
        rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к эталону, %": round((df.prediction.sum() / ref.prediction.sum() - 1) * 100, 3),
                     "ячеек изменено": int((df.prediction != ref.prediction).sum())})
    pd.DataFrame(rows).to_csv(OUT / "index.csv", sep=";", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    if "--combos" in sys.argv:
        C = ROOT / "artifacts" / "candidates_v2" / "combos"
        C.mkdir(exist_ok=True)
        rows = []
        for name, note, df in combos(ref):
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(C / f"{name}.csv", sep=";", index=False)
            rows.append({"файл": f"{name}.csv", "описание": note, "сумма посадок": int(df.prediction.sum()), "к эталону, %": round((df.prediction.sum() / ref.prediction.sum() - 1) * 100, 3)})
        print("\nСовмещение:\n" + pd.DataFrame(rows).to_string(index=False))
    if "--roundc" in sys.argv:        # --roundc d1,d2,d3,hours [--blocks 5|8|12|24] [--clip 0.15] [--name имя]: итоговый файл f3 = 0.3,0,0,0.7 --blocks 24 --clip 0.15
        v = sys.argv[sys.argv.index("--roundc") + 1].split(",")
        nb = int(sys.argv[sys.argv.index("--blocks") + 1]) if "--blocks" in sys.argv else 5
        clip = float(sys.argv[sys.argv.index("--clip") + 1]) if "--clip" in sys.argv else 0.1
        blocks = {5: None, 8: [(0, 5), (5, 7), (7, 9), (9, 12), (12, 16), (16, 19), (19, 22), (22, 24)], 12: [(i, i + 2) for i in range(0, 24, 2)], 24: [(h, h + 1) for h in range(24)]}[nb]
        df = round_c(ref, d1=float(v[0]), d2=bool(int(float(v[1]))), d3=float(v[2]), hours_wd=float(v[3]), rb_blocks=blocks, rb_clip=clip)
        name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "roundc"
        Cd = ROOT / "artifacts" / "candidates_v2" / "roundc"
        Cd.mkdir(exist_ok=True)
        df.to_csv(Cd / f"{name}.csv", sep=";", index=False)
        print("→", Cd / f"{name}.csv", int(df.prediction.sum()))
    if "--roundb" in sys.argv:
        Bd = ROOT / "artifacts" / "candidates_v2" / "roundb"
        Bd.mkdir(exist_ok=True)
        rows = []
        for name, note, df in round_b(ref):
            assert len(df) == 14640 and df.prediction.min() >= 0
            df.to_csv(Bd / f"{name}.csv", sep=";", index=False)
            c3 = pd.read_csv(ROOT / "artifacts" / "candidates_v2" / "combos" / "c3_route_oct.csv", sep=";")
            rows.append({"файл": f"{name}.csv", "сумма посадок": int(df.prediction.sum()), "к c3, %": round((df.prediction.sum() / c3.prediction.sum() - 1) * 100, 3), "ячеек отличается от c3": int((df.prediction != c3.prediction).sum())})
        print("\nРаунд B:\n" + pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    configure_console()
    main()
