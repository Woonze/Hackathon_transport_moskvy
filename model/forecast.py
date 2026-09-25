"""Train and export the hourly tram boarding forecast for the hackathon."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.forecaster import fit_predict

DATA = ROOT / "dataset"
SUBMISSION_TEMPLATE = DATA / "test_submission.csv"
TRAIN_LABELS = DATA / "labels" / "labels_day_train.csv"
TEST_LABELS = DATA / "labels" / "labels_day_test.csv"
SUBMISSION_PATH = ROOT / "submission.csv"
FORECAST_PATH = ROOT / "artifacts" / "forecast.csv"
FORECAST_START = "2025-11-01"
FORECAST_END = "2025-12-31"

# Chosen from the Jan-Aug -> Sep-Oct rolling-origin backtest. A light
# multiplicative calibration compensates for the fall growth in boardings.
CALIBRATION = 1.086


def load_history() -> pd.DataFrame:
    frames = [pd.read_csv(TRAIN_LABELS, sep=";"), pd.read_csv(TEST_LABELS, sep=";")]
    history = pd.concat(frames, ignore_index=True)
    history["date"] = pd.to_datetime(history["date"])
    return history


def complete_grid(observed: pd.DataFrame, routes: list[int]) -> pd.DataFrame:
    days = pd.date_range(observed.date.min(), observed.date.max(), freq="D")
    grid = pd.MultiIndex.from_product(
        [routes, days, range(24)], names=["route", "date", "hour"]
    ).to_frame(index=False)
    values = observed.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum()
    grid = grid.merge(values, on=["route", "date", "hour"], how="left")
    grid["boardings"] = grid["boardings"].fillna(0).astype(float)
    grid["weekday"] = grid["date"].dt.dayofweek
    return grid


def predict_profile(history: pd.DataFrame, target: pd.DataFrame, calibration: float = CALIBRATION) -> pd.DataFrame:
    """Predict each route/hour using its historical weekday profile."""
    routes = sorted(set(target["route"].astype(int)))
    dense = complete_grid(history, routes)
    profile = (
        dense.groupby(["route", "weekday", "hour"], as_index=False)["boardings"]
        .mean()
        .rename(columns={"boardings": "prediction"})
    )
    out = target[["route", "date", "hour"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out["weekday"] = out["date"].dt.dayofweek
    out = out.merge(profile, on=["route", "weekday", "hour"], how="left")
    out["prediction"] = out["prediction"].fillna(0).clip(lower=0) * calibration
    out["prediction"] = np.rint(out["prediction"]).astype(int)
    return out[["route", "date", "hour", "prediction"]]


def load_calendar() -> dict:
    path = ROOT / "artifacts" / "external" / "calendar_2025.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path, parse_dates=["date"])
    return {d.date(): kind for d, kind in zip(frame.date, frame.day_type)}


def predict_ml(history: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    routes = sorted(pd.read_csv(SUBMISSION_TEMPLATE, sep=";").route.unique().astype(int))
    fitted = fit_predict(history, target, routes, load_calendar())
    return fitted.predictions


def backtest(history: pd.DataFrame, model_name: str = "ml", start="2025-09-01", end="2025-10-31") -> tuple[float, float]:
    """Train strictly before the holdout and score every route×date×hour cell."""
    cutoff = pd.Timestamp(start)
    end = pd.Timestamp(end)
    observed = history[(history["date"] >= cutoff) & (history["date"] <= end)].copy()
    routes = sorted(pd.read_csv(SUBMISSION_TEMPLATE, sep=";").route.unique().astype(int))
    days = pd.date_range(cutoff, end, freq="D")
    target = pd.MultiIndex.from_product(
        [routes, days, range(24)], names=["route", "date", "hour"]
    ).to_frame(index=False)
    train = history[history["date"] < cutoff]
    predicted = predict_ml(train, target) if model_name == "ml" else predict_profile(train, target, calibration=1.0)
    actual = target.merge(
        observed.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum(),
        on=["route", "date", "hour"], how="left",
    )["boardings"].fillna(0).to_numpy()
    forecast = predicted["prediction"].to_numpy()
    total = actual.sum()
    wape = float(np.abs(actual - forecast).sum() / total) if total else 0.0
    return wape, max(0.0, 1.0 - wape)


def rolling_backtest(history: pd.DataFrame, model_name: str = "ml") -> list[tuple[str, float, float]]:
    """Три независимых двухмесячных окна и дополнительный пересекающийся октябрь."""
    windows = [
        ("май–июнь", "2025-05-01", "2025-06-30"),
        ("июль–август", "2025-07-01", "2025-08-31"),
        ("сентябрь–октябрь", "2025-09-01", "2025-10-31"),
        ("октябрь", "2025-10-01", "2025-10-31"),
    ]
    results = []
    for name, start, end in windows:
        wape, score = backtest(history, model_name, start, end)
        results.append((name, wape, score))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action="store_true", help="Evaluate the Sep-Oct holdout")
    parser.add_argument("--rolling-backtest", action="store_true", help="Evaluate three disjoint windows and supplemental October")
    parser.add_argument("--model", choices=("ml", "profile"), default="ml", help="ml = trained HistGradientBoosting model; profile = previous baseline")
    parser.add_argument("--calibration", type=float, default=CALIBRATION, help="Used only with --model profile")
    args = parser.parse_args()

    history = load_history()
    template = pd.read_csv(SUBMISSION_TEMPLATE, sep=";")
    if args.backtest:
        wape, score = backtest(history, args.model)
        print(f"Sep-Oct {args.model} WAPE: {wape:.4f}; WAPE-score: {score:.4f}")
    if args.rolling_backtest:
        results = rolling_backtest(history, args.model)
        for name, wape, score in results:
            print(f"{name:<20} WAPE: {wape:.4f}; WAPE-score: {score:.4f}")
        print(f"Средний score по трём непересекающимся окнам: {np.mean([row[2] for row in results[:3]]):.4f}")

    submission = predict_ml(history, template) if args.model == "ml" else predict_profile(history, template, calibration=args.calibration)
    submission["date"] = submission["date"].dt.strftime("%Y-%m-%d")
    submission.to_csv(SUBMISSION_PATH, sep=";", index=False, encoding="utf-8")
    submission.to_csv(FORECAST_PATH, sep=";", index=False, encoding="utf-8")
    print(f"Saved {len(submission):,} predictions to {SUBMISSION_PATH}")
    if args.model == "ml":
        print("Model: HistGradientBoostingRegressor; predicted boardings:", f"{submission.prediction.sum():,}")
    else:
        print(f"Model: weekday profile; calibration {args.calibration:.3f}; predicted boardings: {submission.prediction.sum():,}")


if __name__ == "__main__":
    main()
