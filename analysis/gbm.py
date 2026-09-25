"""Градиентный бустинг (Пуассон) на признаках дня: календарь, длина блока выходных, лето, погода. Нужен scikit-learn."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from analysis import panel as P
from analysis.panel import CAL, FUT_N, R, WX, Y

FULL = pd.date_range("2025-01-01", "2025-12-31")
_code = CAL.reindex(FULL).code.fillna(0).to_numpy()
_blk = np.zeros(len(FULL), int)
_i = 0
while _i < len(FULL):
    if _code[_i] == 1:
        _j = _i
        while _j < len(FULL) and _code[_j] == 1:
            _j += 1
        _blk[_i:_j] = _j - _i
        _i = _j
    else:
        _i += 1


def frame(day_idx, feats):
    dates = FULL[day_idx]
    t = CAL.reindex(FULL).loc[dates]
    cols = {"dow": dates.dayofweek.to_numpy(), "hol": (t.day_type == "holiday").astype(int).to_numpy(),
            "short": (t.day_type == "short").astype(int).to_numpy(), "blk": _blk[day_idx]}
    if "wx" in feats:
        w = WX.reindex(FULL).loc[dates]
        cols.update(precip=w.precip.fillna(0).to_numpy(), snow=w.snow.fillna(0).to_numpy(), tmean=w.tmean.fillna(8).to_numpy())
    if "summer" in feats:
        cols["summer"] = np.array([d.month in (6, 7, 8) for d in dates]).astype(int)
    day, n = pd.DataFrame(cols), len(day_idx)
    ridx, didx, hh = np.repeat(np.arange(R), n * 24), np.tile(np.repeat(np.arange(n), 24), R), np.tile(np.arange(24), R * n)
    X = day.iloc[didx].reset_index(drop=True)
    X["route"], X["hour"] = ridx, hh
    return X, ridx, didx


def predict(a, feats=("summer",)):
    X, ridx, didx = frame(np.arange(a), feats)
    w = (~P.anomaly_mask(a)[ridx, didx]).astype(float) + 1e-6
    m = HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=0.06, max_leaf_nodes=40, categorical_features=["route"], random_state=0)
    m.fit(X, Y[:, :a].reshape(-1), sample_weight=w)
    Xf, _, _ = frame(np.minimum(a + np.arange(FUT_N), len(FULL) - 1), feats)
    return m.predict(Xf).reshape(R, FUT_N, 24)
