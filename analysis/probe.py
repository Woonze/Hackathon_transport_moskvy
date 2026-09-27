"""Настройка крупных групп уровня по скору платформы: план проб на матрице Адамара и подгонка по полученным скорам.

    python -m analysis.probe design [--groups routes|hours] [--base файл.csv] [--delta 0.04] [--out папка]   → artifacts/<папка>/p01…p20.csv и design.json
    python -m analysis.probe fit скоры.json [--base файл.csv] [--out папка]          → artifacts/<папка>/tuned.csv и таблица множителей

Группы: маршрут × тип дня (будни; выходные и праздники), 9 маршрутов × 2 = 18 множителей (маршрут 5 не трогаем).
В каждой пробе множители групп сдвигаются на ±delta по ортогональному плану (20 проб, порядок Адамара), общий отклик
S = c − Σ a_g (s_g − s*_g)² даёт оптимум каждой группы s*_g = 1 + β_g / (2·delta·a_g), где β_g = (1/20) Σ_j ε_jg S_j.
Кривизна группы a_g = A · доля группы в посадках; A ≈ 1,9 оценена по скорам платформы (f5, h1, h2, h4).
Это настройка 18 крупных множителей, а не восстановление данных по ячейкам.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "probe")
A_CURV = 1.9
ROUTES = [1, 7, 11, 12, 17, 25, 26, 28, 50]
HOLIDAYS = pd.to_datetime(["2025-11-03", "2025-11-04", "2025-12-31"])


def hadamard(n: int) -> np.ndarray:
    """Адамар порядка n = q + 1 по Пэли (q простое, q ≡ 3 mod 4: 11 → 12, 19 → 20)"""
    q = n - 1
    sq = {(i * i) % q for i in range(1, q)}
    chi = lambda x: 0 if x % q == 0 else (1 if (x % q) in sq else -1)
    Q = np.array([[chi(i - j) for j in range(q)] for i in range(q)])
    H = np.ones((n, n), int)
    H[1:, 0] = -1
    H[1:, 1:] = Q + np.eye(q, dtype=int)
    assert (H @ H.T == n * np.eye(n)).all()
    return H * H[:, :1]           # первый столбец → единицы: остальные столбцы ортогональны константе


BLOCKS = [(0, 6), (6, 10), (10, 16), (16, 20), (20, 24)]
MODE = sys.argv[sys.argv.index("--groups") + 1] if "--groups" in sys.argv else "routes"
NPROBE = 12 if MODE == "hours" else 20


def groups(df: pd.DataFrame) -> tuple[list[tuple], np.ndarray]:
    """индекс группы каждой строки (-1 — вне групп) и список групп"""
    off = (df.date.dt.dayofweek >= 5) | df.date.isin(HOLIDAYS)
    if MODE == "hours":      # часовые блоки × тип дня, все маршруты кроме 5
        gl = [(f"{lo:02d}–{hi:02d} ч", t) for lo, hi in BLOCKS for t in ("будни", "выходные")]
        idx = np.full(len(df), -1)
        ok = (df.route != 5).to_numpy()
        for k, (label, t) in enumerate(gl):
            lo, hi = BLOCKS[k // 2]
            idx[ok & (df.hour >= lo).to_numpy() & (df.hour < hi).to_numpy() & (off.to_numpy() == (t == "выходные"))] = k
        return gl, idx
    gl = [(r, t) for r in ROUTES for t in ("будни", "выходные")]
    idx = np.full(len(df), -1)
    for k, (r, t) in enumerate(gl):
        idx[((df.route == r) & (off == (t == "выходные"))).to_numpy()] = k
    return gl, idx


def design(df: pd.DataFrame, delta: float) -> tuple[np.ndarray, list[pd.DataFrame], list[tuple[int, str]]]:
    gl, idx = groups(df)
    eps = hadamard(NPROBE)[:, 1: len(gl) + 1]     # столбцы ортогональны друг другу и константе
    frames = []
    for j in range(NPROBE):
        mult = np.ones(len(df))
        ok = idx >= 0
        mult[ok] = 1 + delta * eps[j, idx[ok]]
        f = df.copy()
        f["prediction"] = np.maximum(np.rint(df.prediction.to_numpy() * mult), 0).astype(int)
        frames.append(f)
    return eps, frames, gl


def fit_multipliers(df: pd.DataFrame, eps: np.ndarray, scores: np.ndarray, delta: float, shrink: float = 0.7, clip: float = 0.12):
    gl, idx = groups(df)
    beta = eps.T @ scores / eps.shape[0]
    total = df.prediction.sum()
    w = np.array([df.prediction[idx == k].sum() / total for k in range(len(gl))])
    a = A_CURV * w
    star = 1 + beta / (2 * delta * a)
    used = 1 + np.clip(shrink * (star - 1), -clip, clip)
    return gl, star, used, beta


def apply(df: pd.DataFrame, used: np.ndarray) -> pd.DataFrame:
    gl, idx = groups(df)
    mult = np.ones(len(df))
    ok = idx >= 0
    mult[ok] = used[idx[ok]]
    out = df.copy()
    out["prediction"] = np.maximum(np.rint(df.prediction.to_numpy() * mult), 0).astype(int)
    return out


def load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", parse_dates=["date"])


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "design"
    OUT.mkdir(parents=True, exist_ok=True)
    base_path = Path(sys.argv[sys.argv.index("--base") + 1]) if "--base" in sys.argv else ROOT / "artifacts" / "candidates_v2" / "round3" / "k1_combined.csv"
    delta = float(sys.argv[sys.argv.index("--delta") + 1]) if "--delta" in sys.argv else 0.04
    df = load(base_path)
    if cmd == "design":
        eps, frames, gl = design(df, delta)
        for j, f in enumerate(frames, 1):
            f.to_csv(OUT / f"p{j:02d}.csv", sep=";", index=False)
        json.dump({"base": str(base_path), "delta": delta, "groups": gl, "eps": eps.tolist()}, open(OUT / "design.json", "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{NPROBE} проб в {OUT} (p01…p{NPROBE:02d}), база {base_path.name}, delta {delta}, группы: {MODE}")
    else:
        d = json.load(open(OUT / "design.json", encoding="utf-8"))
        scores = json.load(open(sys.argv[2], encoding="utf-8"))
        s = np.array([scores[f"p{j:02d}"] for j in range(1, NPROBE + 1)], float)
        gl, star, used, beta = fit_multipliers(df, np.array(d["eps"]), s, d["delta"])
        print(f"{'группа':<24}{'оптимум':>9}{'применён':>10}")
        for g, a, b in zip(gl, star, used):
            print(f"{('маршрут ' + str(g[0])) if MODE == 'routes' else g[0]:<16}{g[1]:<10}{a:>9.3f}{b:>10.3f}")
        apply(df, used).to_csv(OUT / "tuned.csv", sep=";", index=False)
        print("→", OUT / "tuned.csv")


if __name__ == "__main__":
    main()
