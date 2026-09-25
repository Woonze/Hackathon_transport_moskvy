"""Reproducible time-split comparison of supervised ML candidates.

All features for a holdout are built from observations before that holdout.
The script prints scores and never writes submission.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from model.forecast import load_calendar, load_history
from model.forecaster import _profile_features, dense_history

ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50]
WINDOWS = [
    ("May-Jun", "2025-05-01", "2025-06-30"),
    ("Jul-Aug", "2025-07-01", "2025-08-31"),
    ("Sep-Oct", "2025-09-01", "2025-10-31"),
]
OCTOBER = ("Oct", "2025-10-01", "2025-10-31")


def main() -> None:
    history = load_history()
    calendar = load_calendar()
    variants = [
        ("squared-base", "squared_error", 31, 100, 200),
        ("absolute-deep", "absolute_error", 63, 50, 300),
    ]
    results = {name: [] for name, *_ in variants}
    for window, start, end in [*WINDOWS, OCTOBER]:
        train = dense_history(history[history.date < start], ROUTES)
        target = dense_history(history[(history.date >= start) & (history.date <= end)], ROUTES)
        x_train, x_target = _profile_features(train, target, ROUTES, calendar)
        actual = target.boardings.to_numpy()
        for name, loss, leaves, min_leaf, iterations in variants:
            model = HistGradientBoostingRegressor(
                loss=loss,
                learning_rate=0.05,
                max_iter=iterations,
                max_leaf_nodes=leaves,
                min_samples_leaf=min_leaf,
                l2_regularization=10.0,
                categorical_features="from_dtype",
                early_stopping=False,
                random_state=42,
            )
            model.fit(x_train, train.boardings.to_numpy())
            predicted = np.maximum(model.predict(x_target), 0)
            predicted[target.route.eq(5).to_numpy()] = 0
            score = 1 - np.abs(actual - np.rint(predicted)).sum() / actual.sum()
            results[name].append(score)
        print(window, {name: round(scores[-1], 4) for name, scores in results.items()}, flush=True)
    print("mean3", {name: round(np.mean(scores[:3]), 4) for name, scores in results.items()})


if __name__ == "__main__":
    main()
