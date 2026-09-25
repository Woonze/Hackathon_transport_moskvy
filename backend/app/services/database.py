from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone

import pandas as pd
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..errors import ApiError
from . import overlay

log = logging.getLogger("tram.database")

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS auth_users (
        username text PRIMARY KEY,
        password_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash char(64) PRIMARY KEY,
        username text NOT NULL REFERENCES auth_users(username) ON DELETE CASCADE,
        created_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS auth_sessions_expiry_idx ON auth_sessions (expires_at)",
    """CREATE TABLE IF NOT EXISTS ingest_batches (
        batch_id text PRIMARY KEY,
        payload_hash char(64) NOT NULL,
        complete boolean NOT NULL DEFAULT false,
        accepted integer NOT NULL DEFAULT 0,
        received_at timestamptz NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS ingested_aggregates (
        batch_id text NOT NULL REFERENCES ingest_batches(batch_id) ON DELETE CASCADE,
        route integer NOT NULL,
        service_date date NOT NULL,
        hour smallint NOT NULL CHECK (hour BETWEEN 0 AND 23),
        boardings integer NOT NULL CHECK (boardings >= 0),
        PRIMARY KEY (batch_id, route, service_date, hour)
    )""",
    "CREATE INDEX IF NOT EXISTS ingested_aggregates_date_idx ON ingested_aggregates (service_date, route)",
    """CREATE TABLE IF NOT EXISTS app_state (
        key text PRIMARY KEY,
        value bigint NOT NULL DEFAULT 0
    )""",
    "INSERT INTO app_state (key, value) VALUES ('ingest_revision', 0) ON CONFLICT (key) DO NOTHING",
)


class Database:
    """Small PostgreSQL adapter for sessions and durable validation ingestion."""

    def __init__(self, dsn: str):
        self.pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=12,
            timeout=15,
            kwargs={"row_factory": dict_row},
            open=False,
        )

    def open(self) -> None:
        self.pool.open(wait=True, timeout=30)
        with self.pool.connection() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)

    def close(self) -> None:
        self.pool.close()

    def ensure_user(self, username: str, password_hash: str) -> None:
        if not password_hash:
            raise RuntimeError("AUTH_PASSWORD_HASH is required when PostgreSQL is enabled")
        with self.pool.connection() as conn:
            # The deployment is single-account by design. A changed configured
            # login replaces the old one and invalidates all previous sessions.
            conn.execute("DELETE FROM auth_users WHERE username <> %s", (username,))
            conn.execute("DELETE FROM auth_sessions WHERE username = %s", (username,))
            conn.execute(
                """INSERT INTO auth_users (username, password_hash) VALUES (%s, %s)
                   ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash,
                   updated_at = now()""",
                (username, password_hash),
            )

    def get_user(self, username: str) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT username, password_hash FROM auth_users WHERE username = %s",
                (username,),
            ).fetchone()

    def create_session(self, username: str, token_hash: str, created_at: datetime, expires_at: datetime) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE expires_at <= now()")
            conn.execute(
                "INSERT INTO auth_sessions (token_hash, username, created_at, expires_at) VALUES (%s, %s, %s, %s)",
                (token_hash, username, created_at, expires_at),
            )

    def session_user(self, token_hash: str) -> str | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT username FROM auth_sessions WHERE token_hash = %s AND expires_at > now()",
                (token_hash,),
            ).fetchone()
            return row["username"] if row else None

    def delete_session(self, token_hash: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (token_hash,))

    @staticmethod
    def _payload_hash(agg: pd.DataFrame, complete: bool) -> str:
        rows = sorted(
            (int(route), pd.Timestamp(day).date().isoformat(), int(hour), int(count))
            for route, day, hour, count in agg[["route", "date", "hour", "boardings"]].itertuples(index=False, name=None)
        )
        content = repr((bool(complete), rows)).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def append_batch(self, batch_id: str, agg: pd.DataFrame, complete: bool = False) -> bool:
        """Atomically store a batch and its hourly rollups; reject conflicting retries."""
        payload_hash = self._payload_hash(agg, complete)
        with self.pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (batch_id,))
            existing = conn.execute(
                "SELECT payload_hash FROM ingest_batches WHERE batch_id = %s FOR UPDATE", (batch_id,)
            ).fetchone()
            if existing:
                if existing["payload_hash"].strip() == payload_hash:
                    return False
                raise ApiError(409, "Идентификатор пакета уже использован для других данных", "batch_id_conflict")

            conn.execute(
                "INSERT INTO ingest_batches (batch_id, payload_hash, complete, accepted) VALUES (%s, %s, %s, %s)",
                (batch_id, payload_hash, complete, int(agg.boardings.sum()) if len(agg) else 0),
            )
            if len(agg):
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO ingested_aggregates (batch_id, route, service_date, hour, boardings)
                           VALUES (%s, %s, %s, %s, %s)""",
                        [
                            (batch_id, int(route), pd.Timestamp(day).date(), int(hour), int(count))
                            for route, day, hour, count in agg[["route", "date", "hour", "boardings"]].itertuples(index=False, name=None)
                        ],
                    )
            conn.execute("UPDATE app_state SET value = value + 1 WHERE key = 'ingest_revision'")
            return True

    def ingest_revision(self) -> int:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = 'ingest_revision'").fetchone()
            return int(row["value"])

    def read_ingested(self) -> pd.DataFrame:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT a.batch_id, a.route, a.service_date AS date, a.hour, a.boardings, b.complete
                   FROM ingested_aggregates AS a JOIN ingest_batches AS b USING (batch_id)
                   ORDER BY a.service_date, a.route, a.hour, a.batch_id"""
            ).fetchall()
        if not rows:
            return overlay.empty()
        frame = pd.DataFrame.from_records(rows)
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.astype({"route": "int64", "hour": "int64", "boardings": "int64", "complete": "bool"})
