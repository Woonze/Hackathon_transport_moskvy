"""Сырые валидации (train.csv, test.csv) → почасовые посадки маршрут × дата × час.

    python -m backend.ingest_raw                       # dataset/train.csv + test.csv → artifacts/hourly_from_raw.csv
    python -m backend.ingest_raw --input a.csv b.csv --out out.csv --chunk 1000000

Файлы читаются чанками и не загружаются в память целиком. После агрегации результат
сверяется с dataset/labels/labels_day_*.csv.
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from backend.app import config
from backend.app.console import configure_console
from backend.app.services.ingest import REQUIRED, aggregate, normalize


def ingest(paths: list, chunk: int) -> tuple[pd.DataFrame, Counter]:
    parts, total = [], Counter()
    for path in paths:
        started = time.perf_counter()
        reader = pd.read_csv(path, sep=";", usecols=list(REQUIRED), dtype=str, chunksize=chunk)
        for i, part in enumerate(reader, 1):
            boardings, stats = normalize(part)
            parts.append(aggregate(boardings))
            total.update(stats)
            if len(parts) >= 20:  # периодически схлопываем, чтобы не копить чанки
                parts = [aggregate_sum(parts)]
            print(f"\r{path.name}: чанк {i}, принято {total['accepted']:,}", end="", flush=True)
        print(f"  [{time.perf_counter() - started:.0f} с]")
    return aggregate_sum(parts), total


def aggregate_sum(parts: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(parts).groupby(["route", "date", "hour"], as_index=False)["boardings"].sum()


def compare(raw: pd.DataFrame) -> bool:
    labels = pd.concat([pd.read_csv(p, sep=";", parse_dates=["date"]) for p in config.LABELS])
    tail = raw[raw["date"] > labels["date"].max()]  # суточный «хвост» за пределами периода разметки
    raw = raw[raw["date"] <= labels["date"].max()]
    merged = labels.merge(raw, on=["route", "date", "hour"], how="outer", suffixes=("_labels", "_raw")).fillna(0)
    diff = merged["boardings_raw"] - merged["boardings_labels"]
    print(f"\nСверка с labels ({labels['date'].min().date()} … {labels['date'].max().date()}): строк {len(merged):,}, "
          f"расхождений {(diff != 0).sum():,}, сумма labels {int(merged['boardings_labels'].sum()):,}, "
          f"сумма raw {int(merged['boardings_raw'].sum()):,}")
    if len(tail):
        print(f"Хвост за пределами labels: {len(tail):,} строк, {int(tail['boardings'].sum()):,} посадок, "
              f"даты {tail['date'].min().date()} … {tail['date'].max().date()}")
    return bool((diff == 0).all())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="+", type=Path, default=[config.DATASET / "train.csv", config.DATASET / "test.csv"])
    parser.add_argument("--out", default=str(config.ARTIFACTS / "hourly_from_raw.csv"))
    parser.add_argument("--chunk", type=int, default=2_000_000)
    parser.add_argument("--no-compare", action="store_true")
    args = parser.parse_args()

    raw, stats = ingest(args.input, args.chunk)
    raw.sort_values(["route", "date", "hour"]).to_csv(args.out, sep=";", index=False, date_format="%Y-%m-%d")
    print(f"Строк во входе: {stats['rows']:,}; принято: {stats['accepted']:,}; отклонено по результату валидации: "
          f"{stats['rejected_validation']:,}; битый маршрут: {stats['bad_route']:,}; битое время: {stats['bad_time']:,}")
    print(f"Записано {len(raw):,} строк → {args.out}")
    if not args.no_compare:
        raise SystemExit(0 if compare(raw) else 1)


if __name__ == "__main__":
    configure_console()
    main()
