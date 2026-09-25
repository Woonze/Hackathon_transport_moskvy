"""Train and export the hourly tram boarding forecast for the hackathon."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
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


def backtest(history: pd.DataFrame) -> tuple[float, float]:
    """Hold out Sep-Oct and mimic the final two-month forecast horizon."""
    cutoff = pd.Timestamp("2025-09-01")
    observed = history[history["date"] >= cutoff].copy()
    routes = sorted(history["route"].astype(int).unique())
    days = pd.date_range(cutoff, "2025-10-31", freq="D")
    target = pd.MultiIndex.from_product(
        [routes, days, range(24)], names=["route", "date", "hour"]
    ).to_frame(index=False)
    predicted = predict_profile(history[history["date"] < cutoff], target)
    actual = target.merge(
        observed.groupby(["route", "date", "hour"], as_index=False)["boardings"].sum(),
        on=["route", "date", "hour"], how="left",
    )["boardings"].fillna(0).to_numpy()
    forecast = predicted["prediction"].to_numpy()
    total = actual.sum()
    wape = float(np.abs(actual - forecast).sum() / total) if total else 0.0
    return wape, max(0.0, 1.0 - wape)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action="store_true", help="Evaluate Sep-Oct holdout")
    parser.add_argument("--calibration", type=float, default=CALIBRATION)
    args = parser.parse_args()

    history = load_history()
    template = pd.read_csv(SUBMISSION_TEMPLATE, sep=";")
    if args.backtest:
        wape, score = backtest(history)
        print(f"Sep-Oct WAPE: {wape:.4f}; WAPE-score: {score:.4f}")

    submission = predict_profile(history, template, calibration=args.calibration)
    submission["date"] = submission["date"].dt.strftime("%Y-%m-%d")
    submission.to_csv(SUBMISSION_PATH, sep=";", index=False, encoding="utf-8")
    submission.to_csv(FORECAST_PATH, sep=";", index=False, encoding="utf-8")
    print(f"Saved {len(submission):,} predictions to {SUBMISSION_PATH}")
    print(f"Calibration: {args.calibration:.3f}; predicted boardings: {submission.prediction.sum():,}")


if __name__ == "__main__":
    main()
