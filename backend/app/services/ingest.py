from __future__ import annotations

import pandas as pd

REQUIRED = ("tran_date_time", "validation_result", "ngpt_route")
_ROUTE = r"^\s*(\d+)\s*трамвай"


def normalize(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Сырые валидации → успешные посадки [route, date, hour] и счётчики отбраковки.

    Час и дата берутся только из tran_date_time (input_date_time ненадёжен),
    номер маршрута — из ngpt_route («25 трамвай» → 25).
    """
    stats = {"rows": len(df)}
    ok = pd.to_numeric(df["validation_result"], errors="coerce") == 1
    stats["rejected_validation"] = int((~ok).sum())
    df = df[ok]

    route = df["ngpt_route"].astype("string").str.extract(_ROUTE)[0]
    stats["bad_route"] = int(route.isna().sum())
    ts = pd.to_datetime(df["tran_date_time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    stats["bad_time"] = int((ts.isna() & route.notna()).sum())

    good = route.notna() & ts.notna()
    out = pd.DataFrame({"route": route[good].astype("int64"), "date": ts[good].dt.normalize(), "hour": ts[good].dt.hour})
    stats["accepted"] = len(out)
    return out, stats


def aggregate(boardings: pd.DataFrame) -> pd.DataFrame:
    return boardings.groupby(["route", "date", "hour"], as_index=False).size().rename(columns={"size": "boardings"})


def process(records: list[dict], batch_id: str | None, store) -> dict:
    """Нормализует пакет, дописывает в общий файл и обновляет историю текущего воркера."""
    import hashlib

    import orjson

    from .. import config
    from ..errors import ApiError
    from . import overlay

    df = pd.DataFrame.from_records(records)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ApiError(422, f"В записях нет обязательных полей: {', '.join(missing)}", "missing_fields")
    if batch_id is None:
        # A retry can arrive with rows in a different order. Hash the canonical
        # record set (keeping duplicates) so ordering alone cannot double count it.
        canonical_records = sorted(orjson.dumps(record, option=orjson.OPT_SORT_KEYS) for record in records)
        batch_id = hashlib.sha256(b"\n".join(canonical_records)).hexdigest()[:32]

    duplicates = 0
    if {"device_no", "tran_no"} <= set(df.columns):
        key = df["device_no"].notna() & df["tran_no"].notna()
        successful = pd.to_numeric(df["validation_result"], errors="coerce") == 1
        eligible = df.loc[key & successful]
        duplicate_ids = eligible.loc[eligible.duplicated(["device_no", "tran_no"])].index
        duplicates = len(duplicate_ids)
        # A failed attempt must not win the deduplication race against the
        # successful validation for the same transaction in this batch.
        df = df.drop(index=duplicate_ids)

    boardings, stats = normalize(df)
    known = boardings["route"].isin(store.routes)
    in_range = (boardings["date"] >= pd.Timestamp(config.HISTORY_START)) & (boardings["date"] <= pd.Timestamp(config.INGEST_MAX_DATE))
    rejected = {
        "validation_failed": stats["rejected_validation"],
        "bad_route_format": stats["bad_route"],
        "bad_time": stats["bad_time"],
        "unknown_route": int((~known).sum()),
        "date_out_of_range": int((known & ~in_range).sum()),
    }
    boardings = boardings[known & in_range]
    agg = aggregate(boardings)

    new = overlay.append(batch_id, agg) if len(agg) else True
    if new:
        store.refresh()
    return {
        "batch_id": batch_id,
        "status": "accepted" if new else "already_ingested",
        "received": len(records),
        "accepted": len(boardings) if new else 0,
        "duplicates": duplicates,
        "rejected": rejected,
        "period": [boardings["date"].min().date().isoformat(), boardings["date"].max().date().isoformat()] if len(boardings) else None,
        "history_end": store.history_end.isoformat(),
    }
